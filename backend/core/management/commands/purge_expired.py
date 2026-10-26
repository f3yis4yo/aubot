"""Delete conversations and documents older than AUBOT_RETENTION_DAYS (APP 11.2:
destroy personal information once it is no longer needed). Schedule daily."""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from chat.models import ChatSession, Escalation
from core.models import ApiUsage
from documents.models import Document


class Command(BaseCommand):
    help = "Purge personal data past the retention period."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, dry_run=False, **opts):
        cutoff = timezone.now() - timedelta(days=settings.AUBOT["RETENTION_DAYS"])
        open_cases = Escalation.objects.exclude(status=Escalation.RESOLVED).values("session_id")
        sessions = ChatSession.objects.filter(updated_at__lt=cutoff).exclude(id__in=open_cases)
        documents = Document.objects.filter(created_at__lt=cutoff, status=Document.PROCESSED)
        self.stdout.write(f"Cut-off {cutoff:%Y-%m-%d}: {sessions.count()} sessions, {documents.count()} documents")
        if dry_run:
            return
        for doc in documents:
            doc.file.delete(save=False)
        documents.delete()
        sessions.delete()  # cascades to messages and resolved escalations
        ApiUsage.objects.filter(created_at__lt=cutoff - timedelta(days=365)).delete()
        self.stdout.write(self.style.SUCCESS("Purge complete"))
