"""AUBOT Buddy voice endpoint: speech -> UC01/UC03 engine -> speech.

Buddy is a voice layer over the same engine as text chat, so it obeys exactly
the same intent, FAQ-grounding and escalation rules (Assessment 1: "GPT-4 stays
under the core intent and escalation rules").

Privacy: requires recorded consent; the audio is held in memory only for the
transcription call and is never written to disk or the database.
"""
import base64
import time
import uuid

from django.conf import settings
from django.http import JsonResponse
from ninja import Router

from chat.api import get_session
from chat.engine import handle_customer_message
from chat.models import ChatSession, Message
from core import llm
from core.models import BusinessProfile
from core.security import rate_limit

router = Router(tags=["buddy"])


def _error(code: str, detail: str, status: int) -> JsonResponse:
    return JsonResponse({"ok": False, "code": code, "detail": detail}, status=status)


@router.post("/sessions/{session_id}/voice")
async def voice_turn(request, session_id: uuid.UUID):
    """Multipart field `audio` (webm/ogg/mp3/wav/m4a, <= 3 MB)."""
    t0 = time.perf_counter()
    session = await get_session(request, session_id)
    if session.status == ChatSession.CLOSED:
        return _error("closed", "This chat has ended. Please start a new chat.", 409)
    if session.voice_consent_at is None:
        return _error("consent_required", "Please allow voice first.", 403)
    await rate_limit(f"voice:{session.id}", limit=12)
    if int(request.META.get("CONTENT_LENGTH") or 0) > settings.AUBOT["MAX_AUDIO_BYTES"] + 64 * 1024:
        return _error("too_long", "That recording is too long. Please keep voice messages under a minute.", 413)

    upload = request.FILES.get("audio")
    if upload is None or upload.size == 0:
        return _error("missing_audio", "No audio was received.", 400)
    audio = upload.read()
    filename = upload.name or "voice.webm"

    try:
        text = await llm.transcribe(audio, filename)
    except llm.LLMUnavailable:
        return _error("voice_unavailable", "Voice isn't available right now. Please type your message instead.", 503)
    finally:
        del audio  # drop our reference immediately; nothing is persisted
        upload.close()
    t_stt = time.perf_counter()

    if not text:
        return _error("no_speech", "Sorry, I didn't catch that. Could you try again?", 422)

    result = await handle_customer_message(session, text, channel="voice")
    t_chat = time.perf_counter()

    # Speak the assistant's newest reply (bot answer or escalation notice). While a
    # specialist is handling the chat there is no automated reply to speak.
    spoken = next((m for m in reversed(result.messages) if m["role"] in (Message.BOT, Message.SYSTEM)), None)
    audio_b64 = None
    if spoken:
        profile = await BusinessProfile.aget_solo()
        try:
            mp3 = await llm.speak(spoken["text"], profile.buddy_voice, profile.buddy_tone)
            audio_b64 = base64.b64encode(mp3).decode()
        except llm.LLMUnavailable:
            pass  # degrade to text-only; the reply is still shown on screen
    t_tts = time.perf_counter()

    return {
        "ok": True,
        "transcript": text,
        "messages": result.messages,
        "status": result.session_status,
        "escalation": result.escalation,
        "actions": result.actions,
        "audio_base64": audio_b64,
        "audio_mime": "audio/mpeg",
        "timings_ms": {
            "speech_to_text": int((t_stt - t0) * 1000),
            "assistant": int((t_chat - t_stt) * 1000),
            "text_to_speech": int((t_tts - t_chat) * 1000),
            "total": int((t_tts - t0) * 1000),
        },
    }
