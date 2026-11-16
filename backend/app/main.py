"""FastAPI 入口。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.db import close_db, init_db
from app.routers import generation, novels, outline, providers, skills, story_bible, tasks
from app.schemas.health import HealthOut
from app.services.health import collect_health
from app.services.batch_generation import batch_generate_handler
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
    queue.register("batch_generate", batch_generate_handler)
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
    app.include_router(providers.router)
    app.include_router(skills.router)

    @app.get("/api/health", response_model=HealthOut)
    async def health(
        response: Response,
        probe: str | None = Query(
            default=None,
            description="传 llm、1 或 true 时，用已配置的续写密钥做一次连通探测",
        ),
    ):
        report = await collect_health(probe_llm=_wants_llm_probe(probe))
        if not report.checks.db.ok:
            response.status_code = 503
        return report

    return app


def _wants_llm_probe(probe: str | None) -> bool:
    return (probe or "").strip().lower() in {"1", "true", "yes", "llm"}


def local_uvicorn_options(settings: Settings | None = None) -> dict[str, object]:
    """本地与开发进程的 uvicorn 参数。默认只监听 127.0.0.1。

    容器不使用这里：镜像命令显式传入 ``--host 0.0.0.0``，
    以便 Compose 网络中的 nginx 访问 ``backend:8000``。
    """
    resolved = settings if settings is not None else get_settings()
    return {
        "app": "app.main:app",
        "host": resolved.bind_host,
        "port": 8000,
        "reload": True,
    }


app = create_app()
