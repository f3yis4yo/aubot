"""Customer-facing chat API (UC01, UC03 hand-off request)."""
import uuid

from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError
from pydantic import EmailStr, Field

from core.models import BusinessProfile
from core.security import client_ip, rate_limit

from . import events
from .engine import escalate, escalation_payload, handle_customer_message, start_session, transcript
from .models import ChatSession, Escalation, Message

router = Router(tags=["chat"])


class MessageIn(Schema):
    text: str = Field(min_length=1, max_length=2000)


class ContactIn(Schema):
    name: str = Field(default="", max_length=120)
    email: EmailStr | None = None
    phone: str = Field(default="", max_length=40)


class ConsentIn(Schema):
    voice: bool


async def get_session(request, session_id: uuid.UUID) -> ChatSession:
    """Customers authenticate per session with the token issued at creation (X-Session-Token)."""
    session = await ChatSession.objects.filter(id=session_id).afirst()
    if session is None or not session.check_token(request.headers.get("X-Session-Token")):
        raise HttpError(404, "Chat session not found.")
    return session


async def open_escalation(session: ChatSession) -> Escalation | None:
    return await Escalation.objects.filter(session=session).exclude(status=Escalation.RESOLVED).afirst()


async def session_state(session: ChatSession) -> dict:
    esc = await open_escalation(session)
    return {
        "session_id": str(session.id),
        "status": session.status,
        "escalation_reference": esc.reference if esc else None,
        "contact": {"name": session.customer_name, "email": session.customer_email, "phone": session.customer_phone},
        "voice_consent": session.voice_consent_at is not None,
        "messages": await transcript(session),
    }


@router.post("/sessions")
async def create_session(request):
    await rate_limit(f"new-session:{client_ip(request)}", limit=20)
    session, token, _ = await start_session()
    return {"token": token, **(await session_state(session))}


@router.get("/sessions/{session_id}")
async def get_session_state(request, session_id: uuid.UUID):
    return await session_state(await get_session(request, session_id))


@router.post("/sessions/{session_id}/messages")
async def send_message(request, session_id: uuid.UUID, payload: MessageIn):
    session = await get_session(request, session_id)
    if session.status == ChatSession.CLOSED:
        raise HttpError(409, "This chat has ended. Please start a new chat.")
    await rate_limit(f"msg:{session.id}")
    result = await handle_customer_message(session, payload.text)
    return {
        "messages": result.messages,
        "status": result.session_status,
        "escalation": result.escalation,
        "actions": result.actions,
    }


@router.post("/sessions/{session_id}/handoff")
async def request_handoff(request, session_id: uuid.UUID):
    """The always-visible "Talk to a human" button (UC03, customer request)."""
    session = await get_session(request, session_id)
    if session.status == ChatSession.CLOSED:
        raise HttpError(409, "This chat has ended. Please start a new chat.")
    esc, notice = await escalate(session, Escalation.CUSTOMER_REQUEST, "Customer pressed 'Talk to a human'")
    return {
        "messages": [notice.as_dict()] if notice else [],
        "status": session.status,
        "escalation": escalation_payload(esc, session),
    }


@router.post("/sessions/{session_id}/contact")
async def update_contact(request, session_id: uuid.UUID, payload: ContactIn):
    """Customer details forwarded to the specialist with the case (Assessment 1, UC03)."""
    session = await get_session(request, session_id)
    session.customer_name = payload.name.strip()
    session.customer_email = payload.email or ""
    session.customer_phone = payload.phone.strip()
    await session.asave(update_fields=["customer_name", "customer_email", "customer_phone", "updated_at"])
    msg = await Message.objects.acreate(
        session=session, role=Message.SYSTEM, source="system", text="Contact details shared with our team."
    )
    await events.to_staff("session.updated", {"session_id": str(session.id), "contact": payload.dict(), "message": msg.as_dict()})
    return {"ok": True, "message": msg.as_dict()}


@router.post("/sessions/{session_id}/consent")
async def voice_consent(request, session_id: uuid.UUID, payload: ConsentIn):
    """Explicit opt-in before the microphone is used (APP 3/5, Assessment 1)."""
    session = await get_session(request, session_id)
    session.voice_consent_at = timezone.now() if payload.voice else None
    await session.asave(update_fields=["voice_consent_at", "updated_at"])
    return {"voice_consent": payload.voice}


@router.post("/sessions/{session_id}/close")
async def close_session(request, session_id: uuid.UUID):
    session = await get_session(request, session_id)
    if session.status != ChatSession.CLOSED:
        session.status = ChatSession.CLOSED
        await session.asave(update_fields=["status", "updated_at"])
        msg = await Message.objects.acreate(session=session, role=Message.SYSTEM, source="system", text="The customer ended the chat.")
        await events.to_staff("message.new", {"session_id": str(session.id), "message": msg.as_dict()})
    return {"status": session.status}


public_router = Router(tags=["public"])


@public_router.get("/config")
async def public_config(request):
    from django.conf import settings

    from .engine import AI_DISCLOSURE

    profile = await BusinessProfile.aget_solo()
    return {
        "business_name": profile.business_name,
        "tagline": profile.tagline,
        "phone": profile.phone,
        "opening_hours": profile.opening_hours,
        "buddy_name": profile.buddy_name,
        "ai_disclosure": AI_DISCLOSURE,
        "max_upload_mb": settings.AUBOT["MAX_UPLOAD_BYTES"] // (1024 * 1024),
        "voice_available": bool(settings.AUBOT["OPENAI_API_KEY"]),
    }


@public_router.get("/health")
async def health(request):
    return {"status": "ok"}
