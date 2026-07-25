"""FastAPI 入口。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import close_db, init_db
from app.routers import generation, novels, outline, story_bible, tasks
from app.services.ingestion import ingest_novel_handler
from app.services.tasks import get_task_queue

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mythweaver")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    await init_db()
    queue = get_task_queue()
    queue.register("ingest", ingest_novel_handler)
    logger.info("MythWeaver 已启动，数据目录: %s", settings.data_dir)
    yield
    await close_db()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(novels.router)
    app.include_router(story_bible.router)
    app.include_router(outline.router)
    app.include_router(generation.router)
    app.include_router(tasks.router)

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "app": settings.app_name}

    return app


app = create_app()
