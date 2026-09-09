"""E-paper PDF/image downloader for Hindi newspapers.

File naming: epaper_{provider}_{city}_{yymmdd}.pdf
Folder: data/epapers/{yyyy}/{mm}/{dd}/

Page images are downloaded then combined into one PDF per city.
"""
import httpx
import asyncio
import re
from io import BytesIO
from pathlib import Path
from datetime import datetime
from PIL import Image
import structlog

from app.utils import now_ist

logger = structlog.get_logger()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "hi,en-US;q=0.7,en;q=0.3",
}

JHARKHAND_JAGRAN_EDITIONS = {
    "ranchi": 212, "dhanbad": 139, "jamshedpur": 151, "deoghar": 177,
    "dumka": 227, "santhal": 226, "bokaro": 181, "hazaribag": 235,
    "giridih": 180, "palamu": 234, "lohardagga": 236, "koderma": 263,
    "ramgarh": 269, "godda": 305, "jamtara": 179, "chaibasa": 255,
    "ghatshila": 256, "garwha": 276,
}

LIVEHINDUSTAN_CITIES = {
    "sahibganj": "DNB_SAH", "godda": "DNB_GOD", "deoghar": "BHG_DEO",
    "dumka": "BHG_SNT", "dhanbad": "DNB_DNB", "jamshedpur": "JMD_JMD",
    "giridih": "DNB_GRD", "bokaro": "DNB_BKR", "ranchi": "BHG_HTM",
    "pakur": "DNB_PKR", "hazaribag": "BHG_HZB",
}

PRABHAT_KHABAR_CITIES = {
    "ranchi": {"group": "ranchi", "city": "ranchi-city"},
    "deoghar": {"group": "deoghar", "city": "deoghar-city"},
    "sahibganj": {"group": "deoghar", "city": "sahibganj"},
    "pakur": {"group": "deoghar", "city": "pakur"},
    "godda": {"group": "deoghar", "city": "godda"},
    "dhanbad": {"group": "dhanbad", "city": "dhanbad-city"},
    "dumka": {"group": "deoghar", "city": "dumka"},
    "bokaro": {"group": "bokaro", "city": "bokaro-city"},
    "jamshedpur": {"group": "jamshedpur", "city": "jamshedpur-city"},
    "hazaribag": {"group": "hazaribag", "city": "hazaribag-city"},
    "giridih": {"group": "giridih", "city": "giridih-city"},
}


def _date_dir(date: datetime) -> Path:
    return Path(date.strftime("%Y")) / date.strftime("%m") / date.strftime("%d")


def _date_suffix(date: datetime) -> str:
    return date.strftime("%y%m%d")


def _images_to_pdf(image_data_list: list[bytes], pdf_path: Path):
    """Combine multiple images into a single PDF file."""
    if not image_data_list:
        return
    images = []
    for data in image_data_list:
        img = Image.open(BytesIO(data))
        if img.mode != "RGB":
            img = img.convert("RGB")
        images.append(img)

    if images:
        images[0].save(pdf_path, "PDF", save_all=True, append_images=images[1:])
        for img in images:
            img.close()


class EpaperDownloader:
    def __init__(self, output_dir: str = "data/epapers"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.client = None

    async def _get_client(self):
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=30, follow_redirects=True, headers=HEADERS)
        return self.client

    def _pdf_path(self, provider: str, city: str, date: datetime) -> Path:
        folder = self.output_dir / _date_dir(date)
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"epaper_{provider}_{city}_{_date_suffix(date)}.pdf"

    async def download_indian_punch(self, date: datetime = None) -> dict:
        """Download Indian Punch e-paper PDF (already a PDF)."""
        date = date or now_ist()
        day, month_name = date.day, date.strftime("%b").upper()
        month_num = f"{date.month:02d}"

        pdf_url = (
            f"https://epaper.indianpunch.com/wp-content/uploads/"
            f"{date.year}/{month_num}/INDIAN-PUNCH-{day}-{month_name}-{date.year}.pdf"
        )
        try:
            client = await self._get_client()
            resp = await client.get(pdf_url)
            resp.raise_for_status()
            path = self._pdf_path("indian-punch", "deoghar", date)
            path.write_bytes(resp.content)
            size_mb = len(resp.content) / (1024 * 1024)
            logger.info("indian_punch_downloaded", path=str(path), size_mb=round(size_mb, 2))
            return {"status": "ok", "path": str(path), "size_mb": round(size_mb, 2)}
        except Exception as e:
            return {"status": "error", "error": str(e)[:100]}

    async def download_jagran(self, edition: str = "ranchi", date: datetime = None) -> dict:
        """Download Dainik Jagran front page and save as PDF."""
        date = date or now_ist()
        edition_id = JHARKHAND_JAGRAN_EDITIONS.get(edition.lower())
        if not edition_id:
            return {"status": "error", "error": f"Unknown edition: {edition}"}

        page_url = f"https://epaper.jagran.com/epaper/edition-today-{edition_id}-{edition}.html"
        try:
            client = await self._get_client()
            resp = await client.get(page_url)
            resp.raise_for_status()

            img_match = re.search(
                r'data-echo=["\']?(https://epaperapi\.jagran\.com/EpaperImages/[^"\'>\s]+)', resp.text
            )
            if not img_match:
                img_match = re.search(
                    r'(https://epaperapi\.jagran\.com/EpaperImages/[^"\'>\s]+\.png)', resp.text
                )
            if not img_match:
                return {"status": "error", "error": "No image found", "url": page_url}

            img_resp = await client.get(img_match.group(1))
            img_resp.raise_for_status()

            path = self._pdf_path("jagran", edition, date)
            _images_to_pdf([img_resp.content], path)
            size_kb = path.stat().st_size / 1024
            logger.info("jagran_downloaded", edition=edition, path=str(path), size_kb=round(size_kb, 1))
            return {"status": "ok", "path": str(path), "size_kb": round(size_kb, 1), "pages": 1}
        except Exception as e:
            return {"status": "error", "error": str(e)[:100]}

    async def _download_prabhat_khabar_image(self, city: str, page: int, date: datetime, client) -> bytes | None:
        """Download a single Prabhat Khabar page image, return bytes or None."""
        city_info = PRABHAT_KHABAR_CITIES.get(city.lower())
        if not city_info:
            return None

        date_str = date.strftime("%Y-%m-%d")
        page_url = f"https://epaper.prabhatkhabar.com/{city_info['group']}/{city_info['city']}/{date_str}/{page}"
        try:
            resp = await client.get(page_url)
            resp.raise_for_status()

            # Get full-size JPGs only (skip thumbnails)
            all_jpgs = re.findall(r'(https://cdnimg\.prabhatkhabar\.com/image/[^"\'>\s\\]+\.jpg)', resp.text)
            unique_jpgs = list(set(u for u in all_jpgs if "_thumb" not in u and "_thumbnail" not in u))
            if not unique_jpgs:
                return None

            # Match page number: _1_r1 or _01_r1 in filename
            page_pattern = f"_{page:02d}_" if page >= 10 else f"_{page}_"
            target_img = next((u for u in unique_jpgs if page_pattern in u), None)
            if not target_img:
                return None

            img_resp = await client.get(target_img)
            img_resp.raise_for_status()
            # Skip tiny images (thumbnails ~30KB vs full-size ~1MB)
            if len(img_resp.content) > 100_000:
                return img_resp.content
        except Exception:
            pass
        return None

    async def download_prabhat_khabar(self, city: str, max_pages: int = 20, date: datetime = None) -> dict:
        """Download all Prabhat Khabar pages for a city and combine into PDF."""
        date = date or now_ist()
        client = await self._get_client()
        images = []

        for pg in range(1, max_pages + 1):
            img_data = await self._download_prabhat_khabar_image(city, pg, date, client)
            if not img_data:
                break
            images.append(img_data)

        if not images:
            return {"status": "error", "error": "No pages downloaded", "city": city}

        path = self._pdf_path("prabhat-khabar", city, date)
        _images_to_pdf(images, path)
        size_mb = path.stat().st_size / (1024 * 1024)
        logger.info("prabhat_downloaded", city=city, pages=len(images), path=str(path), size_mb=round(size_mb, 2))
        return {"status": "ok", "path": str(path), "size_mb": round(size_mb, 2), "pages": len(images)}

    async def download_prabhat_khabar_all(self, cities: list[str] = None, date: datetime = None) -> dict:
        """Download Prabhat Khabar for multiple cities."""
        date = date or now_ist()
        if cities is None:
            cities = ["ranchi", "deoghar", "sahibganj", "pakur", "godda"]

        results = {}
        sem = asyncio.Semaphore(3)

        async def _dl(city):
            async with sem:
                results[city] = await self.download_prabhat_khabar(city, date=date)

        await asyncio.gather(*[_dl(c) for c in cities], return_exceptions=True)
        return results

    async def download_ranchi_express(self, date: datetime = None) -> dict:
        """Download Ranchi Express pages and combine into PDF."""
        date = date or now_ist()
        date_url = f"{date.strftime('%d')}/{date.strftime('%m')}/{date.year}-Ranchi"
        page_url = f"https://epaper.ranchiexpress.com/e-Paper?edate={date_url}"

        try:
            client = await self._get_client()
            resp = await client.get(page_url, timeout=60)
            resp.raise_for_status()

            img_paths = re.findall(r'src=["\']([^"\']*Epaper City[^"\']+\.jpg)["\']', resp.text)
            unique_paths = sorted(set(img_paths))
            if not unique_paths:
                return {"status": "error", "error": "No images found"}

            images = []
            for path in unique_paths:
                img_url = "https://epaper.ranchiexpress.com/" + path.replace(" ", "%20")
                img_resp = await client.get(img_url, timeout=60)
                if img_resp.status_code == 200 and len(img_resp.content) > 5000:
                    images.append(img_resp.content)

            if not images:
                return {"status": "error", "error": "No pages downloaded"}

            pdf_path = self._pdf_path("ranchi-express", "ranchi", date)
            _images_to_pdf(images, pdf_path)
            size_mb = pdf_path.stat().st_size / (1024 * 1024)
            logger.info("ranchi_express_downloaded", pages=len(images), path=str(pdf_path))
            return {"status": "ok", "path": str(pdf_path), "size_mb": round(size_mb, 2), "pages": len(images)}
        except Exception as e:
            return {"status": "error", "error": str(e)[:100]}

    async def download_santal_express(self, date: datetime = None) -> dict:
        """Download Santal Express e-paper pages and combine into PDF.

        API: /api/latest?page=1 returns edition list with fileDir.
        Page images: {fileDir}/{page}.webp
        """
        date = date or now_ist()
        date_str = date.strftime("%Y-%m-%d")
        client = await self._get_client()

        try:
            # Get today's edition from API
            api_resp = await client.get("https://epaper.santalexpress.com/api/latest?page=1", timeout=30)
            api_resp.raise_for_status()
            data = api_resp.json()

            today_edition = None
            for e in data.get("data", {}).get("editions", []):
                if e.get("editionDate") == date_str:
                    today_edition = e
                    break

            if not today_edition:
                return {"status": "error", "error": "No edition found for today"}

            file_dir = today_edition["fileDir"]
            base_url = f"https://epaper.santalexpress.com/{file_dir}"

            # Download pages until we get a 403
            images = []
            for pg in range(1, 25):
                img_url = f"{base_url}/{pg}.webp"
                img_resp = await client.get(img_url, timeout=30)
                if img_resp.status_code != 200:
                    break
                if len(img_resp.content) > 10_000:
                    images.append(img_resp.content)

            if not images:
                return {"status": "error", "error": "No pages downloaded"}

            pdf_path = self._pdf_path("santal-express", "ranchi", date)
            _images_to_pdf(images, pdf_path)
            size_mb = pdf_path.stat().st_size / (1024 * 1024)
            logger.info("santal_express_downloaded", pages=len(images), path=str(pdf_path), size_mb=round(size_mb, 2))
            return {"status": "ok", "path": str(pdf_path), "size_mb": round(size_mb, 2), "pages": len(images)}
        except Exception as e:
            return {"status": "error", "error": str(e)[:100]}

    async def download_livehindustan(self, city: str, max_pages: int = 20, date: datetime = None) -> dict:
        """Download Live Hindustan e-paper pages for a city and combine into PDF.

        Site loads all pages at once in a single request, so we only need page=1.
        Images are webp format; filtered by city-specific edition code.
        """
        date = date or now_ist()
        edition_code = LIVEHINDUSTAN_CITIES.get(city.lower())
        if not edition_code:
            return {"status": "error", "error": f"Unknown city: {city}"}

        client = await self._get_client()
        date_str = date.strftime("%Y-%m-%d")
        images = []

        # Site loads all pages in one request; page=1 gives us all images
        page_url = f"https://epaper.livehindustan.com/edition/{city}?date={date_str}&page=1"
        try:
            resp = await client.get(page_url, timeout=30)
            resp.raise_for_status()

            # Find high-res webp images for this edition code
            pattern = rf'(https://epaper\.livehindustan\.com/ep-img/prod/lh-epaper/\d+/\d+/\d+/pages/{edition_code}/[^"\'>\s]+_hr\.webp[^"\'>\s]*)'
            all_imgs = re.findall(pattern, resp.text)
            unique_imgs = sorted(set(img.split("?")[0] for img in all_imgs))

            for img_url in unique_imgs:
                img_resp = await client.get(img_url, timeout=30)
                if img_resp.status_code == 200 and len(img_resp.content) > 10_000:
                    images.append(img_resp.content)
        except Exception as e:
            return {"status": "error", "error": str(e)[:100]}

        if not images:
            return {"status": "error", "error": "No pages downloaded", "city": city}

        path = self._pdf_path("livehindustan", city, date)
        _images_to_pdf(images, path)
        size_mb = path.stat().st_size / (1024 * 1024)
        logger.info("livehindustan_downloaded", city=city, pages=len(images), path=str(path), size_mb=round(size_mb, 2))
        return {"status": "ok", "path": str(path), "size_mb": round(size_mb, 2), "pages": len(images)}

    async def download_livehindustan_all(self, cities: list[str] = None, date: datetime = None) -> dict:
        """Download Live Hindustan for multiple cities."""
        date = date or now_ist()
        if cities is None:
            cities = list(LIVEHINDUSTAN_CITIES.keys())

        results = {}
        sem = asyncio.Semaphore(3)

        async def _dl(city):
            async with sem:
                results[city] = await self.download_livehindustan(city, date=date)

        await asyncio.gather(*[_dl(c) for c in cities], return_exceptions=True)
        return results

    async def download_all_today(self, state: str = "jharkhand") -> dict:
        """Download today's e-papers from all sources."""
        today = now_ist()
        results = {}
        results["indian_punch"] = await self.download_indian_punch(today)
        results["prabhat_khabar"] = await self.download_prabhat_khabar_all(
            ["ranchi", "deoghar", "dumka", "sahibganj", "pakur"], today
        )
        results["ranchi_express"] = await self.download_ranchi_express(today)
        results["santal_express"] = await self.download_santal_express(today)
        results["livehindustan"] = await self.download_livehindustan_all(
            ["sahibganj", "godda", "deoghar", "dumka", "dhanbad", "jamshedpur"], today
        )
        logger.info("epaper_all_complete", results={k: v.get("status") for k, v in results.items()})
        return results

    async def close(self):
        if self.client:
            await self.client.aclose()
            self.client = None
