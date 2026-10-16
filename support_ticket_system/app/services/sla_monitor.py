from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Ticket, TicketHistory, Notification
from app.services.notification_manager import notification_manager


INACTIVE_SLA_STATUSES = ["Resolved", "Closed"]
ESCALATION_DELAY_MINUTES = 30
AUTO_CLOSE_AFTER_DAYS = 7

# Priority order from lowest to highest.
PRIORITY_LEVELS = ["Low", "Medium", "High", "Urgent"]


def get_utc_now():
    """Return the current UTC time as a naive datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def monitor_sla_breaches(db: AsyncSession):
    """
    Monitor SLA deadlines, notify administrators, escalate eligible
    breached tickets, and automatically close resolved tickets
    after seven days.
    """

    now = get_utc_now()
    notifications_to_send = []

    try:
        admin_result = await db.execute(
            select(User).where(
                User.role == "Admin",
                User.is_active.is_(True),
            )
        )
        admins = admin_result.scalars().all()

        # Detect new SLA breaches.
        ticket_result = await db.execute(
            select(Ticket).where(
                Ticket.status.notin_(INACTIVE_SLA_STATUSES),
                Ticket.sla_breached.is_(False),
            )
        )
        tickets = ticket_result.scalars().all()

        for ticket in tickets:
            # Pause SLA monitoring while waiting for the customer.
            if ticket.waiting_since is not None:
                continue

            paused_duration = timedelta(
                seconds=ticket.paused_seconds or 0
            )

            first_response_breached = (
                ticket.first_response_at is None
                and ticket.first_response_due is not None
                and ticket.first_response_due + paused_duration <= now
            )

            resolution_breached = (
                ticket.resolution_due is not None
                and ticket.resolution_due + paused_duration <= now
            )

            if not (
                first_response_breached or resolution_breached
            ):
                continue

            ticket.sla_breached = True

            breach_reason = (
                "First response deadline exceeded"
                if first_response_breached
                else "Resolution deadline exceeded"
            )

            db.add(
                TicketHistory(
                    ticket_id=ticket.id,
                    changed_by_id=None,
                    action="SLA Breached",
                    old_value="Within SLA",
                    new_value="SLA Breached",
                    details=breach_reason,
                )
            )

            # Notify administrators of the breach, including Urgent tickets.
            for admin in admins:
                notification = Notification(
                    user_id=admin.id,
                    ticket_id=ticket.id,
                    title="Ticket SLA Breached",
                    message=(
                        f"Ticket {ticket.ticket_number}: "
                        f"{breach_reason}."
                    ),
                    notification_type="sla_breached",
                    is_read=False,
                )
                db.add(notification)
                notifications_to_send.append(
                    (admin.id, notification)
                )

        # Escalate tickets after the configured delay.
        escalated_result = await db.execute(
            select(Ticket).where(
                Ticket.sla_breached.is_(True),
                Ticket.sla_escalated.is_(False),
                Ticket.status.notin_(INACTIVE_SLA_STATUSES),
                Ticket.waiting_since.is_(None),
            )
        )
        breached_tickets = escalated_result.scalars().all()

        for ticket in breached_tickets:
            history_result = await db.execute(
                select(TicketHistory)
                .where(
                    TicketHistory.ticket_id == ticket.id,
                    TicketHistory.action == "SLA Breached",
                )
                .order_by(TicketHistory.created_at.asc())
                .limit(1)
            )
            breach_history = history_result.scalar_one_or_none()

            if breach_history is None:
                continue

            escalation_time = (
                breach_history.created_at
                + timedelta(minutes=ESCALATION_DELAY_MINUTES)
            )

            if escalation_time > now:
                continue

            # Mark the breach as processed even for Urgent tickets,
            # so the scheduler does not repeat the same notification.
            ticket.sla_escalated = True

            old_priority = ticket.priority

            if old_priority != "Urgent" and old_priority in PRIORITY_LEVELS:
                new_priority = PRIORITY_LEVELS[
                    PRIORITY_LEVELS.index(old_priority) + 1
                ]
                ticket.priority = new_priority

                db.add(
                    TicketHistory(
                        ticket_id=ticket.id,
                        changed_by_id=None,
                        action="Priority Escalated",
                        old_value=old_priority,
                        new_value=new_priority,
                        details="Priority increased after an SLA breach.",
                    )
                )

            db.add(
                TicketHistory(
                    ticket_id=ticket.id,
                    changed_by_id=None,
                    action="SLA Escalated",
                    old_value="Not Escalated",
                    new_value="Escalated",
                    details=(
                        "SLA escalation processed after the "
                        "configured delay."
                    ),
                )
            )

            for admin in admins:
                message = (
                    f"Ticket {ticket.ticket_number} breached its SLA."
                    if old_priority == "Urgent"
                    else (
                        f"Ticket {ticket.ticket_number} priority was "
                        f"raised from {old_priority} to {ticket.priority} "
                        "after an SLA breach."
                    )
                )

                notification = Notification(
                    user_id=admin.id,
                    ticket_id=ticket.id,
                    title=(
                        "Urgent Ticket SLA Breached"
                        if old_priority == "Urgent"
                        else "Ticket Priority Escalated"
                    ),
                    message=message,
                    notification_type="sla_escalated",
                    is_read=False,
                )
                db.add(notification)
                notifications_to_send.append(
                    (admin.id, notification)
                )

        # Automatically close tickets that have remained resolved
        # for seven days.
        close_before = now - timedelta(days=AUTO_CLOSE_AFTER_DAYS)

        resolved_result = await db.execute(
            select(Ticket).where(
                Ticket.status == "Resolved",
                Ticket.resolved_at.is_not(None),
                Ticket.resolved_at <= close_before,
            )
        )
        resolved_tickets = resolved_result.scalars().all()

        for ticket in resolved_tickets:
            old_status = ticket.status
            ticket.status = "Closed"
            ticket.closed_at = now

            db.add(
                TicketHistory(
                    ticket_id=ticket.id,
                    changed_by_id=None,
                    action="Ticket Auto-Closed",
                    old_value=old_status,
                    new_value="Closed",
                    details=(
                        "Ticket automatically closed after "
                        "remaining resolved for seven days."
                    ),
                )
            )

            recipients = {ticket.customer_id}
            recipients.update(admin.id for admin in admins)

            for user_id in recipients:
                notification = Notification(
                    user_id=user_id,
                    ticket_id=ticket.id,
                    title="Ticket Automatically Closed",
                    message=(
                        f"Ticket {ticket.ticket_number} was "
                        "automatically closed after seven days."
                    ),
                    notification_type="ticket_auto_closed",
                    is_read=False,
                )
                db.add(notification)
                notifications_to_send.append(
                    (user_id, notification)
                )

        # Commit all changes before broadcasting notifications.
        await db.commit()

        for user_id, notification in notifications_to_send:
            await db.refresh(notification)

            await notification_manager.send_notification(
                user_id,
                {
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
                },
            )

    except Exception:
        await db.rollback()
        raise


