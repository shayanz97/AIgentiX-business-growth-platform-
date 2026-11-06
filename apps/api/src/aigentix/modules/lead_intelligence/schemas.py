import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints, UrlConstraints

from aigentix.modules.lead_intelligence.models import OpportunityStatus, ProjectStatus

ProjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
WebsiteUrl = Annotated[AnyHttpUrl, UrlConstraints(max_length=2048, allowed_schemes=["http", "https"])]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ProjectName
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)] = ""
    target_url: WebsiteUrl | None = Field(default=None, description="Company website to research (used from Sprint 2).")


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str
    target_url: str | None
    status: ProjectStatus
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


# --- Companies ---------------------------------------------------------------------------------------


UrlText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2048)]
CompanyName = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
MAX_IDS = 100


class CompanyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    website_url: UrlText | None = Field(default=None, description="Company website, e.g. https://acme.com")
    name: CompanyName | None = None
    project_id: uuid.UUID | None = Field(default=None, description="Also add the company to this project.")


class CompanyRead(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    canonical_domain: str | None
    website_url: str | None
    industry: str | None
    location: str | None
    short_description: str | None
    created_at: datetime
    updated_at: datetime
    research_status: str | None = Field(description="Status of the most recent research run, if any.")
    latest_run_id: uuid.UUID | None
    last_researched_at: datetime | None


class CompanyCreateResult(BaseModel):
    company: CompanyRead
    created: bool = Field(description="False when an existing company with the same domain was returned.")


class CompanyDetail(CompanyRead):
    profile: dict[str, Any] | None = Field(description="Structured profile from the latest finished research run.")
    profile_run_id: uuid.UUID | None


class CompanyImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csv_text: str = Field(description="CSV file content with a header row containing name and/or website.")
    dry_run: bool = Field(default=True, description="Validate and preview without importing.")
    project_id: uuid.UUID | None = None


class CompanyImportRow(BaseModel):
    line: int
    name: str
    website_url: str | None
    canonical_domain: str | None
    status: Literal["new", "existing", "duplicate_in_file", "invalid"]
    errors: list[str]
    company_id: uuid.UUID | None


class CompanyImportResult(BaseModel):
    dry_run: bool
    total_rows: int
    new: int
    existing: int
    duplicates: int
    invalid: int
    created: int
    linked_to_project: int
    rows: list[CompanyImportRow]


class ProjectCompaniesAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_IDS)


class LinkResult(BaseModel):
    linked: int


# --- Research runs -----------------------------------------------------------------------------------


class ResearchRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_ids: list[uuid.UUID] | None = Field(default=None, max_length=MAX_IDS)
    project_id: uuid.UUID | None = Field(
        default=None, description="Research every company in this project (when company_ids is omitted)."
    )


class StepRead(BaseModel):
    name: str
    state: Literal["done", "current", "pending", "skipped"]
    duration_ms: int | None


class ResearchRunRead(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    company_name: str
    project_id: uuid.UUID | None
    status: str
    current_step: str | None
    progress: int
    steps: list[StepRead]
    attempts: int
    max_attempts: int
    next_attempt_at: datetime | None
    error_type: str | None
    error_message: str | None
    ai_status: str
    audit_summary: str | None
    pages_fetched: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    models_used: list[str]
    prompt_versions: dict[str, str]
    cancel_requested: bool
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class SkippedCompany(BaseModel):
    company_id: uuid.UUID
    reason: Literal["not_found", "no_website", "already_running"]


class ResearchRunStartResult(BaseModel):
    started: list[ResearchRunRead]
    skipped: list[SkippedCompany]


class SourceRead(BaseModel):
    id: uuid.UUID
    source_url: str
    page_title: str | None
    page_category: str
    http_status: int | None
    retrieved_at: datetime
    extraction_status: str
    extraction_error: str | None
    content_hash: str | None


class EvidenceRead(BaseModel):
    id: uuid.UUID
    label: str = Field(description="Short reference (E1, E2, …) within the research run.")
    research_run_id: uuid.UUID
    source_id: uuid.UUID
    source_url: str | None
    observed_fact: str
    supporting_excerpt: str
    evidence_type: str
    basis: Literal["observed", "inferred"]
    confidence: Literal["low", "medium", "high"]
    origin: Literal["deterministic", "llm"]
    created_at: datetime


class EvidenceRef(BaseModel):
    id: uuid.UUID
    label: str
    evidence_type: str
    observed_fact: str
    supporting_excerpt: str
    source_url: str | None
    basis: str
    confidence: str


class OpportunityRead(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    company_name: str
    research_run_id: uuid.UUID
    title: str
    observed_context: str
    problem_hypothesis: str
    proposed_ai_solution: str
    estimated_business_impact: str
    implementation_complexity: Literal["low", "medium", "high"]
    confidence: Literal["low", "medium", "high"]
    assumptions: list[str]
    validation_questions: list[str]
    next_step: str
    quality_flags: list[str]
    status: OpportunityStatus
    reviewer_note: str | None
    reviewed_by_user_id: uuid.UUID | None
    reviewed_at: datetime | None
    evidence: list[EvidenceRef]
    created_at: datetime
    updated_at: datetime


class OpportunityUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: OpportunityStatus | None = None
    reviewer_note: Annotated[str, StringConstraints(max_length=2000)] | None = None


class ResearchResults(BaseModel):
    run: ResearchRunRead
    profile: dict[str, Any]
    sources: list[SourceRead]
    evidence: list[EvidenceRead]
    opportunities: list[OpportunityRead]


class LeadIntelligenceSummary(BaseModel):
    total_companies: int
    research_runs: int
    companies_researched: int
    opportunities_found: int
    failed_runs: int
    active_runs: int
    opportunities_by_status: dict[str, int]
