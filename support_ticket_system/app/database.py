import os

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

# Load environment variables from the .env file
load_dotenv()

# Read the asynchronous MySQL connection URL
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is missing. Please configure it in your .env file."
    )

# Create the asynchronous database engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

# Create a reusable asynchronous session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Base class for all SQLAlchemy models
class Base(DeclarativeBase):
    pass


# Dependency used by API routes to access the database
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
