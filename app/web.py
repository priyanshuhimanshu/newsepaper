"""E-Paper Downloader — lightweight FastAPI + vanilla HTML."""
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
from datetime import datetime
from .storage import init_firebase, get_latest, get_epapers

app = FastAPI(title="E-Paper")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROVIDERS = {
    "indian-punch": "Indian Punch", "prabhat-khabar": "Prabhat Khabar",
    "ranchi-express": "Ranchi Express", "santal-express": "Santal Express",
    "livehindustan": "Live Hindustan",
}
CITIES = {
    "ranchi": "रांची", "deoghar": "देवघर", "dumka": "दुमका", "sahibganj": "साहिबगंज",
    "pakur": "पाकुड़", "godda": "गोड्डा", "dhanbad": "धनबाद", "jamshedpur": "जमशेदपुर",
}


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE


@app.get("/api/health")
async def health():
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/api/today")
async def today():
    now = datetime.now()
    init_firebase()
    firestore_files = get_latest()
    return JSONResponse({"date": now.strftime("%Y-%m-%d"), "files": firestore_files})


@app.get("/api/history")
async def history(date: str = None):
    """Get e-paper history from Firestore."""
    init_firebase()
    files = get_epapers(date)
    return JSONResponse({"files": files})


@app.get("/api/lookup")
async def lookup(date: str, provider: str, city: str):
    """Download e-paper directly from web source (no storage)."""
    from datetime import datetime
    from fastapi.responses import Response
    from .ingestion.epaper import EpaperDownloader
    from pathlib import Path
    import tempfile
    import shutil
    import structlog

    logger = structlog.get_logger()

    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return JSONResponse({"found": False, "error": "Invalid date format. Use YYYY-MM-DD"})

    if provider in ["prabhat-khabar", "livehindustan"] and not city:
        return JSONResponse({"found": False, "error": f"City is required for {provider}"})

    logger.info("past_download_start", provider=provider, city=city, date=date)

    tmp_dir = tempfile.mkdtemp()
    dl = EpaperDownloader(output_dir=tmp_dir)
    result = None
    data = None
    filename = None

    try:
        if provider == "indian-punch":
            result = await dl.download_indian_punch(dt)
        elif provider == "prabhat-khabar":
            result = await dl.download_prabhat_khabar(city, date=dt)
        elif provider == "ranchi-express":
            result = await dl.download_ranchi_express(dt)
        elif provider == "santal-express":
            result = await dl.download_santal_express(dt)
        elif provider == "livehindustan":
            result = await dl.download_livehindustan(city, date=dt)
        else:
            return JSONResponse({"found": False, "error": f"Unknown newspaper: {provider}"})

        if result and result.get("status") == "ok":
            pdf_path = Path(result["path"])
            if pdf_path.exists():
                data = pdf_path.read_bytes()
                filename = pdf_path.name
    except Exception as e:
        logger.error("past_download_error", provider=provider, city=city, error=str(e)[:100])
        return JSONResponse({"found": False, "error": f"Download error: {str(e)[:150]}"})
    finally:
        await dl.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if data:
        logger.info("past_download_complete", provider=provider, city=city, size_mb=round(len(data)/1048576, 2))
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    
    error_msg = result.get("error", "") if result else "No response from source"
    if "No pages downloaded" in error_msg or "No image found" in error_msg:
        error_msg = f"{provider} edition not available for {date}. The newspaper may not publish on this date."
    elif "timeout" in error_msg.lower() or "connect" in error_msg.lower():
        error_msg = "Connection timed out. The newspaper website may be slow or unavailable."
    elif "404" in error_msg or "Not Found" in error_msg:
        error_msg = f"E-paper not found for {date}. It may not be published yet or doesn't exist for this date."
    elif "403" in error_msg or "Forbidden" in error_msg:
        error_msg = "Access denied by the newspaper website. Please try again later."
    
    logger.warn("past_download_failed", provider=provider, city=city, error=error_msg[:100])
    return JSONResponse({"found": False, "error": error_msg or "Download failed. Please try again."})


@app.get("/download/{path:path}")
async def download(path: str):
    """Download PDF from Firestore."""
    import base64
    from .storage import init_firebase, get_pdf_base64
    init_firebase()

    # Parse path: 2026/09/09/epaper_indian-punch_deoghar_260909.pdf
    parts = Path(path).parts  # ('2026', '09', '09', 'epaper_indian-punch_deoghar_260909.pdf')
    if len(parts) < 4:
        return JSONResponse({"error": "invalid path"}, 400)

    date_str = f"{parts[0]}-{parts[1]}-{parts[2]}"
    stem = Path(path).stem  # epaper_indian-punch_deoghar_260909
    file_parts = stem.split("_")
    if len(file_parts) < 3:
        return JSONResponse({"error": "invalid filename"}, 400)

    provider = file_parts[1].replace("-", "_")
    city = file_parts[2]
    doc_id = f"{date_str}_{provider}_{city}"

    pdf_b64 = get_pdf_base64(doc_id)
    if not pdf_b64:
        return JSONResponse({"error": "not found"}, 404)

    data = base64.b64decode(pdf_b64)
    from fastapi.responses import Response
    return Response(content=data, media_type="application/pdf",
                   headers={"Content-Disposition": f'attachment; filename="{Path(path).name}"'})


class EncodeRequest(BaseModel):
    path: str


class EncodeResponse(BaseModel):
    filename: str
    size_mb: float
    base64: str


@app.post("/api/encode", response_model=EncodeResponse)
async def encode_pdf(req: EncodeRequest):
    """Get PDF from Firestore and return as base64."""
    import base64
    from .storage import get_pdf_base64
    init_firebase()

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
    filename: str
    provider: str = ""
    city: str = ""


class DecodeResponse(BaseModel):
    doc_id: str
    size_mb: float


@app.post("/api/decode", response_model=DecodeResponse)
async def decode_pdf(req: DecodeRequest):
    """Decode base64 and save to Firestore."""
    import base64
    from .storage import save_epaper
    init_firebase()

    data = base64.b64decode(req.base64)

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





HTML_PAGE = r"""<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>E-Paper Download</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#f8fafc;--surface:#ffffff;--border:#e2e8f0;--hover:#f1f5f9;--text:#1e293b;--muted:#64748b;--accent:#2563eb;--green:#16a34a;--purple:#7c3aed;--pink:#db2777;--cyan:#0891b2;--d50:#f0f9ff;--d100:#e0f2fe;--d200:#bae6fd;--d300:#7dd3fc;--d400:#38bdf8;--d500:#0ea5e9;--d600:#0284c7;--d700:#0369a1;--d800:#075985;--d900:#0c4a6e;--amber:#f59e0b;--red:#dc2626}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.5;-webkit-font-smoothing:antialiased}

.nav{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.95);backdrop-filter:blur(20px);border-bottom:1px solid #e2e8f0;padding:.85rem 1.5rem;display:flex;align-items:center;gap:1rem;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.nav-brand{font-size:1.15rem;font-weight:800;background:linear-gradient(135deg,#2563eb,#1d4ed8);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.nav-time{margin-left:auto;display:flex;align-items:center;gap:.75rem;font-size:.85rem}
#clockDate{color:#64748b;font-weight:500;letter-spacing:.02em}
#clockTime{background:linear-gradient(135deg,#2563eb,#7c3aed);color:#fff;font-weight:700;font-variant-numeric:tabular-nums;padding:.4rem .9rem;border-radius:2rem;font-size:.8rem;box-shadow:0 2px 8px rgba(37,99,235,.3);letter-spacing:.03em}

.wrap{max-width:1100px;margin:0 auto;padding:1.5rem}

.sec{margin-bottom:2.5rem}
.sec-head{display:flex;align-items:center;gap:.75rem;margin-bottom:1rem}
.sec-head h2{font-size:1.15rem;font-weight:700;color:#0f172a}
.badge{background:linear-gradient(135deg,#2563eb,#1d4ed8);color:#fff;font-size:.7rem;font-weight:700;padding:.25rem .7rem;border-radius:1rem;box-shadow:0 2px 6px rgba(37,99,235,.25)}

.stats{display:flex;gap:.75rem;margin-bottom:1rem;overflow-x:auto;scrollbar-width:none}
.stats::-webkit-scrollbar{display:none}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:.75rem;padding:.75rem 1.25rem;min-width:100px;text-align:center;flex-shrink:0;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.stat b{display:block;font-size:1.4rem;color:var(--accent);font-weight:700}
.stat small{font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}

.tbl-wrap{background:var(--surface);border:1px solid var(--border);border-radius:.75rem;overflow:hidden;position:relative;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.tbl-wrap.loading::after{content:'';position:absolute;inset:0;background:rgba(255,255,255,.85);display:flex;align-items:center;justify-content:center;z-index:10}
.tbl-wrap.loading::before{content:'⏳';font-size:2rem;position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);z-index:11;animation:pulse 1s infinite}
@keyframes pulse{0%,100%{opacity:1;transform:translate(-50%,-50%) scale(1)}50%{opacity:.5;transform:translate(-50%,-50%) scale(1.2)}}
.tbl{width:100%;border-collapse:collapse}
.tbl th{text-align:left;padding:.85rem 1rem;font-size:.7rem;color:#64748b;text-transform:uppercase;letter-spacing:.08em;border-bottom:2px solid #e2e8f0;background:#f8fafc;font-weight:700}
.tbl td{padding:.85rem 1rem;border-bottom:1px solid #f1f5f9;font-size:.875rem;vertical-align:middle;color:#1e293b}
.tbl tr:last-child td{border-bottom:none}
.tbl tr:hover{background:#e0f2fe}
.tbl tr{transition:background .15s}

.prov{display:inline-flex;align-items:center;gap:.5rem;font-weight:600;color:#0f172a;letter-spacing:-.01em}
.dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;box-shadow:0 0 0 2px rgba(0,0,0,.05)}
.d-ip{background:#f59e0b}.d-pk{background:#22c55e}.d-re{background:#8b5cf6}.d-se{background:#ec4899}.d-lh{background:#06b6d4}
.ctag{background:#eff6ff;color:#1d4ed8;padding:.25rem .7rem;border-radius:1rem;font-size:.75rem;white-space:nowrap;font-weight:600;border:1px solid #dbeafe}
.sz{color:#475569;font-variant-numeric:tabular-nums;font-weight:600;font-size:.85rem}

.btns{display:flex;gap:0;padding:0}
.b{display:inline-flex;align-items:center;gap:.35rem;padding:.5rem 1rem;border-radius:.5rem;font-size:.75rem;font-weight:600;border:none;cursor:pointer;text-decoration:none;transition:all .2s;white-space:nowrap}
.bd{background:linear-gradient(135deg,#2563eb,#1d4ed8);color:#fff;box-shadow:0 1px 3px rgba(37,99,235,.3)}.bd:hover{background:linear-gradient(135deg,#1d4ed8,#1e40af);box-shadow:0 4px 12px rgba(37,99,235,.4);transform:translateY(-1px)}
.bs{background:#f1f5f9;color:#475569;border:1px solid #e2e8f0}.bs:hover{background:#e2e8f0;color:#1e293b}
.bs.ok{background:#22c55e;color:#fff}

.past-card{background:#f8fafc;border:1px solid #e2e8f0;border-radius:.75rem;padding:1.25rem;margin-top:1rem;margin-bottom:1.5rem;box-shadow:0 1px 3px rgba(0,0,0,.06)}

.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.5);backdrop-filter:blur(4px);z-index:100;display:flex;align-items:center;justify-content:center;padding:1rem}
.modal{background:#fff;border-radius:1rem;box-shadow:0 25px 50px -12px rgba(0,0,0,.25);width:100%;max-width:550px;animation:modalIn .25s ease-out}
.modal-header{display:flex;align-items:center;justify-content:space-between;padding:1.25rem 1.5rem;border-bottom:1px solid #e2e8f0}
.modal-header h3{font-size:1.1rem;font-weight:700;color:#0f172a}
.modal-close{background:none;border:none;font-size:1.25rem;color:#64748b;cursor:pointer;padding:.25rem;border-radius:.5rem;transition:all .15s}
.modal-close:hover{background:#f1f5f9;color:#0f172a}
.modal-body{padding:1.5rem}
@keyframes modalIn{from{opacity:0;transform:scale(.95) translateY(10px)}to{opacity:1;transform:scale(1) translateY(0)}}
.past-row{display:flex;gap:.75rem;flex-wrap:wrap;margin-bottom:.75rem}
.field{flex:1;min-width:120px}
.field label{display:block;font-size:.7rem;color:var(--muted);margin-bottom:.3rem;text-transform:uppercase;letter-spacing:.05em;font-weight:600}
.field select,.field input{background:var(--bg);border:1px solid var(--border);color:var(--text);padding:.55rem .75rem;border-radius:.5rem;font-size:.85rem;width:100%;transition:border-color .15s}
.field select:focus,.field input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(37,99,235,.1)}

.dl-btn{width:100%;padding:.7rem;border-radius:.5rem;font-size:.9rem;font-weight:700;border:none;cursor:pointer;transition:all .15s;background:var(--accent);color:#fff;display:flex;align-items:center;justify-content:center;gap:.5rem}
.dl-btn:hover{background:var(--d600);box-shadow:0 2px 8px rgba(37,99,235,.3)}
.dl-btn:disabled{opacity:.5;cursor:not-allowed}
.dl-btn.loading{pointer-events:none}

.msg{margin-top:.75rem;padding:.7rem .9rem;border-radius:.5rem;font-size:.85rem;display:none}
.msg.ok{display:block;background:rgba(22,163,74,.08);border:1px solid rgba(22,163,74,.2);color:var(--green)}
.msg.err{display:block;background:rgba(220,38,38,.08);border:1px solid rgba(220,38,38,.2);color:var(--red)}
.msg.info{display:block;background:rgba(37,99,235,.08);border:1px solid rgba(37,99,235,.2);color:var(--accent)}

.empty{text-align:center;padding:2.5rem 1rem;color:var(--muted)}
.empty i{font-size:2.5rem;display:block;margin-bottom:.5rem}

@media(max-width:640px){
  .tbl-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
  .tbl{min-width:500px}
  .tbl th,.tbl td{padding:.4rem .5rem;font-size:.75rem;white-space:nowrap}
  .sec-head{flex-wrap:wrap}
  .sec-head h2{font-size:.9rem}
  .past-row{flex-direction:column}
  .field{min-width:100%}
  .nav{padding:.6rem 1rem}
  .nav-brand{font-size:1rem}
  .wrap{padding:.75rem}
}
</style>
</head>
<body>
<nav class="nav">
  <div class="nav-brand">📰 E-Paper</div>
  <div class="nav-time"><span id="clockDate"></span> <span id="clockTime"></span></div>
</nav>

<div class="wrap">
  <!-- TODAY -->
  <div class="sec">
    <div class="sec-head">
      <h2>Today's Newspapers — <span id="todayDate"></span></h2>
      <span class="badge" id="badge"></span>
      <button class="b bs" onclick="loadToday()" style="margin-left:auto">🔄 Refresh</button>
      <button class="b bd" onclick="openPastModal()">📥 Past Download</button>
    </div>
    <div class="stats" id="stats"></div>
    <div class="tbl-wrap">
      <table class="tbl"><thead><tr><th>SN</th><th>Newspaper</th><th>City</th><th>Size</th><th>Action</th></tr></thead><tbody id="tbody"></tbody></table>
      <div class="empty" id="empty" style="display:none"><i>📰</i>No e-papers found</div>
    </div>
  </div>
</div>

<!-- PAST DOWNLOAD MODAL -->
<div class="modal-overlay" id="pastModal" style="display:none" onclick="closePastModal(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <div class="modal-header">
      <h3>📥 Past E-Paper Download</h3>
      <button class="modal-close" onclick="closePastModal()">✕</button>
    </div>
    <div class="modal-body">
      <div class="past-row">
        <div class="field"><label>Date</label><input type="date" id="pDate"></div>
        <div class="field"><label>Newspaper</label><select id="pProv"></select></div>
        <div class="field"><label>City</label><select id="pCity"></select></div>
      </div>
      <button class="dl-btn" id="dlBtn" onclick="pastDownload()">⬇ Download</button>
      <div class="msg" id="pMsg"></div>
    </div>
  </div>
</div>

<script>
function openPastModal(){
  document.getElementById('pastModal').style.display='flex';
}
function closePastModal(e){
  if(!e || e.target===document.getElementById('pastModal')){
    document.getElementById('pastModal').style.display='none';
    document.getElementById('pMsg').style.display='none';
  }
}
const DOT={'indian-punch':'d-ip','prabhat-khabar':'d-pk','ranchi-express':'d-re','santal-express':'d-se','livehindustan':'d-lh'};
const PN={'indian-punch':'Indian Punch','prabhat-khabar':'Prabhat Khabar','ranchi-express':'Ranchi Express','santal-express':'Santal Express','livehindustan':'Live Hindustan'};
const CN={ranchi:'रांची',deoghar:'देवघर',dumka:'दुमका',sahibganj:'साहिबगंज',pakur:'पाकुड़',godda:'गोड्डा',dhanbad:'धनबाद',jamshedpur:'जमशेदपुर',giridih:'गिरिडीह',hazaribag:'हजारीबाग',bokaro:'बोकारो'};

function tick(){
  const now=new Date();
  document.getElementById('clockDate').textContent=now.toLocaleDateString('en-IN',{timeZone:'Asia/Kolkata',weekday:'short',day:'numeric',month:'short',year:'numeric'});
  document.getElementById('clockTime').textContent=now.toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',second:'2-digit'});
}
setInterval(tick,1000);tick();

(async function(){
  // Init past form selects
  const ps=document.getElementById('pProv');
  Object.entries(PN).forEach(([k,v])=>{const o=document.createElement('option');o.value=k;o.textContent=v;ps.appendChild(o)});
  const cs=document.getElementById('pCity');
  Object.entries(CN).forEach(([k,v])=>{const o=document.createElement('option');o.value=k;o.textContent=v;cs.appendChild(o)});

  // Load today
  loadToday();
})();

async function loadToday(){
  const tw=document.querySelector('.tbl-wrap');
  tw.classList.add('loading');
  const data=await fetch('/api/today').then(r=>r.json());
  document.getElementById('todayDate').textContent=data.date;
  renderTable(data.files);
  tw.classList.remove('loading');
}

function renderTable(files){
  const tb=document.getElementById('tbody'),st=document.getElementById('stats'),em=document.getElementById('empty'),bg=document.getElementById('badge');
  tb.innerHTML='';st.innerHTML='';em.style.display='none';bg.textContent=files.length;
  if(!files.length){em.style.display='block';return}
  const ps=new Set(),cs=new Set();let mb=0;
  files.forEach(f=>{
    const pk=f.provider_key||f.provider;
    const ck=f.city_key||f.city;
    ps.add(pk);cs.add(ck);
    mb+=(f.size||f.size_mb||0);
  });
  st.innerHTML=`<div class="stat"><b>${files.length}</b><small>Files</small></div><div class="stat"><b>${ps.size}</b><small>Newspapers</small></div><div class="stat"><b>${cs.size}</b><small>Cities</small></div><div class="stat"><b>${mb.toFixed?mb.toFixed(0):mb}</b><small>MB</small></div>`;
  files.forEach((f,i)=>{
    const pk=f.provider_key||f.provider;
    const ck=f.city_key||f.city;
    const prov=PN[pk]||pk.replace(/-/g,' ').replace(/\b\w/g,l=>l.toUpperCase());
    const city=CN[ck]||ck.replace(/-/g,' ').replace(/\b\w/g,l=>l.toUpperCase());
    const cls=DOT[pk]||'d-ip';
    const sz=f.size||f.size_mb||0;
    const url='/download/'+f.path;
    const tr=document.createElement('tr');
    tr.innerHTML=`<td data-label="SN">${i+1}</td><td data-label="Newspaper"><span class="prov"><span class="dot ${cls}"></span>${prov}</span></td><td data-label="City"><span class="ctag">${city}</span></td><td data-label="Size" class="sz">${sz} MB</td><td data-label="Action" class="btns"><a class="b bd" href="${url}" download>⬇ Download</a></td>`;
    tb.appendChild(tr);
  });
}

async function copyL(btn,url){
  await navigator.clipboard.writeText(url);
  btn.classList.add('ok');btn.textContent='✓ कॉपी';
  setTimeout(()=>{btn.classList.remove('ok');btn.textContent='🔗 लिंक'},1200);
}

async function pastDownload(){
  const date=document.getElementById('pDate').value;
  const prov=document.getElementById('pProv').value;
  const city=document.getElementById('pCity').value;
  const msg=document.getElementById('pMsg');
  const btn=document.getElementById('dlBtn');

  if(!date){msg.className='msg err';msg.textContent='Select a date';return}

  btn.classList.add('loading');
  btn.innerHTML='⏳ Downloading... Please wait';
  msg.className='msg info';msg.style.display='block';msg.textContent='Fetching from source, this may take 30-60 seconds...';

  try{
    const res=await fetch(`/api/lookup?date=${date}&provider=${prov}&city=${city}`);
    if(res.ok && res.headers.get('content-type')?.includes('application/pdf')){
      const blob=await res.blob();
      const url=URL.createObjectURL(blob);
      const filename=`epaper_${prov}_${city}_${date.replace(/-/g,'')}.pdf`;
      const a=document.createElement('a');a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();
      URL.revokeObjectURL(url);
      msg.className='msg ok';msg.textContent='Download started!';
    }else{
      const data=await res.json();
      msg.className='msg err';msg.textContent=data.error||'E-paper not available for this date';
    }
  }catch(e){
    msg.className='msg err';msg.textContent='Connection error or source unavailable';
  }
  btn.classList.remove('loading');
  btn.innerHTML='⬇ Download';
}
</script>
</body>
</html>"""

if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
