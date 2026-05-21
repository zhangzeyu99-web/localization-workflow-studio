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


class ProjectHarnessUpdate(BaseModel):
    project_metadata: dict[str, Any] | None = None
    style_guidance: str | None = None
    target_audience: str | None = None
    tone: str | None = None
    forbidden_translations: list[str] | None = None
    fixed_terms: list[dict[str, Any]] | None = None
    hard_rules: list[dict[str, Any]] | None = None
    soft_rules: list[dict[str, Any]] | None = None
    reference_examples: list[dict[str, Any]] | None = None
    manual_fixes: list[dict[str, Any]] | None = None
    qa_summary: dict[str, Any] | None = None


class ArtifactUpdate(BaseModel):
    label: str | None = None
    role: str | None = None
    origin: str | None = None
    metadata: dict[str, Any] | None = None


class ProjectAnalysisRequest(BaseModel):
    intro: str = ""
    asset_artifact_ids: list[str] = Field(default_factory=list)


class GlossaryTermPayload(BaseModel):
    term_key: str = ""
    source: str
    target: str = ""
    target_alt: str = ""
    category: str = ""
    note: str = ""
    source_type: str = "manual"
    confirmed: bool = False


class GlossaryTermUpdate(BaseModel):
    term_key: str | None = None
    source: str | None = None
    target: str | None = None
    target_alt: str | None = None
    category: str | None = None
    note: str | None = None
    source_type: str | None = None
    confirmed: bool | None = None


class GlossaryImportRequest(BaseModel):
    artifact_id: str
    sheet: str | None = None
    term_key_column: str | None = None
    source_column: str | None = None
    target_column: str | None = None
    target_alt_column: str | None = None
    category_column: str | None = None
    note_column: str | None = None
    limit: int = 100


class RunCreate(BaseModel):
    project_id: str
    kind: str = "translation"
    language: str = "en"
    input_artifact_id: str | None = None
    term_artifact_id: str | None = None
    batch_size: int | None = None
    task_origin: str | None = None
    source_run_id: str | None = None
    task_code: str | None = None


class ManualFixItem(BaseModel):
    sheet: str | None = None
    row: int
    translation: str
    note: str = ""
    issue_id: str | None = None


class ManualFixRequest(BaseModel):
    fixes: list[ManualFixItem]
    rerun_qa: bool = True


class ModelFixRequest(BaseModel):
    max_issues: int = 80
    rerun_qa: bool = True


class GlossaryExtractRequest(BaseModel):
    input_artifact_id: str
    project_name: str | None = None
    source_only: bool = False
    include_empty_final_terms: bool = False
    project_material_artifact_ids: list[str] = Field(default_factory=list)
    project_notes: list[str] = Field(default_factory=list)
    sheet: str | None = None
    id_column: str = "ID"
    source_column: str = "cn"
    target_column: str = "en"


class TranslateRequest(BaseModel):
    provider: str | None = None
    protocol: str | None = None
    preset: str | None = None
    batch_size: int | None = None
    allow_mock: bool = False


class SettingsUpdate(BaseModel):
    provider: str | None = None
    preset: str | None = None
    protocol: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    batch_size: int | None = None
    multimodal: dict[str, bool] | None = None
