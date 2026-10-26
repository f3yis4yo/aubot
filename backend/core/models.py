from decimal import Decimal

from django.db import models


class BusinessProfile(models.Model):
    """Singleton the SME owner edits (Django admin or the Settings screen).

    Assessment 1: "The operator sets name, greeting and tone without retraining."
    """

    TONES = [("warm", "Warm and friendly"), ("professional", "Professional"), ("upbeat", "Upbeat")]
    VOICES = [(v, v.title()) for v in ("alloy", "ash", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer")]

    business_name = models.CharField(max_length=120, default="Harbourside Home Services")
    tagline = models.CharField(max_length=200, default="Licensed plumbing & electrical, Sydney-wide")
    phone = models.CharField(max_length=40, default="(02) 9000 1234")
    email = models.EmailField(default="hello@harbourside.example")
    address = models.CharField(max_length=200, default="12 Wharf Road, Balmain NSW 2041")
    opening_hours = models.CharField(max_length=200, default="Mon–Fri 7am–6pm, Sat 8am–2pm, closed Sunday and public holidays")
    buddy_name = models.CharField(max_length=40, default="Buddy")
    buddy_greeting = models.CharField(
        max_length=300,
        default="Hi, I'm Buddy, Harbourside's AI assistant. I can answer questions, take documents, or connect you with our team.",
    )
    buddy_tone = models.CharField(max_length=20, choices=TONES, default="warm")
    buddy_voice = models.CharField(max_length=20, choices=VOICES, default="coral")
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    async def aget_solo(cls) -> "BusinessProfile":
        obj, _ = await cls.objects.aget_or_create(pk=1)
        return obj

    @classmethod
    def get_solo(cls) -> "BusinessProfile":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return self.business_name


class FaqEntry(models.Model):
    """Knowledge base the generative fallback is grounded in (UC01)."""

    question = models.CharField(max_length=300)
    answer = models.TextField()
    tags = models.CharField(max_length=200, blank=True)
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "FAQ entry"
        verbose_name_plural = "FAQ entries"

    def __str__(self):
        return self.question


class ApiUsage(models.Model):
    """One row per paid API call, used for the budget cap and the cost metric."""

    SERVICES = [("chat", "LLM"), ("transcribe", "Speech-to-text"), ("tts", "Text-to-speech")]

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    service = models.CharField(max_length=20, choices=SERVICES)
    model = models.CharField(max_length=60)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    audio_seconds = models.FloatField(default=0)
    characters = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"))

    class Meta:
        ordering = ["-created_at"]
