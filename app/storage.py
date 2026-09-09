"""Firebase Firestore for e-paper storage (metadata + PDF content in chunks)."""
import os
import base64
import math
import firebase_admin
from firebase_admin import credentials, firestore
from pathlib import Path
from datetime import datetime
import structlog

logger = structlog.get_logger()

_db = None
CHUNK_SIZE = 500_000  # 500KB per chunk (well under 1MB limit)


def init_firebase(key_path: str = None):
    """Initialize Firebase Admin SDK for Firestore."""
    global _db
    if _db is not None:
        return

    # Support file path via GOOGLE_APPLICATION_CREDENTIALS
    key_path = key_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "app/news-storage-01-firebase-adminsdk-fbsvc-934ae7bccd.json")

    # Support direct JSON content via FIREBASE_CRED env var (for Render deployment)
    firebase_cred_json = os.environ.get("FIREBASE_CRED", "")

    if firebase_cred_json:
        import json
        import tempfile
        cred_dict = json.loads(firebase_cred_json)
        cred = credentials.Certificate(cred_dict)
    elif key_path and Path(key_path).exists():
        cred = credentials.Certificate(key_path)
    else:
        logger.warning("firebase_key_missing", path=key_path)
        return

    try:
        firebase_admin.initialize_app(cred)
        _db = firestore.client()
        logger.info("firebase_initialized")
    except Exception as e:
        logger.error("firebase_init_failed", error=str(e))


def save_epaper(provider: str, city: str, date: datetime, path: str, size_mb: float, pages: int = 0, pdf_bytes: bytes = None) -> bool:
    """Save e-paper metadata + PDF content (chunked) to Firestore."""
    if not _db:
        return False

    doc_id = f"{date.strftime('%Y-%m-%d')}_{provider}_{city}"
    try:
        # Save metadata (merge=True to update existing)
        _db.collection("epapers").document(doc_id).set({
            "provider": provider,
            "city": city,
            "date": date.strftime("%Y-%m-%d"),
            "date_yyyy": date.strftime("%Y"),
            "date_mm": date.strftime("%m"),
            "date_dd": date.strftime("%d"),
            "path": path,
            "filename": Path(path).name,
            "size_mb": size_mb,
            "pages": pages,
            "created_at": firestore.SERVER_TIMESTAMP,
        }, merge=True)

        # Delete old chunks before saving new ones
        old_chunks = _db.collection("pdf_chunks").where(filter=firestore.FieldFilter("doc_id", "==", doc_id)).stream()
        for chunk in old_chunks:
            chunk.reference.delete()

        # Save PDF content in chunks
        if pdf_bytes:
            total_chunks = math.ceil(len(pdf_bytes) / CHUNK_SIZE)
            for i in range(total_chunks):
                chunk = pdf_bytes[i * CHUNK_SIZE : (i + 1) * CHUNK_SIZE]
                chunk_b64 = base64.b64encode(chunk).decode("utf-8")
                _db.collection("pdf_chunks").document(f"{doc_id}_chunk_{i}").set({
                    "doc_id": doc_id,
                    "chunk_index": i,
                    "total_chunks": total_chunks,
                    "data": chunk_b64,
                })
            logger.info("firestore_saved_with_chunks", doc_id=doc_id, chunks=total_chunks)

        logger.info("firestore_saved", doc_id=doc_id)
        return True
    except Exception as e:
        logger.error("firestore_save_failed", doc_id=doc_id, error=str(e))
        return False


def get_pdf_base64(doc_id: str) -> str | None:
    """Get PDF content from Firestore by reassembling chunks."""
    if not _db:
        return None
    try:
        # Try with original doc_id first
        first = _db.collection("pdf_chunks").document(f"{doc_id}_chunk_0").get()
        
        # If not found, try normalizing dashes to underscores
        if not first.exists:
            normalized = doc_id.replace("-", "_")
            first = _db.collection("pdf_chunks").document(f"{normalized}_chunk_0").get()
            doc_id = normalized
        
        if not first.exists:
            return None

        first_data = first.to_dict()
        total_chunks = first_data["total_chunks"]
        chunks = [base64.b64decode(first_data["data"])]

        for i in range(1, total_chunks):
            chunk_doc = _db.collection("pdf_chunks").document(f"{doc_id}_chunk_{i}").get()
            if chunk_doc.exists:
                chunks.append(base64.b64decode(chunk_doc.to_dict()["data"]))

        return base64.b64encode(b"".join(chunks)).decode("utf-8")
    except Exception as e:
        logger.error("firestore_get_pdf_failed", doc_id=doc_id, error=str(e))
    return None


def get_doc_by_filename(filename: str) -> dict | None:
    """Find an e-paper document by its filename."""
    if not _db:
        return None
    try:
        docs = _db.collection("epapers").where(filter=firestore.FieldFilter("filename", "==", filename)).limit(1).stream()
        for doc in docs:
            data = doc.to_dict()
            return {"id": doc.id, **data}
    except Exception as e:
        logger.error("firestore_get_by_filename_failed", filename=filename, error=str(e))
    return None


def get_epapers(date: str = None) -> list[dict]:
    """Get e-paper metadata from Firestore."""
    if not _db:
        return []

    try:
        query = _db.collection("epapers")
        if date:
            query = query.where(filter=firestore.FieldFilter("date", "==", date))
        docs = query.order_by("date", direction=firestore.Query.DESCENDING).limit(50).stream()
        results = []
        for doc in docs:
            data = doc.to_dict()
            for k, v in data.items():
                if hasattr(v, "isoformat"):
                    data[k] = v.isoformat()
            results.append({"id": doc.id, **data})
        return results
    except Exception as e:
        logger.error("firestore_list_failed", error=str(e))
        return []


def get_latest() -> list[dict]:
    """Get today's e-papers from Firestore."""
    today = datetime.now().strftime("%Y-%m-%d")
    return get_epapers(today)


def delete_old_records(months: int = 3):
    """Delete e-paper records older than specified months."""
    if not _db:
        return 0

    try:
        from dateutil.relativedelta import relativedelta
        cutoff = (datetime.now() - relativedelta(months=months)).strftime("%Y-%m-%d")
    except ImportError:
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")

    try:
        docs = _db.collection("epapers").where(filter=firestore.FieldFilter("date", "<", cutoff)).stream()
        deleted = 0
        for doc in docs:
            doc.reference.delete()
            # Delete associated chunks
            chunks = _db.collection("pdf_chunks").where(filter=firestore.FieldFilter("doc_id", "==", doc.id)).stream()
            for chunk in chunks:
                chunk.reference.delete()
            deleted += 1
        if deleted:
            logger.info("old_records_deleted", count=deleted, cutoff=cutoff)
        return deleted
    except Exception as e:
        logger.error("delete_old_records_failed", error=str(e))
        return 0
