from ninja import Router, Schema
from ninja.errors import HttpError

from core.security import current_staff

from .models import EvaluationRun
from .runner import SUITES, THRESHOLDS, run_suite

router = Router(tags=["staff"])


class RunIn(Schema):
    suite: str


def _run_row(r: EvaluationRun, with_cases: bool = False) -> dict:
    row = {
        "id": r.id,
        "suite": r.suite,
        "label": r.get_suite_display(),
        "passed": r.passed,
        "score": r.score,
        "threshold": r.threshold,
        "summary": r.summary,
        "duration_ms": r.duration_ms,
        "created_at": r.created_at.isoformat(),
    }
    if with_cases:
        row["cases"] = r.cases
    return row


@router.get("/evaluation")
async def latest(request):
    await current_staff(request)
    latest_runs = {}
    for suite in SUITES:
        run = await EvaluationRun.objects.filter(suite=suite).afirst()
        latest_runs[suite] = _run_row(run, with_cases=True) if run else None
    history = [_run_row(r) async for r in EvaluationRun.objects.all()[:40]]
    return {
        "suites": [{"suite": k, "label": dict(EvaluationRun.SUITES)[k], "threshold": THRESHOLDS[k]} for k in SUITES],
        "latest": latest_runs,
        "history": history,
    }


@router.post("/evaluation/run")
async def run(request, payload: RunIn):
    user = await current_staff(request)
    suites = list(SUITES) if payload.suite == "all" else [payload.suite]
    if any(s not in SUITES for s in suites):
        raise HttpError(400, "Unknown suite.")
    return {"runs": [_run_row(await run_suite(s, user), with_cases=True) for s in suites]}
