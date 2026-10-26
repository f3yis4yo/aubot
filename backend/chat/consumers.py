"""WebSocket consumers: server -> browser pushes only.

Sending messages goes through the REST API (easy to rate-limit, test and load
test); WebSockets just deliver specialist replies and queue updates instantly.
"""
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from core.security import OWNER_GROUP, SPECIALIST_GROUP

from .events import STAFF_GROUP, session_group
from .models import ChatSession


class CustomerConsumer(AsyncJsonWebsocketConsumer):
    """/ws/chat/<session_id>/?token=... (token proves ownership of the session)."""

    async def connect(self):
        session_id = self.scope["url_route"]["kwargs"]["session_id"]
        token = dict(part.split("=", 1) for part in self.scope["query_string"].decode().split("&") if "=" in part).get("token")
        session = await ChatSession.objects.filter(id=session_id).afirst()
        if session is None or not session.check_token(token):
            await self.close(code=4403)
            return
        self.group = session_group(session.id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def push(self, event):
        await self.send_json({"event": event["event"], "payload": event["payload"]})


class StaffConsumer(AsyncJsonWebsocketConsumer):
    """/ws/staff/ for logged-in specialists (Django session cookie)."""

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated or not user.is_active:
            await self.close(code=4401)
            return
        groups = {g async for g in user.groups.values_list("name", flat=True)}
        if not (user.is_superuser or user.is_staff or groups & {SPECIALIST_GROUP, OWNER_GROUP}):
            await self.close(code=4403)
            return
        await self.channel_layer.group_add(STAFF_GROUP, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(STAFF_GROUP, self.channel_name)

    async def push(self, event):
        await self.send_json({"event": event["event"], "payload": event["payload"]})
