from typing import Optional
from datetime import datetime, timedelta

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy import select, func, asc, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    User,
    Agent,
    AgentCategory,
    Category,
    SLAPolicy,
    Ticket,
    TicketHistory,
    Notification,
)
from app.auth.security import get_current_user
from app.schemas.ticket import (
    TicketCreate,
    TicketResponse,
    TicketStatusUpdate,
    TicketPriorityUpdate,
    TicketHistoryResponse,
)
from app.services.assignment import assign_ticket
from app.services.notification_manager import notification_manager
from app.services.ticket_count_manager import (
    broadcast_open_ticket_counts,
)


router = APIRouter(prefix="/tickets", tags=["Tickets"])


async def add_history(
    db: AsyncSession,
    ticket_id: int,
    changed_by_id: Optional[int],
    action: str,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    details: Optional[str] = None,
):
    history = TicketHistory(
        ticket_id=ticket_id,
        changed_by_id=changed_by_id,
        action=action,
        old_value=old_value,
        new_value=new_value,
        details=details,
    )
    db.add(history)


async def get_agent_profile(
    db: AsyncSession,
    user_id: int,
) -> Agent:
    result = await db.execute(
        select(Agent).where(Agent.user_id == user_id)
    )

    agent = result.scalar_one_or_none()

    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent profile not found",
        )

    return agent


async def get_ticket_or_404(
    db: AsyncSession,
    ticket_id: int,
) -> Ticket:
    result = await db.execute(
        select(Ticket).where(Ticket.id == ticket_id)
    )

    ticket = result.scalar_one_or_none()

    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ticket not found",
        )

    return ticket


async def get_sla_policy(
    db: AsyncSession,
    priority: str,
) -> Optional[SLAPolicy]:
    result = await db.execute(
        select(SLAPolicy).where(
            SLAPolicy.priority == priority
        )
    )

    return result.scalar_one_or_none()


async def set_sla_deadlines(
    db: AsyncSession,
    ticket: Ticket,
):
    policy = await get_sla_policy(db, ticket.priority)

    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"No SLA policy configured for priority "
                f"{ticket.priority}"
            ),
        )

    now = datetime.utcnow()

    if ticket.first_response_at is None:
        ticket.first_response_due = (
            now
            + timedelta(
                minutes=policy.first_response_minutes
            )
        )

    ticket.resolution_due = (
        now
        + timedelta(minutes=policy.resolution_minutes)
    )


async def send_saved_notification(
    db: AsyncSession,
    user_id: int,
    ticket_id: int,
    title: str,
    message: str,
    notification_type: str = "ticket_update",
):
    """
    Save a notification and return its WebSocket payload.
    The caller should broadcast the returned payload only
    after committing the database transaction.
    """
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

    return {
        "id": notification.id,
        "user_id": notification.user_id,
        "ticket_id": notification.ticket_id,
        "title": notification.title,
        "message": notification.message,
        "notification_type": notification.notification_type,
        "is_read": notification.is_read,
        "created_at": (
            notification.created_at.isoformat()
            if notification.created_at
            else None
        ),
    }


async def broadcast_notification(
    user_id: int,
    payload: dict,
):
    await notification_manager.send_notification(
        user_id,
        payload,
    )


async def check_ticket_access(
    db: AsyncSession,
    ticket: Ticket,
    current_user: User,
):
    if current_user.role == "Admin":
        return

    if current_user.role == "Customer":
        if ticket.customer_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You cannot access this ticket",
            )
        return

    if current_user.role == "Agent":
        agent = await get_agent_profile(
            db,
            current_user.id,
        )

        if ticket.assigned_agent_id != agent.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This ticket is not assigned to you",
            )
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Permission denied",
    )


@router.post(
    "",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_ticket(
    ticket_data: TicketCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can create tickets",
        )

    category_result = await db.execute(
        select(Category).where(
            Category.id == ticket_data.category_id
        )
    )

    category = category_result.scalar_one_or_none()

    if category is None or not category.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or inactive category",
        )

    # Generate the required ticket number format.
    date_prefix = datetime.utcnow().strftime("%Y%m%d")
    number_prefix = f"TKT-{date_prefix}-"

    count_result = await db.execute(
        select(func.count(Ticket.id)).where(
            Ticket.ticket_number.like(
                f"{number_prefix}%"
            )
        )
    )

    ticket_count = count_result.scalar_one()
    ticket_number = (
        f"{number_prefix}{ticket_count + 1:04d}"
    )

    ticket = Ticket(
        ticket_number=ticket_number,
        customer_id=current_user.id,
        category_id=ticket_data.category_id,
        subject=ticket_data.subject.strip(),
        description=ticket_data.description.strip(),
        priority=ticket_data.priority,
        status="Open",
    )

    try:
        db.add(ticket)
        await db.flush()

        await set_sla_deadlines(db, ticket)

        await add_history(
            db=db,
            ticket_id=ticket.id,
            changed_by_id=current_user.id,
            action="Ticket Created",
            new_value="Open",
            details="Customer created a new support ticket",
        )

        # Automatically assign to an eligible agent.
        await assign_ticket(
              db=db,
              ticket=ticket,
              changed_by_id=current_user.id,
        )

        await db.commit()
        await db.refresh(ticket)

    except Exception:
        await db.rollback()
        raise

    await broadcast_open_ticket_counts(db)

    return ticket


@router.get("")
async def list_tickets(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    ticket_number: Optional[str] = Query(None),
    subject: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(
        None,
        alias="status",
    ),
    priority: Optional[str] = Query(None),
    category_id: Optional[int] = Query(None, ge=1),
    assigned_agent_id: Optional[int] = Query(None, ge=1),
    sla_breached: Optional[bool] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    sort_by: str = Query("created_at"),
    order: str = Query("desc"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    allowed_sort_fields = {
        "created_at": Ticket.created_at,
        "updated_at": Ticket.updated_at,
        "priority": Ticket.priority,
        "status": Ticket.status,
        "resolution_due": Ticket.resolution_due,
    }

    if sort_by not in allowed_sort_fields:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid sort_by. Choose created_at, updated_at, "
                "priority, status, or resolution_due."
            ),
        )

    if order.lower() not in {"asc", "desc"}:
        raise HTTPException(
            status_code=400,
            detail="order must be asc or desc",
        )

    if from_date and to_date and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="from_date cannot be later than to_date",
        )

    query = select(Ticket)
    count_query = select(func.count(Ticket.id))

    if current_user.role == "Customer":
        query = query.where(
            Ticket.customer_id == current_user.id
        )
        count_query = count_query.where(
            Ticket.customer_id == current_user.id
        )

    elif current_user.role == "Agent":
        agent = await get_agent_profile(
            db,
            current_user.id,
        )

        query = query.where(
            Ticket.assigned_agent_id == agent.id
        )
        count_query = count_query.where(
            Ticket.assigned_agent_id == agent.id
        )

    elif current_user.role != "Admin":
        raise HTTPException(
            status_code=403,
            detail="Permission denied",
        )

    filters = []

    if ticket_number:
        filters.append(
            Ticket.ticket_number.ilike(
                f"%{ticket_number.strip()}%"
            )
        )

    if subject:
        filters.append(
            Ticket.subject.ilike(
                f"%{subject.strip()}%"
            )
        )

    if status_filter:
        filters.append(
            Ticket.status == status_filter
        )

    if priority:
        filters.append(
            Ticket.priority == priority
        )

    if category_id is not None:
        filters.append(
            Ticket.category_id == category_id
        )

    if assigned_agent_id is not None:
        filters.append(
            Ticket.assigned_agent_id == assigned_agent_id
        )

    if sla_breached is not None:
        filters.append(
            Ticket.sla_breached == sla_breached
        )

    if from_date:
        filters.append(
            Ticket.created_at >= from_date
        )

    if to_date:
        filters.append(
            Ticket.created_at <= to_date
        )

    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    sort_column = allowed_sort_fields[sort_by]

    if order.lower() == "asc":
        query = query.order_by(asc(sort_column))
    else:
        query = query.order_by(desc(sort_column))

    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    tickets = result.scalars().all()

    return {
        "skip": skip,
        "limit": limit,
        "total": total,
        "tickets": [
            {
                "id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "subject": ticket.subject,
                "description": ticket.description,
                "category_id": ticket.category_id,
                "assigned_agent_id": ticket.assigned_agent_id,
                "priority": ticket.priority,
                "status": ticket.status,
                "sla_breached": ticket.sla_breached,
                "resolution_due": (
                    ticket.resolution_due.isoformat()
                    if ticket.resolution_due
                    else None
                ),
                "created_at": (
                    ticket.created_at.isoformat()
                    if ticket.created_at
                    else None
                ),
                "updated_at": (
                    ticket.updated_at.isoformat()
                    if ticket.updated_at
                    else None
                ),
            }
            for ticket in tickets
        ],
    }



@router.get(
    "/{ticket_id}",
    response_model=TicketResponse,
)
async def get_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = await get_ticket_or_404(db, ticket_id)

    await check_ticket_access(
        db,
        ticket,
        current_user,
    )

    return ticket



@router.put(
    "/{ticket_id}/status",
    response_model=TicketResponse,
)
async def update_ticket_status(
    ticket_id: int,
    status_data: TicketStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = await get_ticket_or_404(db, ticket_id)

    await check_ticket_access(
        db,
        ticket,
        current_user,
    )

    if current_user.role == "Customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Customers cannot change ticket status using "
                "this endpoint. Use the reopen endpoint for "
                "eligible resolved tickets."
            ),
        )

    if current_user.role not in {"Agent", "Admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    old_status = ticket.status
    new_status = status_data.status
    now = datetime.utcnow()

    allowed_transitions = {
        "Open": ["Assigned"],
        "Assigned": ["In Progress"],
        "In Progress": [
            "Waiting on Customer",
            "Resolved",
        ],
        "Waiting on Customer": [
            "In Progress",
            "Resolved",
        ],
        "Resolved": ["Closed"],
        "Closed": [],
    }

    if new_status not in allowed_transitions.get(
        old_status,
        [],
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot change status from {old_status} "
                f"to {new_status}"
            ),
        )

    if new_status == "Waiting on Customer":
        ticket.waiting_since = now

    elif old_status == "Waiting on Customer":
        if ticket.waiting_since is not None:
            elapsed = int(
                (now - ticket.waiting_since).total_seconds()
            )

            ticket.paused_seconds = (
                (ticket.paused_seconds or 0)
                + max(elapsed, 0)
            )

            ticket.waiting_since = None

    ticket.status = new_status

    if new_status == "Resolved":
        ticket.resolved_at = now

    if new_status == "Closed":
        ticket.closed_at = now

    await add_history(
        db=db,
        ticket_id=ticket.id,
        changed_by_id=current_user.id,
        action="Status Changed",
        old_value=old_status,
        new_value=new_status,
    )

    try:
        payload = await send_saved_notification(
            db=db,
            user_id=ticket.customer_id,
            ticket_id=ticket.id,
            title="Ticket Status Updated",
            message=(
                f"Your ticket {ticket.ticket_number} "
                f"status changed to {new_status}"
            ),
        )

        await db.commit()
        await db.refresh(ticket)

    except Exception:
        await db.rollback()
        raise

    await broadcast_notification(
        ticket.customer_id,
        payload,
    )

    await broadcast_open_ticket_counts(db)

    return ticket



@router.put(
    "/{ticket_id}/priority",
    response_model=TicketResponse,
)
async def update_ticket_priority(
    ticket_id: int,
    priority_data: TicketPriorityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in {"Agent", "Admin"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only agents and admins can update priority",
        )

    ticket = await get_ticket_or_404(db, ticket_id)

    await check_ticket_access(
        db,
        ticket,
        current_user,
    )

    if ticket.status == "Closed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Closed tickets cannot be changed",
        )

    old_priority = ticket.priority
    new_priority = priority_data.priority

    valid_priorities = {
        "Low",
        "Medium",
        "High",
        "Urgent",
    }

    if new_priority not in valid_priorities:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid priority",
        )

    if old_priority == new_priority:
        return ticket

    ticket.priority = new_priority

    await set_sla_deadlines(db, ticket)

    await add_history(
        db=db,
        ticket_id=ticket.id,
        changed_by_id=current_user.id,
        action="Priority Changed",
        old_value=old_priority,
        new_value=new_priority,
    )

    try:
        payload = await send_saved_notification(
            db=db,
            user_id=ticket.customer_id,
            ticket_id=ticket.id,
            title="Ticket Priority Updated",
            message=(
                f"Your ticket {ticket.ticket_number} "
                f"priority changed to {new_priority}"
            ),
        )

        await db.commit()
        await db.refresh(ticket)

    except Exception:
        await db.rollback()
        raise

    await broadcast_notification(
        ticket.customer_id,
        payload,
    )

    await broadcast_open_ticket_counts(db)

    return ticket



@router.put(
    "/{ticket_id}/reopen",
    response_model=TicketResponse,
)
async def reopen_ticket(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = await get_ticket_or_404(db, ticket_id)

    if current_user.role != "Customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can reopen their tickets",
        )

    if ticket.customer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot reopen another customer's ticket",
        )

    if ticket.status != "Resolved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only resolved tickets can be reopened",
        )

    now = datetime.utcnow()

    if ticket.resolved_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ticket resolution timestamp is missing",
        )

    if now > ticket.resolved_at + timedelta(days=7):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tickets can only be reopened within 7 days",
        )

    if (ticket.reopen_count or 0) >= 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ticket can only be reopened twice",
        )

    old_status = ticket.status

    ticket.status = "In Progress"
    ticket.reopen_count = (ticket.reopen_count or 0) + 1
    ticket.resolved_at = None
    ticket.closed_at = None

    await set_sla_deadlines(db, ticket)

    await add_history(
        db=db,
        ticket_id=ticket.id,
        changed_by_id=current_user.id,
        action="Ticket Reopened",
        old_value=old_status,
        new_value="In Progress",
        details=f"Reopen count: {ticket.reopen_count}",
    )

    payloads = []

    if ticket.assigned_agent_id is not None:
        agent_result = await db.execute(
            select(Agent).where(
                Agent.id == ticket.assigned_agent_id
            )
        )

        agent = agent_result.scalar_one_or_none()

        if agent is not None:
            payload = await send_saved_notification(
                db=db,
                user_id=agent.user_id,
                ticket_id=ticket.id,
                title="Ticket Reopened",
                message=(
                    f"Ticket {ticket.ticket_number} "
                    "has been reopened by the customer"
                ),
            )
            payloads.append((agent.user_id, payload))

    try:
        await db.commit()
        await db.refresh(ticket)

    except Exception:
        await db.rollback()
        raise

    for user_id, payload in payloads:
        await broadcast_notification(user_id, payload)

    await broadcast_open_ticket_counts(db)

    return ticket



@router.get(
    "/{ticket_id}/history",
    response_model=list[TicketHistoryResponse],
)
async def get_ticket_history(
    ticket_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ticket = await get_ticket_or_404(db, ticket_id)

    await check_ticket_access(
        db,
        ticket,
        current_user,
    )

    result = await db.execute(
        select(TicketHistory)
        .where(TicketHistory.ticket_id == ticket_id)
        .order_by(asc(TicketHistory.created_at))
    )

    return result.scalars().all()
