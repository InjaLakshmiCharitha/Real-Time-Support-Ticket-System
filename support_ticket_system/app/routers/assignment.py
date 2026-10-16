from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth.security import get_current_user
from app.models import (
    User,
    Agent,
    AgentCategory,
    Ticket,
    TicketHistory,
    Notification,
)
from app.services.ticket_count_manager import broadcast_open_ticket_counts

router = APIRouter(tags=["Ticket Assignment"])

OPEN_STATUSES = [
    "Open",
    "Assigned",
    "In Progress",
    "Waiting on Customer",
]


class AssignTicketRequest(BaseModel):
    agent_id: int = Field(gt=0)


@router.put("/tickets/{ticket_id}/assign")
async def assign_or_reassign_ticket(
    ticket_id: int,
    data: AssignTicketRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=403,
            detail="Only Admin can assign or reassign tickets",
        )

    ticket = await db.get(Ticket, ticket_id)

    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if ticket.status in ["Resolved", "Closed"]:
        raise HTTPException(
            status_code=409,
            detail="Resolved or closed tickets cannot be reassigned",
        )

    # Find the target agent and check that their account is active.
    result = await db.execute(
        select(Agent)
        .join(User, Agent.user_id == User.id)
        .where(
            Agent.id == data.agent_id,
            User.is_active.is_(True),
        )
    )
    new_agent = result.scalar_one_or_none()

    if new_agent is None:
        raise HTTPException(
            status_code=404,
            detail="Active agent not found",
        )

    # The agent must handle this ticket's category.
    expertise_result = await db.execute(
        select(AgentCategory).where(
            AgentCategory.agent_id == new_agent.id,
            AgentCategory.category_id == ticket.category_id,
        )
    )

    if expertise_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=400,
            detail="This agent does not handle the ticket category",
        )

    old_agent_id = ticket.assigned_agent_id

    if old_agent_id == new_agent.id:
        return {
            "message": "Ticket is already assigned to this agent",
            "ticket_id": ticket.id,
            "assigned_agent_id": new_agent.id,
        }

    # Check the target agent's current open-ticket workload.
    count_result = await db.execute(
        select(func.count(Ticket.id)).where(
            Ticket.assigned_agent_id == new_agent.id,
            Ticket.status.in_(OPEN_STATUSES),
            Ticket.id != ticket.id,
        )
    )
    open_count = count_result.scalar_one()

    if open_count >= new_agent.max_open_tickets:
        raise HTTPException(
            status_code=409,
            detail="Agent has reached the maximum open-ticket limit",
        )

    old_agent = None

    if old_agent_id is not None:
        old_agent = await db.get(Agent, old_agent_id)

    # Assign the ticket to the new agent.
    ticket.assigned_agent_id = new_agent.id
    ticket.status = "Assigned"

    # Record the assignment/reassignment in ticket history.
    db.add(
        TicketHistory(
            ticket_id=ticket.id,
            changed_by_id=current_user.id,
            action="Ticket Reassigned" if old_agent_id else "Ticket Assigned",
            old_value=str(old_agent_id) if old_agent_id else None,
            new_value=str(new_agent.id),
            details="Ticket manually assigned by Admin",
        )
    )

    # Notify the previous agent, if there was one.
    if old_agent is not None:
        db.add(
            Notification(
                user_id=old_agent.user_id,
                ticket_id=ticket.id,
                title="Ticket Reassigned",
                message=(
                    f"Ticket {ticket.ticket_number} "
                    "has been reassigned to another agent."
                ),
                notification_type="ticket_reassigned",
                is_read=False,
            )
        )

    # Notify the new agent.
    db.add(
        Notification(
            user_id=new_agent.user_id,
            ticket_id=ticket.id,
            title="Ticket Assigned",
            message=(
                f"Ticket {ticket.ticket_number} "
                "has been assigned to you."
            ),
            notification_type="ticket_assigned",
            is_read=False,
        )
    )

    await db.commit()
    await db.refresh(ticket)
    await broadcast_open_ticket_counts(db)
    return {
        "message": "Ticket assigned successfully",
        "ticket_id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "previous_agent_id": old_agent_id,
        "assigned_agent_id": ticket.assigned_agent_id,
        "status": ticket.status,
    }



@router.get("/agents/me/tickets")
async def get_my_assigned_tickets(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Agent":
        raise HTTPException(
            status_code=403,
            detail="Only agents can view their assigned tickets",
        )

    result = await db.execute(
        select(Agent).where(Agent.user_id == current_user.id)
    )
    agent = result.scalar_one_or_none()

    if agent is None:
        raise HTTPException(
            status_code=404,
            detail="Agent profile not found",
        )

    tickets_result = await db.execute(
        select(Ticket)
        .where(Ticket.assigned_agent_id == agent.id)
        .order_by(Ticket.created_at.desc())
        .offset(skip)
        .limit(limit)
    )

    tickets = tickets_result.scalars().all()

    count_result = await db.execute(
      select(func.count(Ticket.id)).where(
         Ticket.assigned_agent_id == agent.id
      )
    )
    total_tickets = count_result.scalar_one()

    return {
        "agent_id": agent.id,
        "total_tickets": len(tickets),
        "tickets": [
            {
                "id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "subject": ticket.subject,
                "description": ticket.description,
                "category_id": ticket.category_id,
                "priority": ticket.priority,
                "status": ticket.status,
                "assigned_agent_id": ticket.assigned_agent_id,
                "created_at": ticket.created_at,
            }
            for ticket in tickets
        ],
    }
