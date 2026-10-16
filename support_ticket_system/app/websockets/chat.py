
import json
import os

import jwt
from jwt import InvalidTokenError

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models import User, Agent, Ticket, Message
from app.services.websocket_manager import manager


router = APIRouter(tags=["Real-Time Ticket Chat"])

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")


async def get_authorized_ticket(ticket_id: int, user: User, db):
    """Return the ticket only if this user can access it."""

    result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()

    if ticket is None:
        return None

    if user.role == "Admin":
        return ticket

    if user.role == "Customer" and ticket.customer_id == user.id:
        return ticket

    if user.role == "Agent":
        result = await db.execute(
            select(Agent).where(Agent.user_id == user.id)
        )
        agent = result.scalar_one_or_none()

        if agent and ticket.assigned_agent_id == agent.id:
            return ticket

    return None


def serialize_message(message: Message, sender_role: str) -> dict:
    return {
        "type": "message",
        "id": message.id,
        "ticket_id": message.ticket_id,
        "sender_id": message.sender_id,
        "sender_role": sender_role,
        "message": message.content,
        "is_internal_note": message.is_internal_note,
        "is_read": message.is_read,
        "created_at": (
            message.created_at.isoformat()
            if message.created_at
            else None
        ),
    }


@router.websocket("/ws/tickets/{ticket_id}")
async def ticket_chat(websocket: WebSocket, ticket_id: int):
    token = websocket.query_params.get("token")

    # Authenticate before accepting the connection.
    if not token or not JWT_SECRET_KEY:
        await websocket.close(code=1008)
        return

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
        )

        user_id = int(payload["sub"])

    except (InvalidTokenError, KeyError, ValueError, TypeError):
        await websocket.close(code=1008)
        return

    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)

        if user is None or not user.is_active:
            await websocket.close(code=1008)
            return

        ticket = await get_authorized_ticket(ticket_id, user, db)

        if ticket is None:
            await websocket.close(code=1008)
            return

        # A customer cannot open a chat to send messages on a closed ticket.
        # They may still connect to read the existing conversation.
        await manager.connect(
            ticket_id=ticket_id,
            websocket=websocket,
            user_id=user.id,
            user_role=user.role,
        )

        try:
            # Send the latest 50 visible messages, oldest first.
            history_query = (
                select(Message)
                .where(Message.ticket_id == ticket_id)
            )

            if user.role == "Customer":
                history_query = history_query.where(
                    Message.is_internal_note.is_(False)
                )

            history_query = history_query.order_by(
                Message.created_at.desc(),
                Message.id.desc(),
            ).limit(50)

            result = await db.execute(history_query)
            history = list(reversed(result.scalars().all()))

            for item in history:
                sender = await db.get(User, item.sender_id)

                if sender is not None:
                    await websocket.send_json(
                        serialize_message(item, sender.role)
                    )

            # Mark messages from other people as read when the chat opens.
            read_query = (
                update(Message)
                .where(
                    Message.ticket_id == ticket_id,
                    Message.sender_id != user.id,
                    Message.is_read.is_(False),
                )
                .values(is_read=True)
            )

            if user.role == "Customer":
                read_query = read_query.where(
                    Message.is_internal_note.is_(False)
                )

            await db.execute(read_query)
            await db.commit()

            while True:
                raw_data = await websocket.receive_text()

                try:
                    data = json.loads(raw_data)
                except json.JSONDecodeError:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Send a valid JSON object",
                    })
                    continue

                # Typing indicators are not saved to the database.
                if data.get("type") == "typing":
                    await manager.send_typing(
                        ticket_id=ticket_id,
                        sender_id=user.id,
                        sender_role=user.role,
                        is_typing=bool(data.get("is_typing", True)),
                    )
                    continue

                content = data.get("message")

                if not isinstance(content, str) or not content.strip():
                    await websocket.send_json({
                        "type": "error",
                        "message": "Message cannot be empty",
                    })
                    continue

                content = content.strip()

                if len(content) > 5000:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Message cannot exceed 5000 characters",
                    })
                    continue

                is_internal_note = data.get("is_internal_note", False)

                if not isinstance(is_internal_note, bool):
                    await websocket.send_json({
                        "type": "error",
                        "message": "is_internal_note must be true or false",
                    })
                    continue

                if is_internal_note and user.role not in ("Agent", "Admin"):
                    await websocket.send_json({
                        "type": "error",
                        "message": "Only Agents and Admin can send internal notes",
                    })
                    continue

                # Customers cannot send messages after the ticket is closed.
                await db.refresh(ticket)

                if user.role == "Customer" and ticket.status == "Closed":
                    await websocket.send_json({
                        "type": "error",
                        "message": "Customers cannot message on closed tickets",
                    })
                    continue

                message = Message(
                    ticket_id=ticket_id,
                    sender_id=user.id,
                    content=content,
                    is_internal_note=is_internal_note,
                    is_read=False,
                )

                db.add(message)

                # Record the first agent reply, excluding internal notes.
                if (
                    user.role == "Agent"
                    and not is_internal_note
                    and ticket.first_response_at is None
                ):
                    from datetime import datetime, timezone

                    ticket.first_response_at = datetime.now(timezone.utc)

                await db.commit()
                await db.refresh(message)

                # Obtain the sender role for the API payload.
                outgoing = serialize_message(message, user.role)

                # Internal notes are sent only to Agent and Admin connections.
                await manager.send_to_ticket(
                    ticket_id=ticket_id,
                    data=outgoing,
                    internal_note=is_internal_note,
                )

        except WebSocketDisconnect:
            manager.disconnect(ticket_id, websocket)

        except Exception:
            manager.disconnect(ticket_id, websocket)
            try:
                await websocket.close(code=1011)
            except Exception:
                pass
