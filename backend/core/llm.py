"""OpenAI adapter: grounded answers (UC01), speech-to-text and text-to-speech (Buddy).

All vendor-specific code lives here, so replacing OpenAI with another provider
or a self-hosted model touches only this module (Assessment 2, Section 8.2).
Every call is metered into ApiUsage and checked against the monthly budget cap.
"""
import json
import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone

from .models import ApiUsage

log = logging.getLogger(__name__)

# USD list prices used to estimate spend for the budget cap. Unknown models use
# the most expensive row so the cap errs on the safe side.
PRICING = {
    "gpt-4.1-mini": {"in": 0.40, "out": 1.60},  # per 1M tokens
    "gpt-4.1-nano": {"in": 0.10, "out": 0.40},
    "gpt-4o-mini": {"in": 0.15, "out": 0.60},
    "gpt-5-mini": {"in": 0.25, "out": 2.00},
    "gpt-5-nano": {"in": 0.05, "out": 0.40},
    "_default": {"in": 2.50, "out": 10.00},
    "whisper-1": {"per_minute": 0.006},
    "gpt-4o-mini-transcribe": {"per_minute": 0.003},
    "gpt-4o-transcribe": {"per_minute": 0.006},
    "gpt-4o-mini-tts": {"per_1k_chars": 0.015},
    "tts-1": {"per_1k_chars": 0.015},
}

BUDGET_CACHE_KEY = "aubot:spend:month"
BREAKER_KEY = "aubot:llm:down"
BREAKER_SECONDS = 300


class LLMUnavailable(Exception):
    """Raised when there is no API key, the budget is spent, or the API failed."""


@dataclass
class GroundedAnswer:
    answerable: bool
    answer: str


def _client():
    from openai import AsyncOpenAI

    key = settings.AUBOT["OPENAI_API_KEY"]
    if not key:
        raise LLMUnavailable("OPENAI_API_KEY is not set")
    return AsyncOpenAI(api_key=key, timeout=settings.AUBOT["OPENAI_TIMEOUT_SECONDS"], max_retries=1)


async def month_spend_usd() -> float:
    cached = await cache.aget(BUDGET_CACHE_KEY)
    if cached is not None:
        return float(cached)
    start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = await ApiUsage.objects.filter(created_at__gte=start).aaggregate(total=Sum("cost_usd"))
    value = float(total["total"] or 0)
    await cache.aset(BUDGET_CACHE_KEY, value, 60)
    return value


async def ensure_budget():
    if not settings.AUBOT["OPENAI_API_KEY"]:
        raise LLMUnavailable("OPENAI_API_KEY is not set")
    reason = await cache.aget(BREAKER_KEY)
    if reason:
        raise LLMUnavailable(f"AI provider paused: {reason}")
    if await month_spend_usd() >= settings.AUBOT["MONTHLY_BUDGET_USD"]:
        raise LLMUnavailable("Monthly AI budget reached")


async def _api_failed(exc: Exception, what: str) -> LLMUnavailable:
    """Log the failure; trip the circuit breaker for errors retrying cannot fix (bad key,
    no credit) so customers aren't each made to wait for a doomed call."""
    log.warning("%s failed: %s", what, exc)
    status = getattr(exc, "status_code", None)
    body = str(exc)
    if status == 401 or (status == 429 and "insufficient_quota" in body):
        reason = "invalid API key" if status == 401 else "no API credit remaining"
        await cache.aset(BREAKER_KEY, reason, BREAKER_SECONDS)
        log.error("OpenAI disabled for %s s: %s", BREAKER_SECONDS, reason)
    return LLMUnavailable(body)


async def _record(service: str, model: str, cost: float, started: float, **fields):
    await ApiUsage.objects.acreate(
        service=service,
        model=model,
        cost_usd=Decimal(str(round(cost, 6))),
        latency_ms=int((time.perf_counter() - started) * 1000),
        **fields,
    )
    await cache.adelete(BUDGET_CACHE_KEY)


TONE_GUIDE = {
    "warm": "warm, friendly and reassuring",
    "professional": "concise, polite and professional",
    "upbeat": "cheerful and positive",
}

GROUNDED_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "grounded_answer",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "answerable": {"type": "boolean"},
                "answer": {"type": "string"},
            },
            "required": ["answerable", "answer"],
            "additionalProperties": False,
        },
    },
}


async def grounded_answer(
    question: str, faq: list[dict], history: list[dict], business: str, assistant: str, tone: str
) -> GroundedAnswer:
    """Answer strictly from the supplied FAQ entries, or report that it cannot."""
    await ensure_budget()
    model = settings.AUBOT["OPENAI_MODEL"]
    knowledge = "\n\n".join(f"Q: {f['question']}\nA: {f['answer']}" for f in faq)
    system = (
        f"You are {assistant}, the AI customer-service assistant for {business}, an Australian small business. "
        "Answer the customer's latest message using ONLY the FAQ excerpts below. "
        "If the excerpts do not clearly answer it, or the request needs account-specific details, a judgement call, "
        "legal/insurance advice or anything not stated, set answerable=false and answer=''. "
        "Never invent prices, policies, times or promises. "
        f"When answerable, reply in Australian English, {TONE_GUIDE.get(tone, TONE_GUIDE['warm'])}, in at most 80 words, "
        "without mentioning the FAQ itself.\n\nFAQ excerpts:\n" + knowledge
    )
    messages = [{"role": "system", "content": system}]
    for turn in history[-6:]:
        messages.append({"role": "user" if turn["role"] == "customer" else "assistant", "content": turn["text"]})
    messages.append({"role": "user", "content": question})

    started = time.perf_counter()
    try:
        resp = await _client().chat.completions.create(
            model=model, messages=messages, response_format=GROUNDED_SCHEMA, temperature=0.2, max_tokens=300
        )
    except Exception as exc:  # network/API errors must never break the chat: caller escalates
        raise await _api_failed(exc, "LLM call") from exc

    usage = resp.usage
    price = PRICING.get(model, PRICING["_default"])
    cost = (usage.prompt_tokens * price["in"] + usage.completion_tokens * price["out"]) / 1_000_000
    await _record("chat", model, cost, started, input_tokens=usage.prompt_tokens, output_tokens=usage.completion_tokens)
    try:
        data = json.loads(resp.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        return GroundedAnswer(False, "")
    answer = (data.get("answer") or "").strip()
    return GroundedAnswer(bool(data.get("answerable")) and bool(answer), answer)


async def transcribe(audio: bytes, filename: str, duration_hint_s: float | None = None) -> str:
    """Speech-to-text. The audio bytes live only in memory for the duration of this call."""
    await ensure_budget()
    model = settings.AUBOT["OPENAI_TRANSCRIBE_MODEL"]
    started = time.perf_counter()
    try:
        resp = await _client().audio.transcriptions.create(model=model, file=(filename, audio), language="en")
    except Exception as exc:
        raise await _api_failed(exc, "Transcription") from exc
    # Opus voice notes are ~4 KB/s; used only when the API does not return a duration.
    seconds = duration_hint_s or max(1.0, len(audio) / 4000)
    price = PRICING.get(model, {"per_minute": 0.006})["per_minute"]
    await _record("transcribe", model, seconds / 60 * price, started, audio_seconds=seconds)
    return (resp.text or "").strip()


async def speak(text: str, voice: str, tone: str) -> bytes:
    """Text-to-speech, returned as MP3 bytes (never stored)."""
    await ensure_budget()
    model = settings.AUBOT["OPENAI_TTS_MODEL"]
    started = time.perf_counter()
    kwargs = {"model": model, "voice": voice, "input": text, "response_format": "mp3"}
    if "tts-1" not in model:
        kwargs["instructions"] = f"Speak in a {TONE_GUIDE.get(tone, TONE_GUIDE['warm'])} Australian customer-service voice."
    try:
        resp = await _client().audio.speech.create(**kwargs)
        audio = resp.content
    except Exception as exc:
        raise await _api_failed(exc, "TTS") from exc
    price = PRICING.get(model, {"per_1k_chars": 0.015})["per_1k_chars"]
    await _record("tts", model, len(text) / 1000 * price, started, characters=len(text))
    return audio


async def usage_summary(days: int = 30) -> dict:
    since = timezone.now() - timedelta(days=days)
    rows = ApiUsage.objects.filter(created_at__gte=since).values("service").annotate(cost=Sum("cost_usd"))
    by_service = {r["service"]: float(r["cost"] or 0) async for r in rows}
    return {
        "month_spend_usd": round(await month_spend_usd(), 4),
        "monthly_budget_usd": settings.AUBOT["MONTHLY_BUDGET_USD"],
        "last_30_days_by_service": by_service,
        "llm_configured": bool(settings.AUBOT["OPENAI_API_KEY"]),
        "llm_paused_reason": await cache.aget(BREAKER_KEY),
    }

