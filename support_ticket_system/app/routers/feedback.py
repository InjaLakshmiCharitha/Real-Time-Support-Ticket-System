
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user, require_roles
from app.database import get_db
from app.models import Feedback, Ticket
from app.schemas.feedback import FeedbackCreate, FeedbackResponse


router = APIRouter(
    prefix="/feedback",
    tags=["Customer Feedback"],
)


@router.post(
    "/tickets/{ticket_id}",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_feedback(
    ticket_id: int,
    data: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("Customer")),
):
    ticket_result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = ticket_result.scalar_one_or_none()

    if ticket is None:
        raise HTTPException(
            status_code=404,
            detail="Ticket not found",
        )

    if ticket.customer_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You can only submit feedback for your own tickets",
        )

    if ticket.status not in ("Resolved", "Closed"):
        raise HTTPException(
            status_code=400,
            detail="Feedback can only be submitted for resolved or closed tickets",
        )

    existing_result = await db.execute(
        select(Feedback).where(Feedback.ticket_id == ticket_id)
    )
    existing_feedback = existing_result.scalar_one_or_none()

    if existing_feedback is not None:
        raise HTTPException(
            status_code=409,
            detail="Feedback has already been submitted for this ticket",
        )

    feedback = Feedback(
        ticket_id=ticket.id,
        customer_id=current_user.id,
        rating=data.rating,
        comment=data.comment,
    )

    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)

    return feedback


@router.get(
    "/tickets/{ticket_id}",
    response_model=FeedbackResponse,
)
async def get_ticket_feedback(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    ticket_result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = ticket_result.scalar_one_or_none()

    if ticket is None:
        raise HTTPException(
            status_code=404,
            detail="Ticket not found",
        )

    if (
        current_user.role != "Admin"
        and ticket.customer_id != current_user.id
    ):
        raise HTTPException(
            status_code=403,
            detail="You cannot view feedback for this ticket",
        )

    feedback_result = await db.execute(
        select(Feedback).where(Feedback.ticket_id == ticket_id)
    )
    feedback = feedback_result.scalar_one_or_none()

    if feedback is None:
        raise HTTPException(
            status_code=404,
            detail="Feedback not found for this ticket",
        )

    return feedback


@router.get(
    "/",
    response_model=list[FeedbackResponse],
)
async def list_feedback(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("Admin")),
):
    result = await db.execute(
        select(Feedback).order_by(Feedback.created_at.desc())
    )
    return result.scalars().all()


@router.get("/reports/summary")
async def feedback_summary(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("Admin")),
):
    result = await db.execute(
        select(
            func.count(Feedback.id),
            func.avg(Feedback.rating),
        )
    )

    total_feedback, average_rating = result.one()

    return {
        "total_feedback": total_feedback,
        "average_rating": (
            round(float(average_rating), 2)
            if average_rating is not None
            else None
        ),
    }
