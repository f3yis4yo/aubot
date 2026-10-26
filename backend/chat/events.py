"""Real-time fan-out over the Channels layer (Redis in production).

Groups:
  session.<uuid>  - the customer's browser for one chat
  staff           - every logged-in specialist console
"""
from contextvars import ContextVar

from channels.layers import get_channel_layer

STAFF_GROUP = "staff"

# Set during evaluation runs so benchmark sessions don't flash through live consoles.
muted: ContextVar[bool] = ContextVar("aubot_events_muted", default=False)


def session_group(session_id) -> str:
    return f"session.{session_id}"


async def _send(group: str, event: str, payload: dict):
    layer = get_channel_layer()
    if layer is not None and not muted.get():
        await layer.group_send(group, {"type": "push", "event": event, "payload": payload})


async def to_customer(session_id, event: str, payload: dict):
    await _send(session_group(session_id), event, payload)


async def to_staff(event: str, payload: dict):
    await _send(STAFF_GROUP, event, payload)
