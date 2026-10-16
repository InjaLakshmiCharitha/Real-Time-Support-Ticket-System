
from typing import Dict, List

from fastapi import WebSocket


class NotificationManager:
    def __init__(self):
        # Store active WebSocket connections by user ID.
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()

        self.active_connections.setdefault(user_id, []).append(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket):
        connections = self.active_connections.get(user_id)

        if connections is None:
            return

        if websocket in connections:
            connections.remove(websocket)

        if not connections:
            self.active_connections.pop(user_id, None)

    async def send_to_user(self, user_id: int, data: dict):
        # Use a copy so disconnections do not affect iteration.
        connections = self.active_connections.get(user_id, []).copy()

        for websocket in connections:
            try:
                await websocket.send_json(data)
            except Exception:
                # Remove connections that can no longer receive messages.
                self.disconnect(user_id, websocket)

    async def send_notification(
        self,
        user_id: int,
        notification: dict,
    ):
        await self.send_to_user(
            user_id,
            {
                "type": "notification",
                "notification": notification,
            },
        )


# One shared manager for the application.
notification_manager = NotificationManager()

