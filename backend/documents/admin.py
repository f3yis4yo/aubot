from django.contrib import admin

from .models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("reference", "original_name", "category", "department", "status", "created_at")
    list_filter = ("status", "department", "category", "has_text_layer")
    search_fields = ("reference", "original_name")
    readonly_fields = ("sha256", "text_excerpt", "routing_reason")
