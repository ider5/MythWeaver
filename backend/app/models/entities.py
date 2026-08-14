"""SQLAlchemy 数据模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Novel(Base):
    __tablename__ = "novels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String(128))
    genre: Mapped[str] = mapped_column(String(64), default="玄幻")  # 玄幻/都市/言情
    description: Mapped[Optional[str]] = mapped_column(Text)
    source_path: Mapped[Optional[str]] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), default="imported")
    # imported | ingesting | ready | generating
    total_chars: Mapped[int] = mapped_column(Integer, default=0)
    chapter_count: Mapped[int] = mapped_column(Integer, default=0)
    # 原作（非生成）单章篇幅缓存；0 表示尚未统计
    avg_chapter_chars: Mapped[int] = mapped_column(Integer, default=0)
    median_chapter_chars: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    chapters: Mapped[list[Chapter]] = relationship(back_populates="novel", cascade="all, delete-orphan")
    characters: Mapped[list[Character]] = relationship(back_populates="novel", cascade="all, delete-orphan")
    world_settings: Mapped[list[WorldSetting]] = relationship(
        back_populates="novel", cascade="all, delete-orphan"
    )
    plot_threads: Mapped[list[PlotThread]] = relationship(
        back_populates="novel", cascade="all, delete-orphan"
    )
    outlines: Mapped[list[Outline]] = relationship(back_populates="novel", cascade="all, delete-orphan")
    summaries: Mapped[list[Summary]] = relationship(back_populates="novel", cascade="all, delete-orphan")
    style_samples: Mapped[list[StyleSample]] = relationship(
        back_populates="novel", cascade="all, delete-orphan"
    )
    recurrent_memory: Mapped[Optional[RecurrentMemory]] = relationship(
        back_populates="novel", uselist=False, cascade="all, delete-orphan"
    )


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("novel_id", "index", name="uq_novel_chapter_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based
    title: Mapped[str] = mapped_column(String(256), default="")
    volume: Mapped[Optional[str]] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text, default="")
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    # raw → summarized → extracted → embedded
    status: Mapped[str] = mapped_column(String(32), default="raw")
    is_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    outline_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("outline_items.id", ondelete="SET NULL"), nullable=True
    )
    embedding_json: Mapped[Optional[list[float]]] = mapped_column(JSON)  # 回退向量存储
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    novel: Mapped[Novel] = relationship(back_populates="chapters")
    versions: Mapped[list[ChapterVersion]] = relationship(
        back_populates="chapter", cascade="all, delete-orphan"
    )
    summaries: Mapped[list[Summary]] = relationship(back_populates="chapter")


class ChapterVersion(Base):
    __tablename__ = "chapter_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    # generated | critic_revised | user_edited
    version_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    consistency_report: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    parent_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("chapter_versions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    chapter: Mapped[Chapter] = relationship(back_populates="versions")


class Summary(Base):
    __tablename__ = "summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # chapter | volume
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    volume_key: Mapped[Optional[str]] = mapped_column(String(128))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    novel: Mapped[Novel] = relationship(back_populates="summaries")
    chapter: Mapped[Optional[Chapter]] = relationship(back_populates="summaries")


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    role: Mapped[Optional[str]] = mapped_column(String(64))  # 主角/配角/反派
    status: Mapped[Optional[str]] = mapped_column(String(256))  # 存活/修为/位置
    personality: Mapped[Optional[str]] = mapped_column(Text)
    speech_style: Mapped[Optional[str]] = mapped_column(Text)
    relationships: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_appear_chapter: Mapped[Optional[int]] = mapped_column(Integer)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    novel: Mapped[Novel] = relationship(back_populates="characters")


class WorldSetting(Base):
    __tablename__ = "world_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(64), default="规则")  # 力量体系/地理/组织/规则
    title: Mapped[str] = mapped_column(String(256), default="")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    do_not_violate: Mapped[Optional[str]] = mapped_column(Text)  # 禁止事项
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    novel: Mapped[Novel] = relationship(back_populates="world_settings")


class PlotThread(Base):
    __tablename__ = "plot_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    thread_type: Mapped[str] = mapped_column(String(32), default="伏笔")  # 伏笔/主线/支线
    status: Mapped[str] = mapped_column(String(32), default="未回收")  # 未回收/已回收
    introduced_chapter: Mapped[Optional[int]] = mapped_column(Integer)
    resolved_chapter: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    novel: Mapped[Novel] = relationship(back_populates="plot_threads")


class Outline(Base):
    __tablename__ = "outlines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(256), default="续写大纲")
    status: Mapped[str] = mapped_column(String(32), default="draft")  # draft | confirmed
    start_from_chapter: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    novel: Mapped[Novel] = relationship(back_populates="outlines")
    items: Mapped[list[OutlineItem]] = relationship(
        back_populates="outline", cascade="all, delete-orphan", order_by="OutlineItem.order"
    )


class OutlineItem(Base):
    __tablename__ = "outline_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    outline_id: Mapped[int] = mapped_column(ForeignKey("outlines.id", ondelete="CASCADE"), index=True)
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(256), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    key_points: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|generating|done

    outline: Mapped[Outline] = relationship(back_populates="items")


class AsyncTask(Base):
    __tablename__ = "async_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("novels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    # pending | running | completed | failed | cancelled
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(String(512), default="")
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class CostLog(Base):
    __tablename__ = "cost_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("novels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    purpose: Mapped[str] = mapped_column(String(64), default="")  # summary|generation|embed|critic
    provider: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RecurrentMemory(Base):
    """递归记忆状态（上一章结尾状态）。"""

    __tablename__ = "recurrent_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), unique=True, index=True
    )
    last_chapter_index: Mapped[int] = mapped_column(Integer, default=0)
    ending_state: Mapped[str] = mapped_column(Text, default="")
    character_positions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timeline_cursor: Mapped[Optional[str]] = mapped_column(String(256))
    open_threads: Mapped[list[str]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    novel: Mapped[Novel] = relationship(back_populates="recurrent_memory")


class StyleSample(Base):
    __tablename__ = "style_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[Optional[int]] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    novel: Mapped[Novel] = relationship(back_populates="style_samples")
