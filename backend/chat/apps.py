from django.apps import AppConfig


class ChatConfig(AppConfig):
    name = "chat"

    def ready(self):
        from . import knowledge  # noqa: F401  (registers FAQ cache-invalidation signals)
