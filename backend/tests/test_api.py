"""HTTP-level tests for customer, staff, document and voice endpoints."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import AsyncClient, Client

from chat.models import ChatSession, Escalation
from core import llm
from evaluation.fixtures import make_docx, make_pdf

pytestmark = pytest.mark.django_db(transaction=True)


async def new_chat(client: AsyncClient):
    resp = await client.post("/api/chat/sessions")
    assert resp.status_code == 200
    data = resp.json()
    return data["session_id"], {"X-Session-Token": data["token"]}


async def test_chat_flow_and_token_required():
    client = AsyncClient()
    sid, headers = await new_chat(client)
    resp = await client.post(f"/api/chat/sessions/{sid}/messages", {"text": "how much is your call out fee"}, content_type="application/json", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["messages"][-1]["intent"] == "pricing_quote"
    bad = await client.get(f"/api/chat/sessions/{sid}", headers={"X-Session-Token": "wrong"})
    assert bad.status_code == 404


async def test_handoff_contact_and_close():
    client = AsyncClient()
    sid, headers = await new_chat(client)
    resp = await client.post(f"/api/chat/sessions/{sid}/handoff", headers=headers)
    assert resp.json()["status"] == "escalated"
    resp = await client.post(
        f"/api/chat/sessions/{sid}/contact", {"name": "Jo", "email": "jo@example.com", "phone": "0400"}, content_type="application/json", headers=headers
    )
    assert resp.status_code == 200
    session = await ChatSession.objects.aget(id=sid)
    assert session.customer_email == "jo@example.com"
    assert (await client.post(f"/api/chat/sessions/{sid}/close", headers=headers)).json()["status"] == "closed"
    resp = await client.post(f"/api/chat/sessions/{sid}/messages", {"text": "hello"}, content_type="application/json", headers=headers)
    assert resp.status_code == 409


async def test_document_upload_valid_and_invalid():
    client = AsyncClient()
    sid, headers = await new_chat(client)
    url = f"/api/chat/sessions/{sid}/documents"
    pdf = SimpleUploadedFile("claim.pdf", make_pdf("Insurance claim, policy number 123, insurer Coastal"), "application/pdf")
    resp = await client.post(url, {"file": pdf}, headers=headers)
    body = resp.json()
    assert resp.status_code == 200 and body["document"]["department"] == "Claims & Insurance"
    assert body["document"]["reference"] in body["message"]["text"]

    docx = SimpleUploadedFile("quote.docx", make_docx(["I accept the quote and have signed it."]))
    assert (await client.post(url, {"file": docx}, headers=headers)).status_code == 200

    for name, data, code in [("a.txt", b"hi", "unsupported_type"), ("b.pdf", b"", "empty"), ("c.pdf", b"MZ" + b"0" * 100, "corrupted")]:
        resp = await client.post(url, {"file": SimpleUploadedFile(name, data)}, headers=headers)
        assert resp.status_code == 400 and resp.json()["code"] == code, name


async def test_oversized_document_rejected_quickly():
    client = AsyncClient()
    sid, headers = await new_chat(client)
    big = SimpleUploadedFile("big.pdf", make_pdf("x", pad_bytes=8 * 1024 * 1024))
    resp = await client.post(f"/api/chat/sessions/{sid}/documents", {"file": big}, headers=headers)
    assert resp.status_code == 413 and resp.json()["code"] == "too_large"


async def test_voice_requires_consent_then_works(monkeypatch, settings):
    settings.AUBOT = {**settings.AUBOT, "OPENAI_API_KEY": "test"}

    async def fake_transcribe(audio, filename, duration_hint_s=None):
        return "what are your opening hours"

    async def fake_speak(text, voice, tone):
        return b"ID3fake-mp3"

    monkeypatch.setattr(llm, "transcribe", fake_transcribe)
    monkeypatch.setattr(llm, "speak", fake_speak)
    client = AsyncClient()
    sid, headers = await new_chat(client)
    url = f"/api/chat/sessions/{sid}/voice"
    audio = SimpleUploadedFile("v.webm", b"\x1aE\xdf\xa3" + b"0" * 2000, "audio/webm")
    assert (await client.post(url, {"audio": audio}, headers=headers)).status_code == 403
    await client.post(f"/api/chat/sessions/{sid}/consent", {"voice": True}, content_type="application/json", headers=headers)
    audio.seek(0)
    resp = await client.post(url, {"audio": audio}, headers=headers)
    body = resp.json()
    assert resp.status_code == 200, body
    assert body["transcript"] == "what are your opening hours"
    assert body["messages"][0]["channel"] == "voice"
    assert body["audio_base64"] and set(body["timings_ms"]) == {"speech_to_text", "assistant", "text_to_speech", "total"}


def test_staff_endpoints_require_login_and_csrf(specialist):
    client = Client(enforce_csrf_checks=True)
    assert client.get("/api/staff/escalations").status_code == 401
    client.get("/api/auth/csrf")
    token = client.cookies["csrftoken"].value
    assert client.post("/api/auth/login", {"username": "spec", "password": "correct-horse-1"}, content_type="application/json").status_code == 403
    resp = client.post(
        "/api/auth/login", {"username": "spec", "password": "correct-horse-1"}, content_type="application/json", headers={"X-CSRFToken": token}
    )
    assert resp.status_code == 200 and resp.json()["is_owner"] is False
    assert client.get("/api/staff/escalations").status_code == 200


def test_specialist_accept_reply_resolve(specialist):
    customer = Client()
    data = customer.post("/api/chat/sessions").json()
    sid, headers = data["session_id"], {"X-Session-Token": data["token"]}
    customer.post(f"/api/chat/sessions/{sid}/handoff", headers=headers)
    esc = Escalation.objects.get(session_id=sid)

    staff = Client()
    staff.force_login(specialist)
    detail = staff.get(f"/api/staff/escalations/{esc.id}").json()
    assert detail["transcript"] and detail["reference"] == esc.reference
    assert staff.post(f"/api/staff/escalations/{esc.id}/accept").json()["status"] == "active"
    staff.post(f"/api/staff/escalations/{esc.id}/reply", {"text": "Hi, Alex here"}, content_type="application/json")
    msgs = customer.get(f"/api/chat/sessions/{sid}", headers=headers).json()["messages"]
    assert any(m["role"] == "specialist" and m["text"] == "Hi, Alex here" for m in msgs)
    assert staff.post(f"/api/staff/escalations/{esc.id}/resolve", {"note": "done"}, content_type="application/json").json()["status"] == "resolved"
    assert ChatSession.objects.get(id=sid).status == ChatSession.ACTIVE
    assert staff.get("/api/staff/overview").status_code == 200


def test_only_owner_can_change_settings(specialist, owner):
    staff = Client()
    staff.force_login(specialist)
    current = staff.get("/api/staff/settings").json()
    payload = {k: current[k] for k in ["business_name", "tagline", "phone", "email", "address", "opening_hours", "buddy_name", "buddy_greeting", "buddy_tone", "buddy_voice"]}
    payload["buddy_name"] = "Matilda"
    assert staff.put("/api/staff/settings", payload, content_type="application/json").status_code == 403
    boss = Client()
    boss.force_login(owner)
    assert boss.put("/api/staff/settings", payload, content_type="application/json").json()["buddy_name"] == "Matilda"
