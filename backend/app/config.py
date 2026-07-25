"""应用配置：双协议端点 / 模型分级 / token 预算。"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["openai", "anthropic"]

# backend/ 目录
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "MythWeaver"
    debug: bool = True

    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    database_url: str = ""

    # Token 预算
    context_token_budget: int = 16000
    ingest_concurrency: int = 8

    # 摘要模型
    summary_provider: Provider = "openai"
    summary_base_url: str = "https://api.openai.com/v1"
    summary_api_key: str = ""
    summary_model: str = "gpt-4o-mini"

    # 生成模型
    generation_provider: Provider = "openai"
    generation_base_url: str = "https://api.openai.com/v1"
    generation_api_key: str = ""
    generation_model: str = "gpt-4o"

    # Embedding
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dims: int = 1536

    # 限流
    llm_rpm: int = 60
    llm_tpm: int = 100_000
    llm_max_retries: int = 3

    # 成本单价 USD / 1M tokens
    cost_summary_input: float = 0.15
    cost_summary_output: float = 0.60
    cost_generation_input: float = 2.50
    cost_generation_output: float = 10.00
    cost_embedding: float = 0.02

    @field_validator("data_dir", mode="before")
    @classmethod
    def _resolve_data_dir(cls, v):  # noqa: ANN001
        if v is None or v == "":
            return PROJECT_ROOT / "data"
        p = Path(v)
        if not p.is_absolute():
            p = (BACKEND_DIR / p).resolve()
        return p

    def resolved_database_url(self) -> str:
        if self.database_url and "://" in self.database_url:
            prefix = "sqlite+aiosqlite:///"
            if self.database_url.startswith(prefix):
                raw = self.database_url[len(prefix) :]
                path = Path(raw)
                if not path.is_absolute():
                    path = (BACKEND_DIR / path).resolve()
                return f"{prefix}{path.as_posix()}"
            return self.database_url
        db_path = (self.data_dir / "mythweaver.db").resolve()
        return f"sqlite+aiosqlite:///{db_path.as_posix()}"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "imports").mkdir(parents=True, exist_ok=True)
    return settings
