from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import AsyncSessionLocal
from app.services.sla_monitor import monitor_sla_breaches


scheduler = AsyncIOScheduler()


async def run_sla_monitor():
    """Run SLA monitoring using a fresh database session."""
    async with AsyncSessionLocal() as db:
        await monitor_sla_breaches(db)


def start_scheduler():
    """Start the background SLA monitoring job."""
    if scheduler.running:
        return

    scheduler.add_job(
        run_sla_monitor,
        trigger="interval",
        minutes=5,
        id="sla_monitor_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    scheduler.start()
    print("SLA monitoring scheduler started.")


def stop_scheduler():
    """Stop the background scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("SLA monitoring scheduler stopped.")


