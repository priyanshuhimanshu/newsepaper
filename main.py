"""E-Paper Download System — Main Entry Point"""
import os
import uvicorn
from contextlib import asynccontextmanager
from app.web import app
from app.scheduler import start_scheduler
from app.storage import init_firebase


@asynccontextmanager
async def lifespan(app):
    init_firebase()
    start_scheduler()
    yield


app.router.lifespan_context = lifespan

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "app.web:app",
        host="0.0.0.0",
        port=port,
        reload=True,
    )
