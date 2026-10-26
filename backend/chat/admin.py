from django.contrib import admin

from .models import ChatSession, Escalation, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    fields = ("created_at", "role", "source", "text", "intent", "confidence", "sentiment_label")
    readonly_fields = fields
    can_delete = False


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "customer_name", "customer_email", "created_at")
    list_filter = ("status",)
    search_fields = ("customer_name", "customer_email", "customer_phone")
    exclude = ("token_hash",)
    inlines = [MessageInline]


@admin.register(Escalation)
class EscalationAdmin(admin.ModelAdmin):
    list_display = ("reference", "reason", "status", "assigned_to", "created_at", "resolved_at")
    list_filter = ("status", "reason")
    search_fields = ("reference", "trigger_text")
    readonly_fields = ("transcript",)
