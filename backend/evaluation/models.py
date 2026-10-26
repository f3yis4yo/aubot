from django.conf import settings
from django.db import models


class EvaluationRun(models.Model):
    """Stored result of one benchmark suite (TC01–TC04), kept as Assessment 3 evidence."""

    SUITES = [
        ("tc01", "TC01 Intent accuracy"),
        ("tc02", "TC02 Document handling"),
        ("tc03", "TC03 Escalation"),
        ("tc04", "TC04 Sentiment accuracy"),
    ]

    suite = models.CharField(max_length=8, choices=SUITES)
    passed = models.BooleanField()
    score = models.FloatField()
    threshold = models.FloatField()
    summary = models.JSONField(default=dict)
    cases = models.JSONField(default=list)
    duration_ms = models.PositiveIntegerField(default=0)
    triggered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
