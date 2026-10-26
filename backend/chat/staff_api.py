"""Specialist console API: escalation queue, live replies, overview metrics."""
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from ninja import Router, Schema
from ninja.errors import HttpError
from pydantic import Field

from core import llm
from core.security import current_staff, display_name
from documents.models import Document

from . import events
from .models import ChatSession, Escalation, Message

router = Router(tags=["staff"])


class ReplyIn(Schema):
    text: str = Field(min_length=1, max_length=4000)


class ResolveIn(Schema):
    note: str = Field(default="", max_length=2000)


def _esc_row(esc: Escalation) -> dict:
    s = esc.session
    return {
        "id": esc.id,
        "reference": esc.reference,
        "reason": esc.reason,
        "reason_label": esc.get_reason_display(),
        "status": esc.status,
        "session_id": str(s.id),
        "session_status": s.status,
        "customer": {"name": s.customer_name, "email": s.customer_email, "phone": s.customer_phone},
        "trigger_text": esc.trigger_text,
        "trigger_confidence": esc.trigger_confidence,
        "assigned_to": display_name(esc.assigned_to) if esc.assigned_to else None,
        "created_at": esc.created_at.isoformat(),
        "accepted_at": esc.accepted_at.isoformat() if esc.accepted_at else None,
        "resolved_at": esc.resolved_at.isoformat() if esc.resolved_at else None,
        "resolution_note": esc.resolution_note,
    }


async def _get_escalation(esc_id: int) -> Escalation:
    esc = await Escalation.objects.select_related("session", "assigned_to").filter(id=esc_id).afirst()
    if esc is None:
        raise HttpError(404, "Case not found.")
    return esc


async def _system_message(session: ChatSession, text: str) -> dict:
    msg = await Message.objects.acreate(session=session, role=Message.SYSTEM, source="system", text=text)
    data = msg.as_dict()
    await events.to_customer(session.id, "message.new", data)
    return data


@router.get("/me")
async def me(request):
    user = await current_staff(request)
    return {"username": user.username, "name": display_name(user), "is_owner": user.aubot_is_owner}


@router.get("/escalations")
async def list_escalations(request, status: str = "open"):
    await current_staff(request)
    qs = Escalation.objects.select_related("session", "assigned_to")
    if status == "open":
        qs = qs.exclude(status=Escalation.RESOLVED).order_by("created_at")  # oldest waiting first
    elif status in {Escalation.QUEUED, Escalation.ACTIVE, Escalation.RESOLVED}:
        qs = qs.filter(status=status)
    rows = [_esc_row(e) async for e in qs[:200]]
    return {"items": rows}


@router.get("/escalations/{esc_id}")
async def escalation_detail(request, esc_id: int):
    await current_staff(request)
    esc = await _get_escalation(esc_id)
    live = [m.as_dict() async for m in esc.session.messages.all()]
    docs = [
        {"id": str(d.id), "reference": d.reference, "name": d.original_name, "department": d.department, "status": d.status}
        async for d in Document.objects.filter(session=esc.session)
    ]
    return {**_esc_row(esc), "transcript": esc.transcript, "messages": live, "documents": docs}


@router.post("/escalations/{esc_id}/accept")
async def accept(request, esc_id: int):
    user = await current_staff(request)
    esc = await _get_escalation(esc_id)
    if esc.status == Escalation.RESOLVED:
        raise HttpError(409, "This case is already resolved.")
    if esc.status == Escalation.QUEUED:
        esc.status, esc.assigned_to, esc.accepted_at = Escalation.ACTIVE, user, timezone.now()
        await esc.asave(update_fields=["status", "assigned_to", "accepted_at"])
        if esc.session.status != ChatSession.CLOSED:
            await _system_message(esc.session, f"{user.first_name or display_name(user)} from our team has joined the chat.")
        await events.to_staff("escalation.updated", _esc_row(esc))
    return _esc_row(esc)


@router.post("/escalations/{esc_id}/reply")
async def reply(request, esc_id: int, payload: ReplyIn):
    user = await current_staff(request)
    esc = await _get_escalation(esc_id)
    if esc.status == Escalation.RESOLVED:
        raise HttpError(409, "This case is already resolved.")
    if esc.status == Escalation.QUEUED:
        esc.status, esc.assigned_to, esc.accepted_at = Escalation.ACTIVE, user, timezone.now()
        await esc.asave(update_fields=["status", "assigned_to", "accepted_at"])
        await events.to_staff("escalation.updated", _esc_row(esc))
    msg = await Message.objects.acreate(
        session=esc.session,
        role=Message.SPECIALIST,
        source="specialist",
        text=payload.text.strip(),
        author=user,
        author_name=user.first_name or display_name(user),
    )
    data = msg.as_dict()
    await events.to_customer(esc.session_id, "message.new", data)
    await events.to_staff("message.new", {"session_id": str(esc.session_id), "escalation_id": esc.id, "message": data})
    return data


@router.post("/escalations/{esc_id}/resolve")
async def resolve(request, esc_id: int, payload: ResolveIn):
    user = await current_staff(request)
    esc = await _get_escalation(esc_id)
    if esc.status != Escalation.RESOLVED:
        esc.status, esc.resolved_at, esc.resolution_note = Escalation.RESOLVED, timezone.now(), payload.note.strip()
        if esc.assigned_to_id is None:
            esc.assigned_to = user
        await esc.asave(update_fields=["status", "resolved_at", "resolution_note", "assigned_to"])
        session = esc.session
        if session.status == ChatSession.ESCALATED:
            session.status = ChatSession.ACTIVE  # the assistant takes over again
            await session.asave(update_fields=["status", "updated_at"])
            await _system_message(session, "Our specialist has marked this case as resolved. I'm here if you need anything else.")
            await events.to_customer(session.id, "session.status", {"status": session.status, "escalation": None})
        await events.to_staff("escalation.updated", _esc_row(esc))
    return _esc_row(esc)


@router.get("/overview")
async def overview(request):
    """Owner dashboard: simple usage summary (Assessment 1 stakeholder matrix)."""
    await current_staff(request)
    now = timezone.now()
    week = now - timedelta(days=7)
    sessions = ChatSession.objects.filter(created_at__gte=week)
    total = await sessions.acount()
    escalated = await sessions.filter(escalations__isnull=False).distinct().acount()
    bot_msgs = Message.objects.filter(created_at__gte=week, role=Message.BOT)
    by_source = {r["source"]: r["n"] async for r in bot_msgs.values("source").annotate(n=Count("id"))}
    intents = [
        {"intent": r["intent"], "count": r["n"]}
        async for r in Message.objects.filter(created_at__gte=week, role=Message.CUSTOMER)
        .exclude(intent="")
        .values("intent")
        .annotate(n=Count("id"))
        .order_by("-n")[:10]
    ]
    sentiment = {
        r["sentiment_label"]: r["n"]
        async for r in Message.objects.filter(created_at__gte=week, role=Message.CUSTOMER)
        .exclude(sentiment_label="")
        .values("sentiment_label")
        .annotate(n=Count("id"))
    }
    # Sessions per day, split by whether they needed a human.
    daily = []
    for offset in range(6, -1, -1):
        day_start = (now - timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        day = sessions.filter(created_at__gte=day_start, created_at__lt=day_start + timedelta(days=1))
        n = await day.acount()
        esc_n = await day.filter(escalations__isnull=False).distinct().acount()
        daily.append({"date": day_start.date().isoformat(), "automated": n - esc_n, "escalated": esc_n})
    open_cases = await Escalation.objects.exclude(status=Escalation.RESOLVED).aaggregate(
        queued=Count("id", filter=Q(status=Escalation.QUEUED)), active=Count("id", filter=Q(status=Escalation.ACTIVE))
    )
    return {
        "window_days": 7,
        "sessions": total,
        "escalated_sessions": escalated,
        "automation_rate": round((total - escalated) / total, 4) if total else None,
        "bot_replies_by_source": by_source,
        "top_intents": intents,
        "sentiment": sentiment,
        "daily": daily,
        "open_cases": open_cases,
        "documents_pending": await Document.objects.exclude(status=Document.PROCESSED).acount(),
        "documents_7d": await Document.objects.filter(created_at__gte=week).acount(),
        "usage": await llm.usage_summary(),
    }
