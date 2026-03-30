"""Prolific Content Generation API - Main Entry Point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from prolific.api.v1.generation import router as generation_router
from prolific.api.v1.shorts import router as shorts_router
from prolific.api.v1.youtube import router as youtube_router
from prolific.core.config import settings

IMAGES_DIR = Path(__file__).parent / "generated_images"
IMAGES_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting Prolific Content Generation API")
    from prolific.youtube.scheduler import start_scheduler as start_youtube_scheduler
    from prolific.shorts.scheduler import start_scheduler as start_shorts_scheduler
    from prolific.youtube.comment_scheduler import start_scheduler as start_comment_scheduler
    start_youtube_scheduler()
    start_shorts_scheduler()
    start_comment_scheduler()
    yield
    from prolific.youtube.scheduler import stop_scheduler as stop_youtube_scheduler
    from prolific.shorts.scheduler import stop_scheduler as stop_shorts_scheduler
    from prolific.youtube.comment_scheduler import stop_scheduler as stop_comment_scheduler
    stop_youtube_scheduler()
    stop_shorts_scheduler()
    stop_comment_scheduler()
    logger.info("Shutting down Prolific Content Generation API")


app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description="LangGraph-based long-form content generation system",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(generation_router, prefix=settings.api_prefix)
app.include_router(youtube_router, prefix=settings.api_prefix)
app.include_router(shorts_router, prefix=settings.api_prefix)

# Serve generated images
app.mount("/images", StaticFiles(directory=str(IMAGES_DIR)), name="images")


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": settings.api_title,
        "version": settings.api_version,
        "docs": "/docs",
        "health": f"{settings.api_prefix}/generation/health",
    }


@app.get("/health")
async def health():
    """Global health check — reports if any pipeline is actively running."""
    from prolific.core.pipeline_lock import get_active_pipelines
    active = get_active_pipelines()
    return {
        "status": "healthy",
        "pipelines_running": len(active),
        "active_pipelines": active,
        "safe_to_deploy": len(active) == 0,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
