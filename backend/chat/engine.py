"""Conversation engine: the UC01 -> UC03 decision policy.

For every customer message:
  1. Score sentiment (logged only, never used to decide escalation).
  2. If the chat is already with a specialist, relay the message to them.
  3. Explicit request for a human           -> escalate (customer_request).
  4. Greeting / thanks / goodbye             -> canned small-talk reply.
  5. Intent confidence >= threshold          -> templated answer for that intent.
  6. Otherwise: retrieve relevant FAQ entries and let the LLM answer ONLY from them.
     No relevant entry, LLM says "not answerable", LLM unavailable or over budget
                                             -> escalate (low_confidence).

Step 6 is the agreed reconciliation of UC01 ("generative fallback") with UC03
("escalate below 60%"): below the threshold the bot never improvises; it either
quotes the business's own knowledge base or hands over to a human.
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field

from django.conf import settings
from django.db import IntegrityError

from buddy.sentiment import analyse
from core import llm
from core.models import BusinessProfile

from . import events
from .knowledge import faq_index
from .models import ChatSession, Escalation, Message, new_reference
from .nlu.base import OUT_OF_SCOPE, get_intent_engine, load_intents

log = logging.getLogger(__name__)

AI_DISCLOSURE = (
    "You're chatting with an AI assistant. It can make mistakes, and you can ask for a person at any time."
)

_PERSON = r"(?:a\s+|an\s+|the\s+|some\s*)?(?:human|person|real\s+person|someone|somebody|staff(?:\s+member)?|agent|representative|specialist|manager|team|customer\s+service)"
_HUMAN_REQUEST = re.compile(
    rf"\b(?:(?:speak|talk|chat)\s+(?:to|with)\s+{_PERSON}|(?:transfer|connect|put)\s+me\s+(?:to|through\s+to|with)\s+{_PERSON}"
    r"|real\s+(?:person|human)|live\s+(?:agent|person|chat)|human\s+please)\b",
    re.IGNORECASE,
)
_GREETING = re.compile(r"^\s*(hi|hello|hey|hiya|g'?day|good\s+(morning|afternoon|evening))\b[\s!.,a-z]{0,12}$", re.IGNORECASE)
_THANKS = re.compile(r"^\s*(thanks|thank\s+you|cheers|ta|much appreciated)\b.{0,30}$", re.IGNORECASE)
_BYE = re.compile(r"^\s*(bye|goodbye|see\s+ya|that'?s\s+all|no\s+thanks)\b.{0,20}$", re.IGNORECASE)

_EMPATHY = {
    "warm": "I'm sorry you're dealing with this. ",
    "professional": "I understand this is frustrating. ",
    "upbeat": "Sorry about the hassle, let's sort it out. ",
}


@dataclass
class TurnResult:
    messages: list[dict] = field(default_factory=list)
    session_status: str = ChatSession.ACTIVE
    escalation: dict | None = None
    actions: list[str] = field(default_factory=list)


def escalation_payload(esc: Escalation, session: ChatSession) -> dict:
    return {
        "id": esc.id,
        "reference": esc.reference,
        "reason": esc.reason,
        "status": esc.status,
        "session_id": str(session.id),
        "customer_name": session.customer_name,
        "trigger_text": esc.trigger_text,
        "trigger_confidence": esc.trigger_confidence,
        "created_at": esc.created_at.isoformat(),
    }


async def add_message(session: ChatSession, role: str, text: str, source: str, **fields) -> Message:
    return await Message.objects.acreate(session=session, role=role, text=text, source=source, **fields)


async def start_session() -> tuple[ChatSession, str, list[dict]]:
    token, token_hash = ChatSession.issue_token()
    session = await ChatSession.objects.acreate(token_hash=token_hash)
    profile = await BusinessProfile.aget_solo()
    greeting = await add_message(session, Message.BOT, f"{profile.buddy_greeting}\n\n{AI_DISCLOSURE}", "system")
    return session, token, [greeting.as_dict()]


async def transcript(session: ChatSession) -> list[dict]:
    return [m.as_dict() async for m in session.messages.all()]


async def escalate(session: ChatSession, reason: str, trigger_text: str = "", confidence: float | None = None) -> tuple[Escalation, Message | None]:
    """Hand the session to a human with the complete transcript. Idempotent per session."""
    existing = await Escalation.objects.filter(session=session).exclude(status=Escalation.RESOLVED).afirst()
    if existing:
        return existing, None
    snapshot = await transcript(session)
    esc = None
    for _ in range(5):  # reference collisions are astronomically unlikely, but retry rather than fail
        try:
            esc = await Escalation.objects.acreate(
                reference=new_reference("ESC"),
                session=session,
                reason=reason,
                trigger_text=trigger_text[:1000],
                trigger_confidence=confidence,
                transcript=snapshot,
            )
            break
        except IntegrityError:
            existing = await Escalation.objects.filter(session=session).exclude(status=Escalation.RESOLVED).afirst()
            if existing:
                return existing, None
    if esc is None:
        raise RuntimeError("Could not allocate an escalation reference")

    session.status = ChatSession.ESCALATED
    await session.asave(update_fields=["status", "updated_at"])
    why = "as you asked" if reason == Escalation.CUSTOMER_REQUEST else "so you get an accurate answer"
    notice = await add_message(
        session,
        Message.SYSTEM,
        f"I've passed this conversation to our team {why}. Your case reference is {esc.reference}. "
        "A specialist can see everything we've discussed, so you won't need to repeat yourself. "
        "Please leave your name and email or phone so they can follow up if you step away.",
        "escalation",
    )
    await events.to_staff("escalation.new", escalation_payload(esc, session))
    await events.to_customer(session.id, "session.status", {"status": session.status, "escalation": esc.reference})
    return esc, notice


def _render(template: str, profile: BusinessProfile) -> str:
    return template.format(
        business_name=profile.business_name,
        opening_hours=profile.opening_hours,
        phone=profile.phone,
        email=profile.email,
        address=profile.address,
    )


async def handle_customer_message(session: ChatSession, text: str, channel: str = "text") -> TurnResult:
    text = text.strip()
    sentiment = analyse(text)
    customer_msg = await add_message(
        session,
        Message.CUSTOMER,
        text,
        "customer",
        channel=channel,
        sentiment_label=sentiment.label,
        sentiment_score=sentiment.score,
    )
    result = TurnResult(messages=[customer_msg.as_dict()], session_status=session.status)

    if session.status == ChatSession.ESCALATED:
        esc = await Escalation.objects.filter(session=session).exclude(status=Escalation.RESOLVED).afirst()
        await events.to_staff(
            "message.new",
            {"session_id": str(session.id), "escalation_id": esc.id if esc else None, "message": customer_msg.as_dict()},
        )
        return result

    profile = await BusinessProfile.aget_solo()

    async def reply(body: str, source: str, **fields):
        msg = await add_message(session, Message.BOT, body, source, channel=channel, **fields)
        result.messages.append(msg.as_dict())

    async def hand_over(reason: str, confidence: float | None):
        esc, notice = await escalate(session, reason, text, confidence)
        if notice:
            result.messages.append(notice.as_dict())
        result.session_status = session.status
        result.escalation = escalation_payload(esc, session)

    if _HUMAN_REQUEST.search(text):
        await hand_over(Escalation.CUSTOMER_REQUEST, None)
        return result

    if _GREETING.match(text):
        await reply(f"Hi! I'm {profile.buddy_name}. What can I help you with today?", "smalltalk")
        return result
    if _THANKS.match(text):
        await reply("You're welcome! Anything else I can help with?", "smalltalk")
        return result
    if _BYE.match(text):
        await reply(f"Thanks for contacting {profile.business_name}. Have a great day!", "smalltalk")
        return result

    engine = get_intent_engine()
    intent = await asyncio.to_thread(engine.classify, text)
    customer_msg.intent, customer_msg.confidence = intent.intent, round(intent.confidence, 4)
    await customer_msg.asave(update_fields=["intent", "confidence"])
    result.messages[0] = customer_msg.as_dict()

    threshold = settings.AUBOT["CONFIDENCE_THRESHOLD"]
    if intent.intent != OUT_OF_SCOPE and intent.confidence >= threshold:
        spec = load_intents()[intent.intent]
        if spec.escalate:
            await hand_over(Escalation.CUSTOMER_REQUEST, intent.confidence)
            return result
        body = _render(spec.responses[0], profile)
        if sentiment.label == "negative" and intent.intent != "complaint":
            body = _EMPATHY.get(profile.buddy_tone, _EMPATHY["warm"]) + body
        await reply(body, "intent", intent=intent.intent, confidence=round(intent.confidence, 4))
        result.actions = list(spec.actions)
        return result

    # Low confidence: answer only from the knowledge base, otherwise escalate.
    hits = await faq_index.search(text)
    if hits:
        try:
            history = [m for m in (await transcript(session))[:-1] if m["role"] in (Message.CUSTOMER, Message.BOT)]
            answer = await llm.grounded_answer(
                question=text,
                faq=[{"question": h.question, "answer": h.answer} for h in hits],
                history=history,
                business=profile.business_name,
                assistant=profile.buddy_name,
                tone=profile.buddy_tone,
            )
            if answer.answerable:
                await reply(answer.answer, "faq_llm", confidence=round(intent.confidence, 4))
                result.actions = ["handoff"]  # let the customer reach a human if the answer wasn't enough
                return result
        except llm.LLMUnavailable as exc:
            log.info("Generative fallback unavailable (%s); escalating", exc)

    await hand_over(Escalation.LOW_CONFIDENCE, intent.confidence)
    return result
