from django.contrib import admin

from .models import EvaluationRun


@admin.register(EvaluationRun)
class EvaluationRunAdmin(admin.ModelAdmin):
    list_display = ("created_at", "suite", "passed", "score", "threshold", "duration_ms")
    list_filter = ("suite", "passed")
