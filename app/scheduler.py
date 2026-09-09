"""Daily scheduler for e-paper downloads — 4 AM and 4 PM IST."""
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import structlog

logger = structlog.get_logger()

scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


async def download_job():
    """Download all e-papers and save to Firestore (temp dir only)."""
    from .ingestion.epaper import EpaperDownloader
    from .storage import save_epaper, init_firebase
    from .utils import now_ist
    from pathlib import Path
    import tempfile
    import shutil

    logger.info("scheduled_download_start")
    init_firebase()

    tmp_dir = tempfile.mkdtemp()
    ep = EpaperDownloader(output_dir=tmp_dir)
    try:
        results = await ep.download_all_today()
        today = now_ist()

        saved = 0
        for provider, data in results.items():
            if isinstance(data, dict) and data.get("status") == "ok":
                pdf_path = Path(data["path"])
                if pdf_path.exists():
                    pdf_bytes = pdf_path.read_bytes()
                    path_str = f"{today.strftime('%Y')}/{today.strftime('%m')}/{today.strftime('%d')}/{pdf_path.name}"
                    if save_epaper(provider, "deoghar", today, path_str, data.get("size_mb", 0), pdf_bytes=pdf_bytes):
                        saved += 1
            elif isinstance(data, dict):
                for city, r in data.items():
                    if isinstance(r, dict) and r.get("status") == "ok":
                        pdf_path = Path(r["path"])
                        if pdf_path.exists():
                            pdf_bytes = pdf_path.read_bytes()
                            path_str = f"{today.strftime('%Y')}/{today.strftime('%m')}/{today.strftime('%d')}/{pdf_path.name}"
                            if save_epaper(provider, city, today, path_str, r.get("size_mb", 0), r.get("pages", 0), pdf_bytes=pdf_bytes):
                                saved += 1

        logger.info("scheduled_download_complete", downloaded=len(results), saved=saved)

        # Delete records older than 3 months
        from .storage import delete_old_records
        delete_old_records(months=3)

    except Exception as e:
        logger.error("scheduled_download_failed", error=str(e))
    finally:
        await ep.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def start_scheduler():
    """Start the APScheduler with 4 AM and 4 PM IST triggers."""
    scheduler.add_job(
        download_job,
        CronTrigger(hour=4, minute=0),
        id="morning_download",
        name="Morning e-paper download",
    )
    scheduler.add_job(
        download_job,
        CronTrigger(hour=16, minute=0),
        id="evening_download",
        name="Evening e-paper download",
    )
    scheduler.start()
    logger.info("scheduler_started", jobs=[job.id for job in scheduler.get_jobs()])
