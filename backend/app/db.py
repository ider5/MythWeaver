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

# 扩展是否已在当前进程成功加载过（connect 时每次都会再 load）
_vec_extension_ok: bool = False
_vec_table_ok: bool = False


def is_vec_available() -> bool:
    """检索/入库是否应优先走 sqlite-vec。"""
    return _vec_extension_ok and _vec_table_ok


def _unwrap_sqlite3_connection(dbapi_conn):
    """从 SQLAlchemy aiosqlite 包装中取出底层 sqlite3.Connection。

    链路：AsyncAdapt_aiosqlite_connection → aiosqlite.Connection → sqlite3.Connection
    aiosqlite 的 enable_load_extension 是 async，不能在同步 connect 事件里 await，
    必须对真正的 sqlite3.Connection 调用同步 API。
    """
    aio = getattr(dbapi_conn, "driver_connection", None) or getattr(
        dbapi_conn, "_connection", None
    )
    if aio is not None:
        raw = getattr(aio, "_conn", None)
        if raw is not None:
            return raw
    # 同步 sqlite3（非 aiosqlite 路径）
    if hasattr(dbapi_conn, "enable_load_extension"):
        return dbapi_conn
    return None


def _load_sqlite_vec_on_connection(dbapi_conn) -> bool:
    """在单个 DBAPI 连接上加载 sqlite-vec。返回是否成功。"""
    global _vec_extension_ok
    try:
        import sqlite_vec

        raw = _unwrap_sqlite3_connection(dbapi_conn)
        if raw is None:
            raise RuntimeError(
                f"无法解包 sqlite3 连接（类型={type(dbapi_conn).__name__}）"
            )

        raw.enable_load_extension(True)
        try:
            sqlite_vec.load(raw)
        finally:
            try:
                raw.enable_load_extension(False)
            except Exception:  # noqa: BLE001
                pass
        _vec_extension_ok = True
        return True
    except Exception as exc:  # noqa: BLE001
        _vec_extension_ok = False
        logger.warning("sqlite-vec 加载失败，将使用 JSON 向量回退: %s", exc)
        return False


def _configure_sqlite_connection(dbapi_conn, _connection_record) -> None:
    """启用 WAL，并加载 sqlite-vec（每个新连接都要加载扩展）。"""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

    _load_sqlite_vec_on_connection(dbapi_conn)


async def init_db() -> None:
    global engine, SessionLocal, _vec_extension_ok, _vec_table_ok
    _vec_extension_ok = False
    _vec_table_ok = False
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
        _vec_table_ok = await _ensure_vec_table(conn, settings.embedding_dims)

    if is_vec_available():
        logger.info("sqlite-vec 已就绪（dims=%s）", settings.embedding_dims)
        assert SessionLocal is not None
        async with SessionLocal() as session:
            from app.services.retrieval import backfill_vec_from_json

            n = await backfill_vec_from_json(session)
            if n:
                await session.commit()
                logger.info("已将 %s 条 JSON 向量回填到 vec0", n)
    else:
        logger.warning("sqlite-vec 不可用，向量检索将使用 JSON 余弦回退")


async def _ensure_vec_table(conn, dims: int) -> bool:
    """创建 sqlite-vec 虚拟表；维度不一致时重建。失败返回 False。"""
    try:
        row = (
            await conn.execute(
                text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type IN ('table', 'view') AND name = 'chapter_embeddings'"
                )
            )
        ).fetchone()
        existing_sql = row[0] if row else None
        if existing_sql and f"float[{dims}]" not in existing_sql:
            logger.warning(
                "chapter_embeddings 维度与 EMBEDDING_DIMS=%s 不一致，重建 vec0 表",
                dims,
            )
            await conn.execute(text("DROP TABLE IF EXISTS chapter_embeddings"))
            existing_sql = None

        if not existing_sql:
            await conn.execute(
                text(
                    f"""
                    CREATE VIRTUAL TABLE chapter_embeddings USING vec0(
                        chapter_id INTEGER PRIMARY KEY,
                        embedding float[{dims}]
                    )
                    """
                )
            )
        else:
            # IF NOT EXISTS 路径：确认可查询
            await conn.execute(text("SELECT count(*) FROM chapter_embeddings"))

        # 冒烟：扩展函数可用
        ver = (await conn.execute(text("SELECT vec_version()"))).fetchone()
        logger.info("sqlite-vec 版本: %s", ver[0] if ver else "?")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("创建 vec0 表失败（将使用 JSON 回退）: %s", exc)
        return False


async def close_db() -> None:
    global engine, SessionLocal, _vec_extension_ok, _vec_table_ok
    if engine is not None:
        await engine.dispose()
    engine = None
    SessionLocal = None
    _vec_extension_ok = False
    _vec_table_ok = False


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    if SessionLocal is None:
        raise RuntimeError("数据库未初始化")
    async with SessionLocal() as session:
        yield session
