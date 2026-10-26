"""The benchmark targets from Assessment 2, Table 8, enforced in CI."""
import pytest

from evaluation.runner import run_suite

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("suite", ["tc01", "tc02", "tc03", "tc04"])
async def test_suite_meets_threshold(suite, faq):
    run = await run_suite(suite)
    assert run.passed, (suite, run.score, run.summary)
