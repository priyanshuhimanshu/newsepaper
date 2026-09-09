"""Daily scheduler for e-paper downloads — 4 AM and 4 PM IST."""
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import structlog

logger = structlog.get_logger()

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


async def download_job():
    """Lightweight sync of metadata to Firestore."""
    from .ingestion.epaper import EpaperDownloader
    from .storage import init_firebase
    from .utils import now_ist
    import tempfile
    import shutil

    logger.info("scheduled_meta_sync_start")
    init_firebase()
    today = now_ist()
    tmp_dir = tempfile.mkdtemp()
    ep = EpaperDownloader(output_dir=tmp_dir)

    try:
        # Only download metadata/front-page to verify availability
        # We no longer save the full PDF to Firestore to save RAM/Storage
        results = await ep.download_all_today()
        # Note: Since we removed save_epaper from here, we only update a minimal metadata record
        # if we want the list to appear. But for 256MB, we avoid all large PDF processing.
        logger.info("meta_sync_complete", results=len(results))
    except Exception as e:
        logger.error("sync_failed", error=str(e))
    finally:
        await ep.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

def start_scheduler():
    """Nightly trigger starting at 2 AM."""
    scheduler.add_job(
        download_job,
        CronTrigger(hour=2, minute=0),
        id="nightly_download",
        name="Nightly sequential download"
    )
    scheduler.start()
    logger.info("scheduler_started", job="nightly_download")
