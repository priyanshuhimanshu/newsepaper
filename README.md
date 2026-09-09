# E-Paper Download System

Download Hindi newspaper e-papers from multiple sources. Stores PDFs in Firebase Firestore (no local files). Scheduled downloads at 4 AM and 4 PM IST.

## Features

- **Today's Newspapers**: Auto-downloaded and stored in Firestore
- **Past Downloads**: Download any date directly from source (no storage)
- **Professional UI**: Responsive design with real-time updates
- **Auto Cleanup**: Records older than 3 months are automatically deleted

## Supported Newspapers

| Provider | Cities | Method |
|----------|--------|--------|
| Indian Punch | Deoghar | Direct PDF download |
| Prabhat Khabar | Ranchi, Deoghar, Dumka, Sahibganj, Pakur, Godda, Dhanbad, Jamshedpur, Hazaribag, Giridih | Multi-page image → PDF |
| Ranchi Express | Ranchi | Page images → PDF |
| Santal Express | Ranchi | API + webp images → PDF |
| Live Hindustan | Sahibganj, Godda, Deoghar, Dumka, Dhanbad, Jamshedpur, Giridih, Bokaro, Ranchi, Pakur, Hazaribag | High-res webp → PDF |

## Quick Start

### Prerequisites

1. Python 3.11+
2. Firebase Admin SDK credentials (service account JSON)

### Installation

```bash
# Clone repository
git clone <repo-url>
cd <dir>

# Install dependencies
pip install -r requirements.txt

# Place Firebase credentials
# Copy your service account JSON to: app/news-storage-01-firebase-adminsdk-fbsvc-934ae7bccd.json
```

### Run
 
 ```bash
 # Start the web server
 python -m app.web
 
 # Alternative: Run with uvicorn for better stability and auto-reload
 python -m uvicorn app.web:app --host 127.0.0.1 --port 8000 --reload
 
 # If port 8000 is blocked, clear zombie processes first:
 # Stop-Process -Name "python" -Force
 # Stop-Process -Name "uvicorn" -Force
 ```
 
 Open http://127.0.0.1:8000

### Docker

```bash
docker compose up -d
```

## Usage

### Web UI

- **Today's Newspapers**: Auto-loaded from Firestore
- **Refresh**: Click 🔄 to reload the list
- **Download**: Click ⬇ to download a newspaper
- **Past Download**: Click 📥 to open modal, select date/newspaper/city, download directly from source

### Scheduler

The scheduler runs automatically when using `main.py`:

```bash
python main.py
```

Or run the scheduler manually:

```bash
python -c "import asyncio; from app.scheduler import download_job; asyncio.run(download_job())"
```

**Schedule**: Downloads at 4 AM and 4 PM IST
**Cleanup**: Automatically deletes records older than 3 months

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI |
| `/api/today` | GET | List today's e-papers from Firestore |
| `/api/lookup?date=&provider=&city=` | GET | Download past e-paper from source |
| `/download/{path}` | GET | Download PDF from Firestore |
| `/api/health` | GET | Health check |

## Project Structure

```
├── main.py                     # Entry point with scheduler
├── app/
│   ├── web.py                  # Web UI + API endpoints
│   ├── storage.py              # Firebase Firestore operations
│   ├── scheduler.py            # APScheduler for auto downloads
│   ├── config.py               # Pydantic settings
│   ├── utils.py                # IST timezone helper
│   ├── api/
│   │   └── main.py             # Health endpoint
│   ├── ingestion/
│   │   └── epaper.py           # Core downloader (image → PDF)
│   └── news-storage-01-*.json  # Firebase credentials
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## Configuration

Environment variables (`.env`):

```
LOG_LEVEL=INFO
TIMEZONE=Asia/Kolkata
```

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Web UI     │────▶│  FastAPI      │────▶│  Firebase       │
│  (Browser)  │     │  (app/web.py)│     │  Firestore      │
└─────────────┘     └──────────────┘     └─────────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │  Scheduler   │
                    │  (4AM/4PM)   │
                    └──────────────┘
```

- **Today's papers**: Downloaded by scheduler → Stored in Firestore (chunked)
- **Past papers**: Downloaded on-demand from source → Returned directly (no storage)
- **No local files**: All data stored in Firestore

## Deployment

### Free Hosting Options (No Credit Card Required)

| Platform | Free Tier | Sleep | Best For |
|----------|-----------|-------|----------|
| **Render** | 750 hrs/month | Yes (15 min idle) | Easiest setup |
| **Railway** | $5 credit trial | No | Full-stack apps |
| **Fly.io** | 3 shared VMs | No | Always-on apps |
| **SnapDeploy** | 10 deploys/day | Auto-sleep | Docker apps |
| **Velixir** | 0.25 vCPU, 256MB | Yes (scale to zero) | EU hosting |
| **Waifly** | 300MB RAM, 1GB disk | No | Always-on, no card |

### Deploy to Render (Recommended Free)

1. Push code to GitHub
2. Go to [render.com](https://render.com) → New Web Service
3. Connect your GitHub repo
4. Settings:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python -m app.web`
5. Add environment variable: `PYTHON_VERSION=3.11`
6. Deploy

### Deploy to Railway

1. Go to [railway.app](https://railway.app) → New Project
2. Deploy from GitHub repo
3. Railway auto-detects Python
4. Add a `Procfile`:
   ```
   web: python -m app.web
   ```
5. Deploy

### Deploy with Docker (Any Platform)

```bash
# Build
docker build -t epaper-app .

# Run
docker run -p 8000:8000 epaper-app
```

### Firebase Setup for Deployment

1. Create Firebase project at [console.firebase.google.com](https://console.firebase.google.com)
2. Enable Firestore Database
3. Generate service account key (JSON)
4. Add JSON content as environment variable or mount as file
5. Update `storage.py` to use environment variable for credentials:

```python
import json
import os

cred = credentials.Certificate(json.loads(os.environ.get("FIREBASE_CRED")))
```
