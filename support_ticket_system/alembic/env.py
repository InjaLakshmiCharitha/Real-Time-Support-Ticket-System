
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.database import Base, DATABASE_URL
from app.models import (
    User,
    Agent,
    Category,
    AgentCategory,
    SLAPolicy,
    Ticket,
    Message,
    TicketHistory,
    Notification,
    Attachment,
    Feedback,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Use the database URL from the project's .env file.
# Escape percent signs for Alembic's configuration parser.
config.set_main_option(
    "sqlalchemy.url",
    DATABASE_URL.replace("%", "%%"),
)

target_metadata = Base.metadata


def run_migrations_offline():
    """Run migrations without creating a database connection."""

    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """Run migrations using the database connection."""

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    """Create an asynchronous database connection."""

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

