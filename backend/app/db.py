"""SQLite (WAL) + sqlite-vec 初始化。"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


engine: AsyncEngine | None = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None


def _configure_sqlite_connection(dbapi_conn, _connection_record) -> None:
    """启用 WAL，并尝试加载 sqlite-vec。"""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

    try:
        import sqlite_vec

        dbapi_conn.enable_load_extension(True)
        sqlite_vec.load(dbapi_conn)
        dbapi_conn.enable_load_extension(False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("sqlite-vec 加载失败，将使用 JSON 向量回退: %s", exc)


async def init_db() -> None:
    global engine, SessionLocal
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    engine = create_async_engine(
        settings.resolved_database_url(),
        echo=settings.debug,
        connect_args={"check_same_thread": False},
    )
    event.listen(engine.sync_engine, "connect", _configure_sqlite_connection)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # 导入模型以注册 metadata
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_vec_table(conn, settings.embedding_dims)


async def _ensure_vec_table(conn, dims: int) -> None:
    """创建 sqlite-vec 虚拟表；失败则跳过。"""
    try:
        await conn.execute(
            text(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS chapter_embeddings USING vec0(
                    chapter_id INTEGER PRIMARY KEY,
                    embedding float[{dims}]
                )
                """
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("创建 vec0 表失败（将使用 JSON 回退）: %s", exc)


async def close_db() -> None:
    global engine, SessionLocal
    if engine is not None:
        await engine.dispose()
    engine = None
    SessionLocal = None


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    if SessionLocal is None:
        raise RuntimeError("数据库未初始化")
    async with SessionLocal() as session:
        yield session
