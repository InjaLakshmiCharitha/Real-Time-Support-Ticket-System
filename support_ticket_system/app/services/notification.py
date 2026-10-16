from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification


async def create_notification(
    db: AsyncSession,
    user_id: int,
    title: str,
    message: str,
    notification_type: str,
    ticket_id: int | None = None,
):
    notification = Notification(
        user_id=user_id,
        ticket_id=ticket_id,
        title=title,
        message=message,
        notification_type=notification_type,
        is_read=False,
    )

    db.add(notification)
    await db.flush()

    return notification
