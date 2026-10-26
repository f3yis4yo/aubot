import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


def upload_path(instance: "Document", filename: str) -> str:
    # Random names: the original filename is customer data and is kept only in the DB.
    ext = filename.rsplit(".", 1)[-1].lower()
    return f"documents/{timezone.now():%Y/%m}/{instance.id}.{ext}"


class Document(models.Model):
    """UC02: a customer-submitted PDF/DOCX, validated, parsed and routed."""

    RECEIVED, IN_REVIEW, PROCESSED = "received", "in_review", "processed"
    STATUSES = [(RECEIVED, "Received"), (IN_REVIEW, "In review"), (PROCESSED, "Processed")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=20, unique=True)
    session = models.ForeignKey("chat.ChatSession", null=True, blank=True, on_delete=models.SET_NULL, related_name="documents")
    original_name = models.CharField(max_length=255)
    file = models.FileField(upload_to=upload_path)
    file_type = models.CharField(max_length=4)  # pdf | docx
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    page_count = models.PositiveIntegerField(null=True, blank=True)
    word_count = models.PositiveIntegerField(default=0)
    has_text_layer = models.BooleanField(default=True)
    text_excerpt = models.TextField(blank=True)
    category = models.CharField(max_length=30)
    department = models.CharField(max_length=40)
    routing_reason = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=STATUSES, default=RECEIVED, db_index=True)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    processing_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.reference} {self.original_name}"
