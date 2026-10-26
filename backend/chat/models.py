import hashlib
import secrets
import uuid

from django.conf import settings
from django.db import models


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_reference(prefix: str) -> str:
    return f"AUB-{prefix}-{secrets.token_hex(3).upper()}"


class ChatSession(models.Model):
    """A customer conversation. Customers are anonymous; they prove ownership
    of a session with a random token (only its hash is stored)."""

    ACTIVE, ESCALATED, CLOSED = "active", "escalated", "closed"
    STATUSES = [(ACTIVE, "Active"), (ESCALATED, "With specialist"), (CLOSED, "Closed")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=STATUSES, default=ACTIVE, db_index=True)
    customer_name = models.CharField(max_length=120, blank=True)
    customer_email = models.EmailField(blank=True)
    customer_phone = models.CharField(max_length=40, blank=True)
    voice_consent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def issue_token(cls) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        return token, _hash_token(token)

    def check_token(self, token: str | None) -> bool:
        return bool(token) and secrets.compare_digest(self.token_hash, _hash_token(token))

    def __str__(self):
        return f"Session {self.id} ({self.status})"


class Message(models.Model):
    CUSTOMER, BOT, SPECIALIST, SYSTEM = "customer", "bot", "specialist", "system"
    ROLES = [(CUSTOMER, "Customer"), (BOT, "AUBOT"), (SPECIALIST, "Specialist"), (SYSTEM, "System")]
    SOURCES = [
        ("customer", "Customer"),
        ("intent", "Matched intent"),
        ("smalltalk", "Small talk"),
        ("faq_llm", "FAQ-grounded LLM"),
        ("escalation", "Escalation"),
        ("specialist", "Specialist"),
        ("document", "Document"),
        ("system", "System"),
    ]

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=12, choices=ROLES)
    source = models.CharField(max_length=12, choices=SOURCES, default="system")
    text = models.TextField()
    channel = models.CharField(max_length=8, default="text")  # text | voice
    intent = models.CharField(max_length=40, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    # Sentiment is logged for diagnostics only; it never blocks an escalation (A1/A2 ethics).
    sentiment_label = models.CharField(max_length=10, blank=True)
    sentiment_score = models.FloatField(null=True, blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    author_name = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["session", "created_at"])]

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "role": self.role,
            "source": self.source,
            "text": self.text,
            "channel": self.channel,
            "intent": self.intent,
            "confidence": self.confidence,
            "sentiment_label": self.sentiment_label,
            "sentiment_score": self.sentiment_score,
            "author": self.author_name or None,
            "created_at": self.created_at.isoformat(),
        }


class Escalation(models.Model):
    """UC03: a case handed to a human specialist with the full transcript."""

    LOW_CONFIDENCE, CUSTOMER_REQUEST = "low_confidence", "customer_request"
    REASONS = [(LOW_CONFIDENCE, "Low confidence / not in knowledge base"), (CUSTOMER_REQUEST, "Customer asked for a human")]
    QUEUED, ACTIVE, RESOLVED = "queued", "active", "resolved"
    STATUSES = [(QUEUED, "Waiting"), (ACTIVE, "In progress"), (RESOLVED, "Resolved")]

    reference = models.CharField(max_length=20, unique=True)
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="escalations")
    reason = models.CharField(max_length=20, choices=REASONS)
    trigger_text = models.TextField(blank=True)
    trigger_confidence = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=QUEUED, db_index=True)
    # Snapshot of every turn at hand-off time, so the specialist always receives the
    # complete transcript even if messages are later purged (TC03 completeness).
    transcript = models.JSONField(default=list)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    resolution_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["session"], condition=~models.Q(status="resolved"), name="one_open_escalation_per_session"
            )
        ]

    def __str__(self):
        return self.reference
