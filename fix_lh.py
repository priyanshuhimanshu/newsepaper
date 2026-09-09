import asyncio
from app.storage import init_firebase, save_epaper
from app.ingestion.epaper import EpaperDownloader
from app.utils import now_ist
from pathlib import Path
import structlog

logger = structlog.get_logger()

async def run():
    init_firebase()
    today = now_ist()
    ep = EpaperDownloader()
    cities = ["sahibganj", "pakur", "dumka"]
    for city in cities:
        logger.info("downloading_livehindustan", city=city)
        res = await ep.download_livehindustan(city, date=today)
        if res and res.get("status") == "ok":
            pdf_path = Path(res["path"])
            if pdf_path.exists():
                pdf_bytes = pdf_path.read_bytes()
                path_str = f"{today.strftime("%Y")}/{today.strftime("%m")}/{today.strftime("%d")}/{pdf_path.name}"
                save_epaper("livehindustan", city, today, path_str, res.get("size_mb", 0), res.get("pages", 0), pdf_bytes)
                logger.info("saved_livehindustan", city=city)
    await ep.close()

if __name__ == "__main__":
    asyncio.run(run())