"""UC01/UC03 decision policy."""
import pytest

from chat.engine import handle_customer_message, start_session
from chat.models import ChatSession, Escalation, Message
from core import llm

pytestmark = pytest.mark.django_db(transaction=True)


async def test_new_session_greets_with_ai_disclosure():
    session, token, messages = await start_session()
    assert session.check_token(token)
    assert "AI assistant" in messages[0]["text"]


async def test_confident_intent_gets_templated_answer():
    session, _, _ = await start_session()
    result = await handle_customer_message(session, "what are your opening hours")
    bot = result.messages[-1]
    assert bot["source"] == "intent" and bot["intent"] == "opening_hours"
    assert result.messages[0]["confidence"] >= 0.6
    assert result.session_status == ChatSession.ACTIVE


async def test_explicit_human_request_escalates_with_full_transcript():
    session, _, _ = await start_session()
    await handle_customer_message(session, "what are your opening hours")
    result = await handle_customer_message(session, "I want to talk to a real person")
    esc = await Escalation.objects.aget(session=session)
    assert esc.reason == Escalation.CUSTOMER_REQUEST
    assert result.escalation["reference"] == esc.reference
    texts = [m["text"] for m in esc.transcript]
    assert "what are your opening hours" in texts and texts[-1] == "I want to talk to a real person"


async def test_low_confidence_without_llm_escalates(faq):
    session, _, _ = await start_session()
    result = await handle_customer_message(session, "I spoke to Dave on Tuesday about it - what did he decide?")
    assert result.session_status == ChatSession.ESCALATED
    esc = await Escalation.objects.aget(session=session)
    assert esc.reason == Escalation.LOW_CONFIDENCE


async def test_low_confidence_answered_only_from_faq(faq, monkeypatch, settings):
    settings.AUBOT = {**settings.AUBOT, "OPENAI_API_KEY": "test"}
    seen = {}

    async def fake_answer(question, faq, **kwargs):
        seen["faq"] = faq
        return llm.GroundedAnswer(True, "Yes, emergency call-outs are available 24/7 for $180.")

    monkeypatch.setattr(llm, "grounded_answer", fake_answer)
    session, _, _ = await start_session()
    result = await handle_customer_message(session, "a pipe burst at 2am, can anyone come out overnight?")
    assert result.messages[-1]["source"] in {"faq_llm", "intent"}
    if result.messages[-1]["source"] == "faq_llm":
        assert any("emergency" in f["question"].lower() for f in seen["faq"])
    assert result.session_status == ChatSession.ACTIVE


async def test_llm_declines_then_escalates(faq, monkeypatch, settings):
    settings.AUBOT = {**settings.AUBOT, "OPENAI_API_KEY": "test"}

    async def decline(*args, **kwargs):
        return llm.GroundedAnswer(False, "")

    monkeypatch.setattr(llm, "grounded_answer", decline)
    session, _, _ = await start_session()
    result = await handle_customer_message(session, "does the emergency service guarantee cover my neighbour's tree?")
    assert result.session_status == ChatSession.ESCALATED


async def test_messages_relay_to_specialist_while_escalated():
    session, _, _ = await start_session()
    await handle_customer_message(session, "connect me with a human please")
    before = await Message.objects.filter(session=session, role=Message.BOT).acount()
    result = await handle_customer_message(session, "my address is 3 Smith St")
    assert len(result.messages) == 1  # no bot reply: a human owns the chat now
    assert await Message.objects.filter(session=session, role=Message.BOT).acount() == before


async def test_escalation_is_idempotent():
    session, _, _ = await start_session()
    await handle_customer_message(session, "talk to a person")
    session.status = ChatSession.ACTIVE  # simulate a race: second trigger while case open
    await handle_customer_message(session, "speak to someone now")
    assert await Escalation.objects.filter(session=session).acount() == 1


async def test_sentiment_logged_but_does_not_escalate():
    session, _, _ = await start_session()
    result = await handle_customer_message(session, "your opening hours are terrible and I'm furious, when are you open?")
    customer = result.messages[0]
    assert customer["sentiment_label"] == "negative"
    assert result.messages[-1]["source"] == "intent"


async def test_circuit_breaker_trips_on_quota_error(settings):
    settings.AUBOT = {**settings.AUBOT, "OPENAI_API_KEY": "test"}

    class QuotaError(Exception):
        status_code = 429

        def __str__(self):
            return "insufficient_quota"

    err = await llm._api_failed(QuotaError(), "test")
    assert isinstance(err, llm.LLMUnavailable)
    with pytest.raises(llm.LLMUnavailable, match="paused"):
        await llm.ensure_budget()
