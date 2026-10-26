import asyncio

from django.core.management.base import BaseCommand

from evaluation.runner import SUITES, run_suite


class Command(BaseCommand):
    help = "Run benchmark suites TC01-TC04 and store the results."

    def add_arguments(self, parser):
        parser.add_argument("suite", nargs="?", default="all", choices=["all", *SUITES])

    def handle(self, *args, suite="all", **opts):
        failed = False
        for name in SUITES if suite == "all" else [suite]:
            run = asyncio.run(run_suite(name))
            mark = self.style.SUCCESS("PASS") if run.passed else self.style.ERROR("FAIL")
            self.stdout.write(f"{mark} {run.get_suite_display():28} score={run.score:.2%} threshold={run.threshold:.0%}")
            for key, value in run.summary.items():
                self.stdout.write(f"       {key}: {value}")
            failed |= not run.passed
        if failed:
            raise SystemExit(1)
