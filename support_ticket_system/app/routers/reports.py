
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Ticket, User, Agent, Feedback, Category
from app.auth.security import get_current_user


router = APIRouter(
    prefix="/reports",
    tags=["Admin Reports"],
)


def check_admin(current_user: User):
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can access reports",
        )


def duration_minutes(start, end):
    """Return the time difference in minutes."""
    if start is None or end is None:
        return None

    return (end - start).total_seconds() / 60


def average(values):
    """Calculate the average of available values."""
    valid_values = [value for value in values if value is not None]
    if not valid_values:
        return None

    return round(sum(valid_values) / len(valid_values), 2)


def date_filters(start_date, end_date):
    """Convert inclusive date filters into a datetime range."""
    start = datetime.combine(start_date, time.min) if start_date else None
    end = (
        datetime.combine(end_date + timedelta(days=1), time.min)
        if end_date
        else None
    )
    return start, end


def apply_ticket_date_filter(query, start, end):
    if start:
        query = query.where(Ticket.created_at >= start)
    if end:
        query = query.where(Ticket.created_at < end)
    return query


@router.get("/dashboard")
async def ticket_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_admin(current_user)

    result = await db.execute(
        select(Ticket.status, func.count(Ticket.id))
        .group_by(Ticket.status)
    )
    tickets_by_status = {
        str(status_name): count
        for status_name, count in result.all()
    }

    total_result = await db.execute(
        select(func.count(Ticket.id))
    )
    total_tickets = total_result.scalar() or 0

    unassigned_result = await db.execute(
        select(func.count(Ticket.id)).where(
            Ticket.assigned_agent_id.is_(None)
        )
    )
    unassigned_tickets = unassigned_result.scalar() or 0

    breached_result = await db.execute(
        select(func.count(Ticket.id)).where(
            Ticket.sla_breached.is_(True)
        )
    )
    sla_breached_tickets = breached_result.scalar() or 0

    online_result = await db.execute(
        select(func.count(Agent.id)).where(
            Agent.is_online.is_(True)
        )
    )
    agents_online = online_result.scalar() or 0

    return {
        "total_tickets": total_tickets,
        "tickets_by_status": tickets_by_status,
        "unassigned_tickets": unassigned_tickets,
        "sla_breached_tickets": sla_breached_tickets,
        "agents_online": agents_online,
    }


@router.get("/agent-performance")
async def agent_performance(
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_admin(current_user)

    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date must not be after end_date",
        )

    agents_result = await db.execute(
        select(Agent, User.full_name)
        .join(User, User.id == Agent.user_id)
        .order_by(User.full_name)
    )

    agent_rows = agents_result.all()
    reports = []

    for agent, agent_name in agent_rows:
        query = select(Ticket).where(
            Ticket.assigned_agent_id == agent.id
        )
        start, end = date_filters(start_date, end_date)
        query = apply_ticket_date_filter(query, start, end)

        tickets_result = await db.execute(query)
        tickets = tickets_result.scalars().all()

        resolved_tickets = [
            ticket for ticket in tickets
            if ticket.status in ("Resolved", "Closed")
            and ticket.resolved_at is not None
        ]

        first_response_times = [
            duration_minutes(ticket.created_at, ticket.first_response_at)
            for ticket in tickets
            if ticket.first_response_at is not None
        ]

        resolution_times = [
            duration_minutes(ticket.created_at, ticket.resolved_at)
            for ticket in resolved_tickets
        ]

        breached_count = sum(
            1 for ticket in tickets
            if ticket.sla_breached is True
        )

        sla_breach_percentage = (
            round(breached_count / len(tickets) * 100, 2)
            if tickets else 0
        )

        feedback_query = (
            select(Feedback.rating)
            .join(Ticket, Feedback.ticket_id == Ticket.id)
            .where(Ticket.assigned_agent_id == agent.id)
        )
        feedback_query = apply_ticket_date_filter(
            feedback_query, start, end
        )

        feedback_result = await db.execute(feedback_query)
        ratings = [
            rating for rating in feedback_result.scalars().all()
            if rating is not None
        ]

        reports.append({
            "agent_id": agent.id,
            "agent_name": agent_name,
            "tickets_resolved": len(resolved_tickets),
            "average_first_response_time_minutes": average(
                first_response_times
            ),
            "average_resolution_time_minutes": average(
                resolution_times
            ),
            "sla_breach_percentage": sla_breach_percentage,
            "average_rating": average(ratings),
        })

    return {
        "start_date": start_date,
        "end_date": end_date,
        "agents": reports,
    }


@router.get("/category-summary")
async def category_summary(
    start_date: date | None = None,
    end_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_admin(current_user)

    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date must not be after end_date",
        )

    start, end = date_filters(start_date, end_date)

    query = (
        select(Category.id, Category.name, Ticket)
        .outerjoin(Ticket, Ticket.category_id == Category.id)
    )

    # Apply the date range to tickets without removing categories
    # that have no matching tickets.
    if start:
        query = query.where(
            (Ticket.id.is_(None)) | (Ticket.created_at >= start)
        )
    if end:
        query = query.where(
            (Ticket.id.is_(None)) | (Ticket.created_at < end)
        )

    result = await db.execute(query)
    rows = result.all()

    grouped = {}

    for category_id, category_name, ticket in rows:
        if category_id not in grouped:
            grouped[category_id] = {
                "category_id": category_id,
                "category_name": category_name,
                "ticket_count": 0,
                "resolution_times": [],
            }

        if ticket is not None:
            grouped[category_id]["ticket_count"] += 1

            if (
                ticket.resolved_at is not None
                and ticket.created_at is not None
            ):
                minutes = duration_minutes(
                    ticket.created_at, ticket.resolved_at
                )
                if minutes is not None:
                    grouped[category_id]["resolution_times"].append(
                        minutes
                    )

    return {
        "start_date": start_date,
        "end_date": end_date,
        "categories": [
            {
                "category_id": item["category_id"],
                "category_name": item["category_name"],
                "ticket_count": item["ticket_count"],
                "average_resolution_time_minutes": average(
                    item["resolution_times"]
                ),
            }
            for item in grouped.values()
        ],
    }


@router.get("/sla-summary")
async def sla_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_admin(current_user)

    result = await db.execute(
        select(
            Ticket.priority,
            func.count(Ticket.id).label("total_tickets"),
            func.sum(
                func.IF(Ticket.sla_breached.is_(True), 1, 0)
            ).label("breached_tickets"),
        ).group_by(Ticket.priority)
    )

    summaries = []

    for row in result.all():
        total = row.total_tickets or 0
        breached = row.breached_tickets or 0

        summaries.append({
            "priority": row.priority,
            "total_tickets": total,
            "sla_breached": breached,
            "sla_met": total - breached,
        })

    return {"sla_summary": summaries}


@router.get("/customer-satisfaction")
async def customer_satisfaction(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    check_admin(current_user)

    result = await db.execute(
        select(
            func.count(Feedback.id),
            func.avg(Feedback.rating),
        )
    )
    total_feedback, avg_rating = result.one()

    distribution_result = await db.execute(
        select(
            Feedback.rating,
            func.count(Feedback.id),
        )
        .group_by(Feedback.rating)
        .order_by(Feedback.rating)
    )

    distribution = {
        rating: count
        for rating, count in distribution_result.all()
    }

    return {
        "total_feedback": total_feedback or 0,
        "average_rating": (
            round(float(avg_rating), 2)
            if avg_rating is not None
            else None
        ),
        "rating_distribution": {
            f"{stars}_star": distribution.get(stars, 0)
            for stars in range(1, 6)
        },
    }


