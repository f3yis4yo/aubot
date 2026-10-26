from django.contrib import admin

from .models import ApiUsage, BusinessProfile, FaqEntry


@admin.register(BusinessProfile)
class BusinessProfileAdmin(admin.ModelAdmin):
    list_display = ("business_name", "buddy_name", "buddy_tone", "updated_at")

    def has_add_permission(self, request):
        return not BusinessProfile.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FaqEntry)
class FaqEntryAdmin(admin.ModelAdmin):
    list_display = ("question", "active", "updated_at")
    list_filter = ("active",)
    search_fields = ("question", "answer", "tags")


@admin.register(ApiUsage)
class ApiUsageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "service", "model", "input_tokens", "output_tokens", "audio_seconds", "characters", "latency_ms", "cost_usd")
    list_filter = ("service", "model")

    def has_add_permission(self, request):
        return False
