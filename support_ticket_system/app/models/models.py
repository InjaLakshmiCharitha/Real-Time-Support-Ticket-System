
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# Common timestamp fields for every database table

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )


#  Users: Admin, Agent, Customer
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="Customer", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    agent_profile: Mapped["Agent | None"] = relationship(
        back_populates="user", uselist=False
    )

    customer_tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="customer",
        foreign_keys="Ticket.customer_id",
    )

    sent_messages: Mapped[list["Message"]] = relationship(
        back_populates="sender",
        foreign_keys="Message.sender_id",
    )

    notifications: Mapped[list["Notification"]] = relationship(
        back_populates="user"
    )

    feedback_given: Mapped[list["Feedback"]] = relationship(
        back_populates="customer",
        foreign_keys="Feedback.customer_id",
    )

    ticket_changes: Mapped[list["TicketHistory"]] = relationship(
        back_populates="changed_by",
        foreign_keys="TicketHistory.changed_by_id",
    )


# Agents
class Agent(Base, TimestampMixin):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False
    )

    is_online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_available: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    max_open_tickets: Mapped[int] = mapped_column(
        Integer, default=10, nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="agent_profile")

    assigned_tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="assigned_agent",
        foreign_keys="Ticket.assigned_agent_id",
    )

    categories: Mapped[list["AgentCategory"]] = relationship(
        back_populates="agent"
    )


# Ticket categories
class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    tickets: Mapped[list["Ticket"]] = relationship(back_populates="category")

    agents: Mapped[list["AgentCategory"]] = relationship(
        back_populates="category"
    )


# Agent-category assignment
class AgentCategory(Base, TimestampMixin):
    __tablename__ = "agent_categories"

    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id"), primary_key=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"), primary_key=True
    )

    agent: Mapped["Agent"] = relationship(back_populates="categories")
    category: Mapped["Category"] = relationship(back_populates="agents")


# SLA policies
class SLAPolicy(Base, TimestampMixin):
    __tablename__ = "sla_policies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    priority: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False
    )

    first_response_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    resolution_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False
    )


# Support tickets
class Ticket(Base, TimestampMixin):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    ticket_number: Mapped[str] = mapped_column(
        String(30), unique=True, index=True, nullable=False
    )

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"), nullable=False, index=True
    )

    assigned_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id"), nullable=True, index=True
    )

    subject: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    priority: Mapped[str] = mapped_column(
        String(20), default="Medium", nullable=False, index=True
    )

    status: Mapped[str] = mapped_column(
        String(30), default="Open", nullable=False, index=True
    )

    first_response_due: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    resolution_due: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    first_response_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    waiting_since: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    paused_seconds: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    sla_breached: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    sla_escalated: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    reopen_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    customer: Mapped["User"] = relationship(
        back_populates="customer_tickets",
        foreign_keys=[customer_id],
    )

    category: Mapped["Category"] = relationship(back_populates="tickets")

    assigned_agent: Mapped["Agent | None"] = relationship(
        back_populates="assigned_tickets",
        foreign_keys=[assigned_agent_id],
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
    )

    history: Mapped[list["TicketHistory"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
    )

    feedback: Mapped["Feedback | None"] = relationship(
        back_populates="ticket",
        uselist=False,
        cascade="all, delete-orphan",
    )

    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
    )


# Ticket chat messages
class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id"), nullable=False, index=True
    )

    sender_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)

    is_internal_note: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    ticket: Mapped["Ticket"] = relationship(back_populates="messages")

    sender: Mapped["User"] = relationship(
        back_populates="sent_messages",
        foreign_keys=[sender_id],
    )

    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="chat_message"
    )


# Ticket history and audit trail
class TicketHistory(Base, TimestampMixin):
    __tablename__ = "ticket_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id"), nullable=False, index=True
    )

    changed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    action: Mapped[str] = mapped_column(String(100), nullable=False)

    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    ticket: Mapped["Ticket"] = relationship(back_populates="history")

    changed_by: Mapped["User | None"] = relationship(
        back_populates="ticket_changes",
        foreign_keys=[changed_by_id],
    )


# User notifications
class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    ticket_id: Mapped[int | None] = mapped_column(
        ForeignKey("tickets.id"), nullable=True
    )

    title: Mapped[str] = mapped_column(String(150), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    notification_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )

    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="notifications")


# Attachments: images and PDF files
class Attachment(Base, TimestampMixin):
    __tablename__ = "attachments"
    __table_args__ = (
    CheckConstraint("file_size >= 0", name="check_attachment_file_size"),
)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id"), nullable=False, index=True
    )

    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id"), nullable=True
    )

    uploaded_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)

    ticket: Mapped["Ticket"] = relationship(back_populates="attachments")

    chat_message: Mapped["Message | None"] = relationship(
        back_populates="attachments"
    )


# Customer feedback
class Feedback(Base, TimestampMixin):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("tickets.id"), unique=True, nullable=False
    )

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )

    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    ticket: Mapped["Ticket"] = relationship(back_populates="feedback")

    customer: Mapped["User"] = relationship(
        back_populates="feedback_given",
        foreign_keys=[customer_id],
    )
