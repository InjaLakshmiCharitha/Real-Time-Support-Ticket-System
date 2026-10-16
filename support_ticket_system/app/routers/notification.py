
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user
from app.database import get_db
from app.models import User, Notification
from app.schemas.notification import (
    NotificationResponse,
    NotificationReadResponse,
)

router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"],
)


@router.get("/", response_model=list[NotificationResponse])
async def get_my_notifications(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(
            Notification.created_at.desc(),
            Notification.id.desc(),
        )
        .offset(skip)
        .limit(limit)
    )

    return result.scalars().all()


@router.put(
    "/{notification_id}/read",
    response_model=NotificationReadResponse,
)
async def mark_notification_as_read(
    notification_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
        .values(is_read=True)
    )

    if result.rowcount == 0:
        await db.rollback()
        raise HTTPException(
            status_code=404,
            detail="Notification not found",
        )

    await db.commit()

    return {"detail": "Notification marked as read"}


@router.put("/read-all")
async def mark_all_notifications_as_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )

    await db.commit()

    return {
        "detail": "All unread notifications marked as read",
        "updated_count": result.rowcount,
    }
