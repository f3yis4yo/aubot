import pytest
from django.contrib.auth.models import Group, User
from django.core.cache import cache

from core.models import FaqEntry
from core.security import OWNER_GROUP, SPECIALIST_GROUP


@pytest.fixture(autouse=True)
def isolated(settings, tmp_path):
    """No network, no Redis, no real media dir: tests never spend API credit."""
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    settings.MEDIA_ROOT = tmp_path
    settings.AUBOT = {**settings.AUBOT, "OPENAI_API_KEY": "", "RATE_LIMIT_PER_MINUTE": 1000}
    cache.clear()
    from chat.knowledge import faq_index

    faq_index.invalidate()
    yield
    cache.clear()


@pytest.fixture
def faq(db):
    return [
        FaqEntry.objects.create(
            question="Do you offer emergency or after-hours call-outs?",
            answer="Yes, 24/7 emergency call-outs cost $180 including the first 30 minutes.",
            tags="emergency urgent after hours burst",
        ),
        FaqEntry.objects.create(
            question="Do you guarantee your work?", answer="Workmanship is guaranteed for 12 months.", tags="warranty guarantee"
        ),
    ]


@pytest.fixture
def specialist(db):
    user = User.objects.create_user("spec", password="correct-horse-1", first_name="Alex")
    user.groups.add(Group.objects.get_or_create(name=SPECIALIST_GROUP)[0])
    return user


@pytest.fixture
def owner(db):
    user = User.objects.create_user("boss", password="correct-horse-2", first_name="Sam")
    user.groups.add(Group.objects.get_or_create(name=OWNER_GROUP)[0])
    return user
