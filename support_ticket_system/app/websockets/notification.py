import os

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models import User
from app.services.notification_manager import notification_manager


router = APIRouter(tags=["Live Notifications"])

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")


@router.websocket("/ws/notifications")
async def notifications_websocket(websocket: WebSocket):
    user_id = None
    connected = False

    try:
        # Read the JWT token from the WebSocket query string.
        token = websocket.query_params.get("token")

        if not token:
            await websocket.close(
                code=1008,
                reason="Token required",
            )
            return

        # Do not accept tokens without a configured secret.
        if not JWT_SECRET_KEY:
            await websocket.close(
                code=1011,
                reason="Authentication configuration error",
            )
            return

        # Decode and validate the JWT.
        try:
            payload = jwt.decode(
                token,
                JWT_SECRET_KEY,
                algorithms=[JWT_ALGORITHM],
            )

            subject = payload.get("sub")
            if subject is None:
                raise ValueError("Token subject is missing")

            user_id = int(subject)

        except (jwt.InvalidTokenError, ValueError, TypeError):
            await websocket.close(
                code=1008,
                reason="Invalid token",
            )
            return

        # Verify that the user exists and is active.
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(User).where(
                    User.id == user_id,
                    User.is_active.is_(True),
                )
            )
            user = result.scalar_one_or_none()

        if user is None:
            await websocket.close(
                code=1008,
                reason="User not found or inactive",
            )
            return

        # Register this user's WebSocket connection.
        await notification_manager.connect(user_id, websocket)
        connected = True

        await websocket.send_json({
            "type": "connected",
            "message": "Connected to live notifications",
        })

        # Keep the connection open until the client disconnects.
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        pass

    except Exception:
        # Avoid exposing internal errors to the client.
        if not connected:
            try:
                await websocket.close(
                    code=1011,
                    reason="WebSocket connection error",
                )
            except Exception:
                pass

    finally:
        if connected and user_id is not None:
            notification_manager.disconnect(user_id, websocket)

