"""阶段写法 API 模型。"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.services.writing_skills import MAX_SOURCE_BYTES


class SkillSourceIn(BaseModel):
    source: Optional[str] = Field(default=None, max_length=MAX_SOURCE_BYTES)
    catalog_id: Optional[str] = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def exactly_one_source(self):
        has_source = bool(self.source and self.source.strip())
        has_catalog = bool(self.catalog_id and self.catalog_id.strip())
        if has_source == has_catalog:
            raise ValueError("提供 source 或 catalog_id 其中之一")
        return self


class SkillInstallIn(SkillSourceIn):
    replace: bool = False


class SkillUpdateIn(BaseModel):
    enabled: bool


class SkillPreviewOut(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    name: Optional[str] = None
    description: Optional[str] = None
    stage: Optional[str] = None
    stage_label: Optional[str] = None
    body: Optional[str] = None
    catalog_id: Optional[str] = None
    already_installed: bool = False


class SkillOut(BaseModel):
    id: int
    name: str
    description: str
    stage: str
    stage_label: str
    body: str
    enabled: bool
    injected: bool
    origin: str
    catalog_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SkillInstalledOut(SkillOut):
    warning: Optional[str] = None


class CatalogOut(BaseModel):
    catalog_id: str
    name: str
    description: str
    stage: str
    stage_label: str
    installed: bool


class SkillDeletedOut(BaseModel):
    message: str
    id: int
