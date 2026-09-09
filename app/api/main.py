from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from pathlib import Path
import base64
from datetime import datetime

app = FastAPI(title="E-Paper Download API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "healthy", "version": "1.0.0"}


class EncodeRequest(BaseModel):
    path: str  # relative path like "2026/09/09/epaper_indian-punch_deoghar_260909.pdf"


class EncodeResponse(BaseModel):
    filename: str
    size_mb: float
    base64: str


@app.post("/api/encode", response_model=EncodeResponse)
async def encode_pdf(req: EncodeRequest):
    """Get PDF from Firestore and return as base64."""
    from app.storage import init_firebase, get_pdf_base64
    init_firebase()

    # Build doc_id from path: 2026/09/09/epaper_indian-punch_deoghar_260909.pdf -> 2026-09-09_indian-punch_deoghar
    parts = Path(req.path).stem.split("_")
    if len(parts) < 3:
        raise HTTPException(status_code=400, detail="Invalid path format")
    date_str = f"{parts[0][:4]}-{parts[0][4:6]}-{parts[0][6:8]}" if len(parts[0]) == 8 else parts[0]
    doc_id = f"{date_str}_{parts[1]}_{parts[2]}"

    pdf_b64 = get_pdf_base64(doc_id)
    if not pdf_b64:
        raise HTTPException(status_code=404, detail="PDF not found in Firestore")

    data = base64.b64decode(pdf_b64)
    return EncodeResponse(
        filename=Path(req.path).name,
        size_mb=round(len(data) / 1048576, 2),
        base64=pdf_b64,
    )


class DecodeRequest(BaseModel):
    base64: str
    filename: str  # e.g. "epaper_indian-punch_deoghar_260909.pdf"
    provider: str = ""
    city: str = ""


class DecodeResponse(BaseModel):
    doc_id: str
    size_mb: float


@app.post("/api/decode", response_model=DecodeResponse)
async def decode_pdf(req: DecodeRequest):
    """Decode base64 and save to Firestore."""
    from app.storage import init_firebase, save_epaper
    init_firebase()

    data = base64.b64decode(req.base64)

    # Extract provider and city from filename if not provided
    parts = Path(req.filename).stem.split("_")
    provider = req.provider or (parts[1] if len(parts) > 1 else "unknown")
    city = req.city or (parts[2] if len(parts) > 2 else "unknown")

    now = datetime.now()
    path = f"{now.strftime('%Y')}/{now.strftime('%m')}/{now.strftime('%d')}/{req.filename}"

    save_epaper(
        provider=provider,
        city=city,
        date=now,
        path=path,
        size_mb=round(len(data) / 1048576, 2),
        pages=1,
        pdf_bytes=data,
    )

    doc_id = f"{now.strftime('%Y-%m-%d')}_{provider}_{city}"
    return DecodeResponse(
        doc_id=doc_id,
        size_mb=round(len(data) / 1048576, 2),
    )
