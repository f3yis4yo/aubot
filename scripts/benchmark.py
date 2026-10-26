"""End-to-end benchmarks against a running AUBOT server (Assessment 2, Section 7.3-7.4).

  python scripts/benchmark.py [--base http://localhost:8000] [--concurrency 10]
                              [--staff-user specialist --staff-password ...] [--voice]

Measures:
  * Concurrency: N simultaneous chat requests, each must finish within 3,000 ms.
  * TC02 via HTTP: upload acknowledgement <= 10 s, rejection <= 5 s.
  * Live hand-off: specialist reply reaches the customer's WebSocket (needs staff login).
  * TC05 (--voice): voice question -> spoken answer <= 5 s. Uses OpenAI TTS to synthesise
    the three standard scenarios, so it needs API credit.

Run from the repo root with the backend virtualenv: backend/.venv/bin/python scripts/benchmark.py
"""
import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from evaluation.fixtures import tc02_cases  # noqa: E402  (pure functions, no Django setup needed)

QUERIES = [
    "What are your opening hours?",
    "How much is a call-out?",
    "Do you install EV chargers?",
    "I need to reschedule my booking",
    "Can I pay by bank transfer?",
    "Do you service Parramatta?",
    "Are your plumbers licensed?",
    "I want to book an electrician",
    "How do I upload my insurance form?",
    "Do you do hot water systems?",
]
VOICE_SCENARIOS = {
    "general enquiry": "Hi, what time are you open on Saturday?",
    "document support": "How do I send you my insurance claim form?",
    "complaint": "Your plumber left a mess and the leak is back. I'm really not happy.",
}

results: dict[str, dict] = {}


def report(name: str, passed: bool, **data):
    results[name] = {"passed": passed, **data}
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {name}: " + ", ".join(f"{k}={v}" for k, v in data.items()))


async def new_session(client: httpx.AsyncClient) -> tuple[str, dict]:
    r = await client.post("/api/chat/sessions")
    r.raise_for_status()
    body = r.json()
    return body["session_id"], {"X-Session-Token": body["token"]}


async def concurrency_test(client: httpx.AsyncClient, n: int):
    sessions = [await new_session(client) for _ in range(n)]

    async def one(i: int) -> float:
        sid, headers = sessions[i]
        t = time.perf_counter()
        r = await client.post(f"/api/chat/sessions/{sid}/messages", json={"text": QUERIES[i % len(QUERIES)]}, headers=headers)
        r.raise_for_status()
        return (time.perf_counter() - t) * 1000

    t0 = time.perf_counter()
    times = await asyncio.gather(*(one(i) for i in range(n)))
    wall = (time.perf_counter() - t0) * 1000
    times.sort()
    p95 = times[max(0, int(round(0.95 * len(times))) - 1)]
    report(
        f"{n} concurrent chat requests",
        max(times) <= 3000,
        p50_ms=round(statistics.median(times)),
        p95_ms=round(p95),
        max_ms=round(max(times)),
        wall_ms=round(wall),
        limit_ms=3000,
    )


async def tc02_http(client: httpx.AsyncClient):
    sid, headers = await new_session(client)
    ok = True
    for case in tc02_cases():
        t = time.perf_counter()
        r = await client.post(f"/api/chat/sessions/{sid}/documents", files={"file": (case["name"], case["data"])}, headers=headers)
        ms = (time.perf_counter() - t) * 1000
        body = r.json()
        outcome = "accepted" if r.status_code == 200 else body.get("code")
        limit = 10_000 if case["expect"] == "accepted" else 5_000
        passed = outcome == case["expect"] and ms <= limit
        ok &= passed
        print(f"    {'ok ' if passed else 'BAD'} {case['label']:32} -> {outcome:16} {ms:7.0f} ms (limit {limit})")
    report("TC02 document upload via HTTP", ok)


async def live_handoff(client: httpx.AsyncClient, base: str, user: str, password: str):
    import websockets

    sid, headers = await new_session(client)
    ws_url = base.replace("http", "ws", 1) + f"/ws/chat/{sid}/?token={headers['X-Session-Token']}"
    async with websockets.connect(ws_url, origin=base) as ws:
        r = await client.post(f"/api/chat/sessions/{sid}/messages", json={"text": "I'd like to speak to a real person"}, headers=headers)
        esc = r.json()["escalation"]
        staff = httpx.AsyncClient(base_url=base, timeout=15)
        await staff.get("/api/auth/csrf")
        csrf = {"X-CSRFToken": staff.cookies.get("csrftoken")}
        login = await staff.post("/api/auth/login", json={"username": user, "password": password}, headers=csrf)
        if login.status_code != 200:
            return report("Live specialist hand-off", False, error=login.text[:120])
        csrf = {"X-CSRFToken": staff.cookies.get("csrftoken")}
        detail = (await staff.get(f"/api/staff/escalations/{esc['id']}")).json()
        t = time.perf_counter()
        await staff.post(f"/api/staff/escalations/{esc['id']}/reply", json={"text": "Hi, this is the team - how can I help?"}, headers=csrf)
        got = None
        while time.perf_counter() - t < 5:
            frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if frame["event"] == "message.new" and frame["payload"]["role"] == "specialist":
                got = (time.perf_counter() - t) * 1000
                break
        await staff.post(f"/api/staff/escalations/{esc['id']}/resolve", json={"note": "benchmark"}, headers=csrf)
        await staff.aclose()
        report(
            "Live specialist hand-off",
            got is not None and len(detail["transcript"]) >= 2,
            transcript_turns=len(detail["transcript"]),
            reply_to_customer_ms=round(got) if got else None,
        )


async def voice_test(client: httpx.AsyncClient):
    """TC05. Synthesises each question with OpenAI TTS, then times the full voice round trip."""
    import os

    from dotenv import load_dotenv
    from openai import AsyncOpenAI

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    oa = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    sid, headers = await new_session(client)
    await client.post(f"/api/chat/sessions/{sid}/consent", json={"voice": True}, headers=headers)
    all_ok = True
    for name, question in VOICE_SCENARIOS.items():
        speech = await oa.audio.speech.create(model="gpt-4o-mini-tts", voice="alloy", input=question, response_format="mp3")
        t = time.perf_counter()
        r = await client.post(f"/api/chat/sessions/{sid}/voice", files={"audio": ("q.mp3", speech.content, "audio/mpeg")}, headers=headers)
        ms = (time.perf_counter() - t) * 1000
        body = r.json()
        ok = r.status_code == 200 and bool(body.get("audio_base64")) and ms <= 5000
        all_ok &= ok
        print(f"    {'ok ' if ok else 'BAD'} {name:18} {ms:6.0f} ms  heard={body.get('transcript')!r}  stages={body.get('timings_ms')}")
        if r.status_code == 200 and body.get("escalation"):
            sid, headers = await new_session(client)  # complaint may escalate; continue in a fresh chat
            await client.post(f"/api/chat/sessions/{sid}/consent", json={"voice": True}, headers=headers)
    report("TC05 end-to-end voice latency", all_ok, limit_ms=5000)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--concurrency", type=int, default=10)
    ap.add_argument("--staff-user")
    ap.add_argument("--staff-password")
    ap.add_argument("--voice", action="store_true")
    ap.add_argument("--json", help="write results to this file")
    args = ap.parse_args()

    async with httpx.AsyncClient(base_url=args.base, timeout=30) as client:
        (await client.get("/api/health")).raise_for_status()
        await concurrency_test(client, args.concurrency)
        await tc02_http(client)
        if args.staff_user and args.staff_password:
            await live_handoff(client, args.base, args.staff_user, args.staff_password)
        if args.voice:
            await voice_test(client)

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2))
    sys.exit(0 if all(r["passed"] for r in results.values()) else 1)


if __name__ == "__main__":
    asyncio.run(main())
