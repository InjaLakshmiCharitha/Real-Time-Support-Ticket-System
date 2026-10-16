from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from pathlib import Path
from fastapi.responses import FileResponse

from app.database import engine
from app.routers.auth import router as auth_router
from app.routers.agents import router as agents_router
from app.routers.category import router as category_router
from app.routers.ticket import router as ticket_router
from app.routers.assignment import router as assignment_router
from app.websockets.chat import router as chat_router
from app.routers.message import router as message_router
from app.routers.notification import router as notification_router
from app.websockets.notification import router as notification_ws_router
from app.services.scheduler import start_scheduler, stop_scheduler
from app.routers.feedback import router as feedback_router
from app.routers.reports import router as reports_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the background SLA monitoring scheduler.
    start_scheduler()
    try:
        yield
    finally:
        # Stop the scheduler and close database connections.
        stop_scheduler()
    await engine.dispose()


app = FastAPI(
    title="Real-Time Support Ticket System",
    description=(
        "A support ticket backend with authentication, "
        "automatic assignment, real-time chat, and SLA tracking."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


app.include_router(auth_router)
app.include_router(agents_router)
app.include_router(category_router)
app.include_router(ticket_router)
app.include_router(assignment_router)
app.include_router(chat_router)
app.include_router(message_router)
app.include_router(notification_router)
app.include_router(notification_ws_router)
app.include_router(feedback_router)
app.include_router(reports_router)

@app.get("/chat-test", include_in_schema=False)
async def chat_test_page():
    html_file = (
        Path(__file__).resolve().parent.parent
        / "static"
        / "chat_test.html"
    )
    return FileResponse(html_file)


@app.get("/")
async def root():
    return {
        "message": "Real-Time Support Ticket System API is running"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/db-check")
async def database_check():
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        return {
            "status": "success",
            "database": "MySQL connected successfully"
        }

    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Database connection failed. Check your .env configuration."
        )
