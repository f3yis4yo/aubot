"""Benchmark suites from Assessment 2, Section 7.3 (Table 8).

  TC01 intent accuracy   = correct / total on 100 held-out queries        pass >= 85%
  TC02 document handling = cases with expected outcome within time limit  pass = 100%
  TC03 escalation        = low-confidence inputs escalated or answered     pass = 100%
                           strictly from the FAQ / all low-confidence inputs
  TC04 sentiment         = correct / total on 50 labelled utterances      pass >= 80%

Results are stored as EvaluationRun rows (evidence for Assessment 3).
TC05 (voice latency) and the 10-concurrent-request test need a running server
and are measured by scripts/benchmark.py.
"""
import asyncio
import csv
import time
from collections import Counter, defaultdict
from pathlib import Path

from django.conf import settings

from buddy.sentiment import analyse
from chat import events
from chat.engine import handle_customer_message, start_session
from chat.models import ChatSession, Escalation
from chat.nlu.base import OUT_OF_SCOPE, get_intent_engine
from documents.processing import DocumentRejected, process

from .fixtures import tc02_cases
from .models import EvaluationRun

THRESHOLDS = {"tc01": 0.85, "tc02": 1.0, "tc03": 1.0, "tc04": 0.80}
ACK_LIMIT_MS, ERROR_LIMIT_MS = 10_000, 5_000


def _rows(name: str) -> list[dict]:
    path: Path = settings.AUBOT["DATA_DIR"] / "eval" / name
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


async def run_tc01() -> dict:
    engine = get_intent_engine()
    threshold = settings.AUBOT["CONFIDENCE_THRESHOLD"]
    cases, by_cat = [], defaultdict(lambda: [0, 0])
    for row in _rows("tc01_intents.csv"):
        res = await asyncio.to_thread(engine.classify, row["query"])
        correct = res.intent == row["expected_intent"]
        confident = res.confidence >= threshold and res.intent != OUT_OF_SCOPE
        by_cat[row["category"]][0] += correct
        by_cat[row["category"]][1] += 1
        cases.append(
            {
                "query": row["query"],
                "expected": row["expected_intent"],
                "predicted": res.intent,
                "confidence": round(res.confidence, 3),
                "category": row["category"],
                "correct": correct,
                "answered_directly": correct and confident,
            }
        )
    n = len(cases)
    correct = sum(c["correct"] for c in cases)
    return {
        "score": correct / n,
        "summary": {
            "engine": engine.name,
            "total": n,
            "correct": correct,
            "accuracy": round(correct / n, 4),
            "correct_and_above_threshold": sum(c["answered_directly"] for c in cases),
            "confidence_threshold": threshold,
            "accuracy_by_category": {k: round(v[0] / v[1], 3) for k, v in sorted(by_cat.items())},
        },
        "cases": cases,
    }


async def run_tc02() -> dict:
    cases = []
    for case in tc02_cases():
        started = time.perf_counter()
        try:
            parsed = await asyncio.to_thread(process, case["name"], case["data"])
            outcome, detail = "accepted", f"{parsed.department}: {parsed.routing_reason}"
        except DocumentRejected as exc:
            outcome, detail = exc.code, exc.message
        ms = round((time.perf_counter() - started) * 1000, 1)
        limit = ACK_LIMIT_MS if case["expect"] == "accepted" else ERROR_LIMIT_MS
        cases.append(
            {
                "case": case["label"],
                "file": case["name"],
                "size_bytes": len(case["data"]),
                "expected": case["expect"],
                "outcome": outcome,
                "detail": detail,
                "ms": ms,
                "limit_ms": limit,
                "passed": outcome == case["expect"] and ms <= limit,
            }
        )
    passed = sum(c["passed"] for c in cases)
    return {
        "score": passed / len(cases),
        "summary": {
            "total": len(cases),
            "passed": passed,
            "valid_upload_success_rate": _rate([c for c in cases if c["expected"] == "accepted"]),
            "invalid_rejection_rate": _rate([c for c in cases if c["expected"] != "accepted"]),
            "max_ms": max(c["ms"] for c in cases),
            "measured_at": "processing pipeline (scripts/benchmark.py measures the HTTP endpoint)",
        },
        "cases": cases,
    }


def _rate(cases: list[dict]) -> float:
    return round(sum(c["passed"] for c in cases) / len(cases), 4) if cases else 0.0


async def run_tc03() -> dict:
    """Runs each query through the real engine in a fresh session, then deletes the sessions."""
    threshold = settings.AUBOT["CONFIDENCE_THRESHOLD"]
    cases, session_ids = [], []
    token = events.muted.set(True)
    try:
        for row in _rows("tc03_low_confidence.csv"):
            session, _, _ = await start_session()
            session_ids.append(session.id)
            result = await handle_customer_message(session, row["query"])
            customer = result.messages[0]
            conf = customer.get("confidence")
            low = customer.get("intent") == OUT_OF_SCOPE or (conf is not None and conf < threshold)
            esc = await Escalation.objects.filter(session=session).afirst()
            expected_turns = 2  # greeting + this customer message, both before the hand-off
            complete = bool(esc) and len(esc.transcript) >= expected_turns and esc.transcript[-1]["text"] == row["query"]
            answered_by = next((m["source"] for m in result.messages[1:] if m["role"] == "bot"), None)
            cases.append(
                {
                    "query": row["query"],
                    "scenario": row["scenario"],
                    "intent": customer.get("intent"),
                    "confidence": conf,
                    "below_threshold": low,
                    "escalated": esc is not None,
                    "transcript_complete": complete,
                    "answered_by": answered_by,
                }
            )
    finally:
        events.muted.reset(token)
        await ChatSession.objects.filter(id__in=session_ids).adelete()

    # Agreed policy (UC01 + UC03): below the threshold the bot may answer only from the
    # business's FAQ; anything else must go to a human. Improvising is the critical defect.
    low_cases = [c for c in cases if c["below_threshold"]]
    escalated_low = sum(c["escalated"] for c in low_cases)
    safe_low = sum(c["escalated"] or c["answered_by"] == "faq_llm" for c in low_cases)
    complete = sum(c["transcript_complete"] for c in cases if c["escalated"])
    escalated_total = sum(c["escalated"] for c in cases)
    score = safe_low / len(low_cases) if low_cases else 0.0
    if escalated_total and complete < escalated_total:
        score = min(score, complete / escalated_total)  # an incomplete transcript is also a critical defect
    return {
        "score": score,
        "summary": {
            "total": len(cases),
            "below_threshold": len(low_cases),
            "handled_safely": safe_low,
            "escalated_when_below_threshold": escalated_low,
            "escalation_trigger_rate": round(escalated_low / len(low_cases), 4) if low_cases else 0.0,
            "transcripts_complete": f"{complete}/{escalated_total}",
            "answered_from_faq_instead": sum(1 for c in low_cases if c["answered_by"] == "faq_llm"),
            "detected_as_low_confidence_rate": round(len(low_cases) / len(cases), 4),
            "note": "Pass = every input below the confidence threshold is escalated or answered strictly from the FAQ "
            "(agreed reconciliation of UC01/UC03; A2 Table 8 counted escalation only). "
            "Vague inputs the model scored above the threshold are reported, not hidden.",
        },
        "cases": cases,
    }


async def run_tc04() -> dict:
    cases = []
    confusion = Counter()
    for row in _rows("tc04_sentiment.csv"):
        s = analyse(row["utterance"])
        confusion[(row["label"], s.label)] += 1
        cases.append({"utterance": row["utterance"], "expected": row["label"], "predicted": s.label, "score": s.score, "correct": s.label == row["label"]})
    correct = sum(c["correct"] for c in cases)
    labels = ["positive", "neutral", "negative"]
    return {
        "score": correct / len(cases),
        "summary": {
            "backend": settings.AUBOT["SENTIMENT_BACKEND"],
            "total": len(cases),
            "correct": correct,
            "accuracy": round(correct / len(cases), 4),
            "confusion_matrix": {e: {p: confusion[(e, p)] for p in labels} for e in labels},
        },
        "cases": cases,
    }


SUITES = {"tc01": run_tc01, "tc02": run_tc02, "tc03": run_tc03, "tc04": run_tc04}


async def run_suite(suite: str, user=None) -> EvaluationRun:
    started = time.perf_counter()
    out = await SUITES[suite]()
    return await EvaluationRun.objects.acreate(
        suite=suite,
        passed=out["score"] >= THRESHOLDS[suite],
        score=round(out["score"], 4),
        threshold=THRESHOLDS[suite],
        summary=out["summary"],
        cases=out["cases"],
        duration_ms=int((time.perf_counter() - started) * 1000),
        triggered_by=user,
    )
