
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        # Store connections by ticket ID and user role.
        self.active_connections: dict[int, list[dict]] = {}

    async def connect(
        self,
        ticket_id: int,
        websocket: WebSocket,
        user_id: int,
        user_role: str,
    ):
        await websocket.accept()

        connection = {
            "websocket": websocket,
            "user_id": user_id,
            "user_role": user_role,
        }

        self.active_connections.setdefault(ticket_id, []).append(
            connection
        )

    def disconnect(self, ticket_id: int, websocket: WebSocket):
        connections = self.active_connections.get(ticket_id, [])

        self.active_connections[ticket_id] = [
            connection
            for connection in connections
            if connection["websocket"] is not websocket
        ]

        if not self.active_connections[ticket_id]:
            self.active_connections.pop(ticket_id, None)

    async def send_to_ticket(
        self,
        ticket_id: int,
        data: dict,
        internal_note: bool = False,
    ):
        connections = self.active_connections.get(ticket_id, [])
        disconnected = []

        for connection in connections:
            websocket = connection["websocket"]
            role = connection["user_role"]

            # Internal notes are visible only to Agents and Admin.
            if internal_note and role not in ("Agent", "Admin"):
                continue

            try:
                await websocket.send_json(data)
            except Exception:
                disconnected.append(websocket)

        for websocket in disconnected:
            self.disconnect(ticket_id, websocket)

    async def send_typing(
        self,
        ticket_id: int,
        sender_id: int,
        sender_role: str,
        is_typing: bool,
    ):
        # Typing indicators are sent live and are not saved to MySQL.
        data = {
            "type": "typing",
            "sender_id": sender_id,
            "sender_role": sender_role,
            "is_typing": is_typing,
            "message": (
                "Agent is typing..."
                if sender_role == "Agent" and is_typing
                else "Customer is typing..."
                if sender_role == "Customer" and is_typing
                else None
            ),
        }

        connections = self.active_connections.get(ticket_id, [])
        disconnected = []

        for connection in connections:
            if connection["user_id"] == sender_id:
                continue

            try:
                await connection["websocket"].send_json(data)
            except Exception:
                disconnected.append(connection["websocket"])

        for websocket in disconnected:
            self.disconnect(ticket_id, websocket)


manager = ConnectionManager()
