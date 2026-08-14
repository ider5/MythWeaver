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
from app.services.generation import revise_commit_handler
from app.services.outline import outline_generate_handler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mythweaver")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    await init_db()
    from app.db import SessionLocal
    from app.services.tasks import fail_interrupted_tasks, get_task_queue

    if SessionLocal is not None:
        async with SessionLocal() as session:
            n = await fail_interrupted_tasks(session)
            if n:
                logger.info("已将 %s 个中断任务标为失败", n)

    queue = get_task_queue()
    queue.register("ingest", ingest_novel_handler)
    queue.register("revise_commit", revise_commit_handler)
    queue.register("outline_generate", outline_generate_handler)
    logger.info("MythWeaver 已启动，数据目录: %s", settings.data_dir)
    yield
    await close_db()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_cors_origins(),
        allow_credentials=False,
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
