from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Agent, Ticket
from app.services.notification_manager import notification_manager


OPEN_STATUSES = [
    "Open",
    "Assigned",
    "In Progress",
    "Waiting on Customer",
]


async def broadcast_open_ticket_counts(db: AsyncSession):
    """
    Send updated open-ticket counts to connected Agents and Admins.
    """

    connected_user_ids = list(
        notification_manager.active_connections.keys()
    )

    if not connected_user_ids:
        return

    # Fetch connected, active users in one query.
    users_result = await db.execute(
        select(User).where(
            User.id.in_(connected_user_ids),
            User.is_active.is_(True),
        )
    )
    users = users_result.scalars().all()

    # Calculate the total open-ticket count once for Admins.
    admin_count = None

    if any(user.role == "Admin" for user in users):
        count_result = await db.execute(
            select(func.count(Ticket.id)).where(
                Ticket.status.in_(OPEN_STATUSES)
            )
        )
        admin_count = count_result.scalar_one()

    for user in users:
        if user.role == "Admin":
            open_count = admin_count

        elif user.role == "Agent":
            agent_result = await db.execute(
                select(Agent).where(Agent.user_id == user.id)
            )
            agent = agent_result.scalar_one_or_none()

            if agent is None:
                continue

            count_result = await db.execute(
                select(func.count(Ticket.id)).where(
                    Ticket.assigned_agent_id == agent.id,
                    Ticket.status.in_(OPEN_STATUSES),
                )
            )
            open_count = count_result.scalar_one()

        else:
            # Customers do not receive agent/admin ticket counts.
            continue

        await notification_manager.send_to_user(
            user.id,
            {
                "type": "open_ticket_count",
                "count": open_count,
            },
        )

