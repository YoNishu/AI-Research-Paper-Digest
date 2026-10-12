import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.services.arxiv_feed import poll_all_categories, sync_categories_from_yaml
from app.services.pipeline import process_pending_papers

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def poll_and_process():
    logger.info("Scheduler: starting poll and process cycle")
    try:
        await sync_categories_from_yaml()
        results = await poll_all_categories()
        total = sum(results.values())
        logger.info("Scheduler: found %d new papers across %d categories", total, len(results))
        processed = await process_pending_papers()
        logger.info("Scheduler: processed %d papers", processed)
    except Exception:
        logger.exception("Scheduler: poll_and_process failed")


def start_scheduler():
    scheduler.add_job(
        poll_and_process,
        trigger=IntervalTrigger(hours=settings.poll_interval_hours),
        id="poll_and_process",
        replace_existing=True,
    )
    # Catch-up job on startup
    scheduler.add_job(poll_and_process, id="startup_catchup", replace_existing=True)
    scheduler.start()
    logger.info("Scheduler started (interval: %dh)", settings.poll_interval_hours)


def stop_scheduler():
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")
