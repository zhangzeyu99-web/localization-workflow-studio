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
    target_language: str = "en"


class GlossaryTermPayload(BaseModel):
    term_key: str = ""
    source: str
    target: str = ""
    target_alt: str = ""
    language: str = "en"
    category: str = ""
    note: str = ""
    source_type: str = "manual"
    confirmed: bool = True


class GlossaryTermUpdate(BaseModel):
    term_key: str | None = None
    source: str | None = None
    target: str | None = None
    target_alt: str | None = None
    language: str | None = None
    category: str | None = None
    note: str | None = None
    source_type: str | None = None
    confirmed: bool | None = None


class GlossaryCandidateUpdate(BaseModel):
    term_key: str | None = None
    source: str | None = None
    target: str | None = None
    target_alt: str | None = None
    language: str | None = None
    category: str | None = None
    note: str | None = None
    translation_status: str | None = None
    translation_source: str | None = None
    metadata: dict[str, Any] | None = None


class GlossaryBatchResolveRequest(BaseModel):
    candidate_ids: list[str] = Field(default_factory=list)


class GlossaryImportRequest(BaseModel):
    artifact_id: str
    mode: str = "merge"
    languages: list[str] = Field(default_factory=list)
    dataset_key: str | None = None
    override_protected: bool = False
    confirmed_glossary: bool | None = None
    sheet: str | None = None
    term_key_column: str | None = None
    source_column: str | None = None
    target_column: str | None = None
    target_alt_column: str | None = None
    auto_languages: bool = True
    language: str = "en"
    category_column: str | None = None
    note_column: str | None = None
    limit: int = 100


class TranslationEntryPayload(BaseModel):
    entry_key: str = ""
    source: str = ""
    target: str = ""
    target_alt: str = ""
    language: str = "en"
    sheet: str = ""
    row_number: int = 0
    note: str = ""
    source_type: str = "manual"
    source_artifact_id: str = ""


class TranslationEntryUpdate(BaseModel):
    entry_key: str | None = None
    source: str | None = None
    target: str | None = None
    target_alt: str | None = None
    language: str | None = None
    sheet: str | None = None
    row_number: int | None = None
    note: str | None = None
    source_type: str | None = None
    source_artifact_id: str | None = None


class TranslationArchiveImportRequest(BaseModel):
    artifact_id: str
    sheet: str | None = None
    id_column: str | None = None
    source_column: str | None = None
    target_column: str | None = None
    target_alt_column: str | None = None
    note_column: str | None = None
    auto_languages: bool = True
    language: str = "en"
    mode: str = "merge"
    languages: list[str] = Field(default_factory=list)
    dataset_key: str | None = None
    override_protected: bool = False


class ArchiveImportCommitRequest(BaseModel):
    token: str


class ArchiveSourcePatchRequest(BaseModel):
    expected_revision: str
    shared: dict[str, str] = Field(default_factory=dict)
    targets: dict[str, str] = Field(default_factory=dict)


class AnnouncementLookupRequest(BaseModel):
    material_artifact_ids: list[str] = Field(default_factory=list)
    text: str = ""
    language: str = "en"
    min_term_length: int = 2
    min_translation_length: int = 4
    max_terms: int = 300
    max_translation_rows: int = 300
    include_glossary: bool = True
    include_translation_archive: bool = True


class AnnouncementTaskCreateRequest(BaseModel):
    source_artifact_id: str | None = None
    text: str = ""
    title: str = ""
    languages: list[str] = Field(default_factory=list)
    language_table_artifact_ids: list[str] = Field(default_factory=list)
    constraint_artifact_ids: list[str] = Field(default_factory=list)
    include_project_archive: bool = True
    output_policy: str = "same_format"


class AnnouncementTaskCancelRequest(BaseModel):
    expected_statuses: list[str] = Field(default_factory=list)


class AnnouncementTaskActionRequest(BaseModel):
    languages: list[str] = Field(default_factory=list)
    language_table_artifact_ids: list[str] = Field(default_factory=list)
    constraint_artifact_ids: list[str] = Field(default_factory=list)
    include_project_archive: bool = True
    announcement_min_hit: int = 1
    generate_validation: bool = True
    confirm_languages: bool = False
    ai_supplement: bool = True
    ai_supplement_response_artifact_id: str | None = None




class AnnouncementTaskTermsRequest(BaseModel):
    languages: list[str] = Field(default_factory=list)
    terms_artifact_id: str | None = None
    terms: list[dict[str, Any]] = Field(default_factory=list)
    generate_validation: bool = True


class AnnouncementTaskTranslateRequest(BaseModel):
    languages: list[str] = Field(default_factory=list)
    provider: str | None = None
    protocol: str | None = None
    batch_size: int | None = None
    confirm_api_budget: bool = False


class AnnouncementTaskImportAiRequest(BaseModel):
    languages: list[str] = Field(default_factory=list)
    response_artifact_ids: list[str] = Field(default_factory=list)
    response_artifacts_by_language: dict[str, str] = Field(default_factory=dict)


class AnnouncementTaskApplyRequest(BaseModel):
    languages: list[str] = Field(default_factory=list)
    translation_workbook_artifact_id: str | None = None


class AnnouncementTaskDeliverRequest(BaseModel):
    languages: list[str] = Field(default_factory=list)
    date_stamp: str | None = None
    force: bool = False


class AnnouncementTermsRequest(BaseModel):
    text: str = ""
    material_artifact_ids: list[str] = Field(default_factory=list)
    language_table_artifact_ids: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    announcement_min_hit: int = 1
    generate_validation: bool = True
    ai_supplement: bool = True
    ai_supplement_response_artifact_id: str | None = None


class AnnouncementDocxPrepareRequest(BaseModel):
    source_artifact_ids: list[str] = Field(default_factory=list)
    terms_artifact_id: str
    languages: list[str] = Field(default_factory=list)


class AnnouncementDocxImportAiRequest(BaseModel):
    prepare_run_id: str
    response_artifact_ids: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)


class AnnouncementDocxApplyRequest(BaseModel):
    prepare_run_id: str
    translation_workbook_artifact_id: str | None = None


class AnnouncementDocxDeliverRequest(BaseModel):
    prepare_run_id: str
    date_stamp: str | None = None


class RunCreate(BaseModel):
    project_id: str
    kind: str = "translation"
    language: str = "en"
    input_artifact_id: str | None = None
    term_artifact_id: str | None = None
    reference_artifact_ids: list[str] = Field(default_factory=list)
    batch_size: int | None = None
    task_origin: str | None = None
    source_run_id: str | None = None
    task_code: str | None = None
    translation_task_id: str | None = None


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
    ai_candidate_supplement: bool = True
    project_material_artifact_ids: list[str] = Field(default_factory=list)
    project_notes: list[str] = Field(default_factory=list)
    announcement_material_artifact_ids: list[str] = Field(default_factory=list)
    announcement_only: bool = False
    announcement_min_hit: int = 1
    ai_supplement: bool = False
    ai_supplement_response_artifact_id: str | None = None
    sheet: str | None = None
    id_column: str = "ID"
    source_column: str = "cn"
    target_column: str | None = None
    language: str = "en"
    update_project_prompt: bool = True


class TranslateRequest(BaseModel):
    provider: str | None = None
    protocol: str | None = None
    preset: str | None = None
    batch_size: int | None = None
    confirm_api_budget: bool = False
    confirm_term_gap: bool = False
    large_text_mode: str | None = None
    enable_line_proofread: bool = False


class MultilingualQueueRequest(BaseModel):
    input_artifact_id: str
    languages: list[str] = Field(default_factory=list)
    batch_size: int | None = None
    task_code: str | None = None
    term_artifact_id: str | None = None
    reference_artifact_ids: list[str] = Field(default_factory=list)
    confirm_api_budget: bool = False
    confirm_term_gap: bool = False
    large_text_mode: str | None = None
    enable_line_proofread: bool = False
    translation_task_id: str | None = None


class SettingsUpdate(BaseModel):
    provider: str | None = None
    preset: str | None = None
    protocol: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    batch_size: int | None = None
    max_concurrent_batches: int | None = None
    max_requests_per_minute: int | None = None
    max_estimated_tokens_per_minute: int | None = None
    max_batch_input_tokens: int | None = None
    api_budget_warning_tokens: int | None = None
    max_batch_attempts: int | None = None
    max_concurrent_ai_jobs: int | None = None
    multimodal: dict[str, bool] | None = None
