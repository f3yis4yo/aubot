"""Create the demo business profile, FAQ, staff groups and two staff accounts.

Passwords come from AUBOT_OWNER_PASSWORD / AUBOT_SPECIALIST_PASSWORD, or are
generated and printed once. Safe to run repeatedly.
"""
import os
import secrets

import yaml
from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand

from core.models import BusinessProfile, FaqEntry
from core.security import OWNER_GROUP, SPECIALIST_GROUP


class Command(BaseCommand):
    help = "Seed demo data (business profile, FAQ, staff accounts)."

    def add_arguments(self, parser):
        parser.add_argument("--reset-faq", action="store_true", help="Replace FAQ entries with data/faq.yaml")

    def handle(self, *args, reset_faq=False, **opts):
        BusinessProfile.get_solo()
        if reset_faq:
            FaqEntry.objects.all().delete()
        if not FaqEntry.objects.exists():
            entries = yaml.safe_load((settings.AUBOT["DATA_DIR"] / "faq.yaml").read_text())
            FaqEntry.objects.bulk_create(FaqEntry(**e) for e in entries)
            self.stdout.write(f"Loaded {len(entries)} FAQ entries")

        owners, _ = Group.objects.get_or_create(name=OWNER_GROUP)
        specialists, _ = Group.objects.get_or_create(name=SPECIALIST_GROUP)
        accounts = [
            ("owner", "Sam", "Nguyen", owners, "AUBOT_OWNER_PASSWORD", True),
            ("specialist", "Alex", "Taylor", specialists, "AUBOT_SPECIALIST_PASSWORD", False),
        ]
        for username, first, last, group, env, superuser in accounts:
            user, created = User.objects.get_or_create(username=username, defaults={"first_name": first, "last_name": last})
            user.groups.add(group)
            if created:
                password = os.environ.get(env) or secrets.token_urlsafe(12)
                user.set_password(password)
                user.is_staff = True
                user.is_superuser = superuser
                user.save()
                self.stdout.write(self.style.SUCCESS(f"Created {username} / {password}"))
            else:
                self.stdout.write(f"{username} already exists (password unchanged)")
