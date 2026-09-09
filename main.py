"""E-Paper Download System — Main Entry Point"""
import os
import sys


def create_app():
    """Lazy-load app to reduce memory on startup."""
    import uvicorn
    from contextlib import asynccontextmanager
    from app.web import app

    @asynccontextmanager
    async def lifespan(app):
        from app.storage import init_firebase
        from app.scheduler import start_scheduler
        init_firebase()
        start_scheduler()
        yield

    app.router.lifespan_context = lifespan
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
    )
