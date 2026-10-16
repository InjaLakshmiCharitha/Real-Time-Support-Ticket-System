
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    User,
    Agent,
    AgentCategory,
    Ticket,
    TicketHistory,

    Notification,
)

OPEN_STATUSES = [
    "Open",
    "Assigned",
    "In Progress",
    "Waiting on Customer",
]


async def assign_ticket(
    db: AsyncSession,
    ticket: Ticket,
    changed_by_id: int | None = None,
) -> bool:
    """
    Assign an unassigned ticket to the eligible agent
    with the fewest open tickets.

    Returns True if assigned, otherwise False.
    """

    # Do not change a ticket that is already assigned.
    if ticket.assigned_agent_id is not None:
        return True

    # Find active, online, available agents who support this category.
    result = await db.execute(
        select(Agent)
        .join(User, Agent.user_id == User.id)
        .join(
            AgentCategory,
            AgentCategory.agent_id == Agent.id,
        )
        .where(
            User.is_active.is_(True),
            Agent.is_online.is_(True),
            Agent.is_available.is_(True),
            AgentCategory.category_id == ticket.category_id,
        )
        .order_by(Agent.id)
    )

    agents = result.scalars().unique().all()

    eligible_agents = []

    for agent in agents:
        count_result = await db.execute(
            select(func.count(Ticket.id)).where(
                Ticket.assigned_agent_id == agent.id,
                Ticket.status.in_(OPEN_STATUSES),
            )
        )

        open_count = count_result.scalar_one()

        if open_count < agent.max_open_tickets:
            eligible_agents.append((agent, open_count))

    # Keep the ticket unassigned if nobody is eligible.
    if not eligible_agents:
        ticket.assigned_agent_id = None
        ticket.status = "Open"
        return False

    # Select the agent with the smallest workload.
    # Agent ID provides a stable tie-breaker.
    best_agent, _ = min(
        eligible_agents,
        key=lambda item: (item[1], item[0].id),
    )

    ticket.assigned_agent_id = best_agent.id
    ticket.status = "Assigned"

    db.add(
        TicketHistory(
            ticket_id=ticket.id,
            changed_by_id=changed_by_id,
            action="Ticket Assigned",
            old_value="Open",
            new_value="Assigned",
            details=(
                f"Ticket automatically assigned to agent"
                f"{best_agent.id}"
            ),
        )
    )

    # Save a notification for the assigned agent.
    db.add(
        Notification(
            user_id=best_agent.user_id,
            ticket_id=ticket.id,
            title="New Ticket Assigned",
            message=(
                f"Ticket {ticket.ticket_number} "
                "has been assigned to you."
            ),
            notification_type="ticket_assigned",
            is_read=False,
        )
    )

    return True



