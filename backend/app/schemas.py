from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str
    type: str = ""
    icon: str = "🎮"
    description: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    icon: str | None = None
    description: str | None = None
    profile: dict[str, Any] | None = None
    prompt_text: str | None = None


class ProjectAnalysisRequest(BaseModel):
    intro: str = ""
    asset_artifact_ids: list[str] = Field(default_factory=list)


class GlossaryTermPayload(BaseModel):
    source: str
    target: str = ""
    category: str = ""
    note: str = ""
    source_type: str = "manual"
    confirmed: bool = False


class RunCreate(BaseModel):
    project_id: str
    kind: str = "translation"
    language: str = "en"
    input_artifact_id: str | None = None
    term_artifact_id: str | None = None
    batch_size: int | None = None


class GlossaryExtractRequest(BaseModel):
    input_artifact_id: str
    project_name: str | None = None
    source_only: bool = False
    include_empty_final_terms: bool = False
    sheet: str | None = None
    id_column: str = "ID"
    source_column: str = "cn"
    target_column: str = "en"


class TranslateRequest(BaseModel):
    provider: str | None = None
    protocol: str | None = None
    batch_size: int | None = None


class SettingsUpdate(BaseModel):
    provider: str | None = None
    protocol: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    batch_size: int | None = None
    multimodal: dict[str, bool] | None = None

