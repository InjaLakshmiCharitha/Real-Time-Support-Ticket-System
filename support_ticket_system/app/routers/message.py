
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user
from app.database import get_db
from app.models import User, Agent, Ticket, Message, Notification
from app.schemas.message import MessageCreate
from app.services.websocket_manager import manager
from app.services.notification_manager import notification_manager


router = APIRouter(
    prefix="/tickets",
    tags=["Ticket Messages"],
)


async def check_ticket_access(
    ticket_id: int,
    user: User,
    db: AsyncSession,
):
    result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = result.scalar_one_or_none()

    if ticket is None:
        raise HTTPException(
            status_code=404,
            detail="Ticket not found",
        )

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

    raise HTTPException(
        status_code=403,
        detail="You are not allowed to access this ticket",
    )


def format_message(message: Message, sender_role: str):
    return {
        "id": message.id,
        "ticket_id": message.ticket_id,
        "sender_id": message.sender_id,
        "sender_role": sender_role,
        "message": message.content,
        "is_internal_note": message.is_internal_note,
        "is_read": message.is_read,
        "created_at": message.created_at,
    }


def customer_is_in_ticket_chat(ticket_id: int, customer_id: int) -> bool:
    """
    Check whether the customer currently has an active
    WebSocket connection to this ticket's chat.
    """
    connections = manager.active_connections.get(ticket_id, [])

    return any(
        connection.get("user_id") == customer_id
        and connection.get("user_role") == "Customer"
        for connection in connections
    )


@router.get("/{ticket_id}/messages")
async def get_ticket_messages(
    ticket_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await check_ticket_access(ticket_id, current_user, db)

    query = select(Message).where(
        Message.ticket_id == ticket_id
    )

    # Customers must never see internal notes.
    if current_user.role == "Customer":
        query = query.where(
            Message.is_internal_note.is_(False)
        )

    query = query.order_by(
        Message.created_at.desc(),
        Message.id.desc(),
    ).offset(skip).limit(limit)

    result = await db.execute(query)
    messages = list(result.scalars().all())

    # Return messages in chronological order.
    messages.reverse()

    response = []

    for message in messages:
        sender = await db.get(User, message.sender_id)

        response.append(
            format_message(
                message,
                sender.role if sender else "Unknown",
            )
        )

        # Mark messages from other users as read.
        if message.sender_id != current_user.id:
            message.is_read = True

    await db.commit()

    return response


@router.post("/{ticket_id}/messages")
async def send_ticket_message(
    ticket_id: int,
    message_data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = await check_ticket_access(
        ticket_id,
        current_user,
        db,
    )

    content = message_data.message.strip()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty",
        )

    if (
        current_user.role == "Customer"
        and ticket.status == "Closed"
    ):
        raise HTTPException(
            status_code=400,
            detail="Customers cannot send messages on closed tickets",
        )

    if (
        message_data.is_internal_note
        and current_user.role not in ("Agent", "Admin")
    ):
        raise HTTPException(
            status_code=403,
            detail="Only agents or admins can send internal notes",
        )

    new_message = Message(
        ticket_id=ticket_id,
        sender_id=current_user.id,
        content=content,
        is_internal_note=message_data.is_internal_note,
        is_read=False,
    )

    db.add(new_message)

    reply_notification = None

    # Notify the customer about a public agent reply,
    # unless the customer is already connected to this ticket chat.
    if (
        current_user.role == "Agent"
        and not message_data.is_internal_note
        and not customer_is_in_ticket_chat(
            ticket_id,
            ticket.customer_id,
        )
    ):
        reply_notification = Notification(
            user_id=ticket.customer_id,
            ticket_id=ticket.id,
            title="New Reply on Your Ticket",
            message=(
                f"You received a new reply on ticket "
                f"{ticket.ticket_number}."
            ),
            notification_type="ticket_reply",
            is_read=False,
        )
        db.add(reply_notification)

    # Record the agent's first public response for SLA tracking.
    if (
        current_user.role == "Agent"
        and not message_data.is_internal_note
        and ticket.first_response_at is None
    ):
        ticket.first_response_at = datetime.now(
            timezone.utc
        ).replace(tzinfo=None)

    # Save the message and notification before sending live events.
    await db.commit()
    await db.refresh(new_message)

    outgoing = format_message(
        new_message,
        current_user.role,
    )

    # Send the message to connected users in the ticket chat.
    await manager.send_to_ticket(
        ticket_id,
        {"type": "message", **outgoing},
        internal_note=message_data.is_internal_note,
    )

    # Send the notification to the customer if one was created.
    if reply_notification is not None:
        await db.refresh(reply_notification)

        await notification_manager.send_notification(
            ticket.customer_id,
            {
                "id": reply_notification.id,
                "user_id": reply_notification.user_id,
                "ticket_id": reply_notification.ticket_id,
                "title": reply_notification.title,
                "message": reply_notification.message,
                "notification_type": (
                    reply_notification.notification_type
                ),
                "is_read": reply_notification.is_read,
                "created_at": (
                    reply_notification.created_at.isoformat()
                    if reply_notification.created_at
                    else None
                ),
            },
        )

    return outgoing

