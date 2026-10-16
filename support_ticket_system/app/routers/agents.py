from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import get_current_user, require_roles, hash_password
from app.database import get_db
from app.models import Agent, User, Ticket, Notification
from app.schemas.agent import AgentCreate, AgentResponse, AgentUpdate
from app.services.assignment import assign_ticket
from app.services.notification_manager import notification_manager
from app.services.ticket_count_manager import broadcast_open_ticket_counts


router = APIRouter(prefix="/agents", tags=["Agents"])


# Admin can create an agent profile for an existing Agent-role user.
@router.post(
    "",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent(
    data: AgentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("Admin")),
):
    # Check whether the email already exists.
    result = await db.execute(
        select(User).where(User.email == data.email.lower())
    )
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered",
        )

    try:
        # Create the Agent user account.
        user = User(
            full_name=data.name,
            email=data.email.lower(),
            hashed_password=hash_password(data.password),
            role="Agent",
            is_active=True,
        )
        db.add(user)
        await db.flush()

        # Create the Agent profile.
        agent = Agent(
            user_id=user.id,
            max_open_tickets=data.max_open_tickets,
            is_online=False,
            is_available=True,
        )
        db.add(agent)

        await db.commit()
        await db.refresh(agent)

    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Could not create agent. Check whether the email or profile already exists.",
        )

    return agent


# Admin can list all agent profiles.
@router.get("", response_model=list[AgentResponse])
async def list_agents(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("Admin")),
):
    result = await db.execute(
        select(Agent)
        .order_by(Agent.id)
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()



# Admin can update an agent profile.
@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: int,
    data: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("Admin")),
):
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id)
    )
    agent = result.scalar_one_or_none()

    if agent is None:
        raise HTTPException(
            status_code=404,
            detail="Agent not found",
        )

    changes = data.model_dump(exclude_unset=True)

    for field, value in changes.items():
        setattr(agent, field, value)

    await db.commit()
    await db.refresh(agent)

    await broadcast_open_ticket_counts(db)

    return agent



# An agent can change their own online/availability status.
@router.put("/me/availability", response_model=AgentResponse)
async def update_my_availability(
    is_online: bool,
    is_available: bool,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("Agent")),
):
    result = await db.execute(
        select(Agent).where(Agent.user_id == current_user.id)
    )
    agent = result.scalar_one_or_none()

    if agent is None:
        raise HTTPException(
            status_code=404,
            detail="Agent profile not found",
        )

    try:
        agent.is_online = is_online
        agent.is_available = is_available

        await db.commit()
        await db.refresh(agent)

        # Assign matching open tickets when the agent is available.
        if agent.is_online and agent.is_available:
            from app.models import AgentCategory

            ticket_result = await db.execute(
                select(Ticket)
                .join(
                    AgentCategory,
                    AgentCategory.category_id == Ticket.category_id,
                )
                .where(
                    AgentCategory.agent_id == agent.id,
                    Ticket.assigned_agent_id.is_(None),
                    Ticket.status == "Open",
                )
                .order_by(
                    Ticket.created_at.asc(),
                    Ticket.id.asc(),
                )
            )

            unassigned_tickets = (
                ticket_result.scalars().unique().all()
            )

            for ticket in unassigned_tickets:
                await assign_ticket(
                    db=db,
                    ticket=ticket,
                    changed_by_id=current_user.id,
                )

            # Save ticket assignments and their notifications.
            await db.commit()

        # Send open-ticket count updates after database changes.
        await broadcast_open_ticket_counts(db)

        await db.refresh(agent)
        return agent

    except Exception:
        await db.rollback()
        raise




  
