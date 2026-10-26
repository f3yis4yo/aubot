import os
import threading

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402  (needs Django set up first)
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402
from django.urls import path  # noqa: E402

from chat.consumers import CustomerConsumer, StaffConsumer  # noqa: E402
from chat.nlu.base import get_intent_engine  # noqa: E402


def _warm_up():
    """Load the embedding model and train the intent classifier as the worker boots,
    so the first customer doesn't pay a ~1.5 s cold start."""
    get_intent_engine().classify("hello")


threading.Thread(target=_warm_up, name="aubot-warmup", daemon=True).start()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(
                URLRouter(
                    [
                        path("ws/chat/<uuid:session_id>/", CustomerConsumer.as_asgi()),
                        path("ws/staff/", StaffConsumer.as_asgi()),
                    ]
                )
            )
        ),
    }
)
