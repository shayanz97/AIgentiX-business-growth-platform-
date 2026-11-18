"""ICP and scoring profile configuration (validated JSON stored on versioned profile rows)."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Solution categories AIgentiX can deliver, with DE/EN keywords used to relate evidence to them.
SOLUTION_CATEGORIES: dict[str, tuple[str, ...]] = {
    "customer_service_automation": (
        "kundenanfragen", "kundenservice", "kundenkommunikation", "kundenbetreuung", "sendungsanfragen",
        "inquiry", "inquiries", "customer service", "customer support", "support", "ticket", "anfragen",
        "triage", "e-mail-eingang",
    ),
    "document_processing": (
        "dokumentenverarbeitung", "dokumente", "posteingang", "rechnungen", "verträge", "belege", "formulare",
        "schadenmeldung", "document", "invoice", "contracts", "forms", "data extraction", "intake",
    ),
    "workflow_automation": (
        "automatisierung", "automatisieren", "prozessautomatisierung", "digitalisieren", "digitalisierung",
        "auftragsabwicklung", "automation", "workflow", "back-office", "backoffice",
    ),
    "knowledge_assistant": ("wissensdatenbank", "knowledge base", "chatbot", "assistent", "assistant", "faq"),
    "appointment_scheduling": ("terminbuchung", "terminvereinbarung", "appointment", "booking", "scheduling"),
    "sales_crm_automation": ("crm", "angebotserstellung", "lead management", "quote", "angebote anfordern"),
}  # fmt: skip

DEFAULT_EXCLUDED_INDUSTRIES = ["tobacco", "tabak", "gambling", "glücksspiel", "weapons", "waffen", "rüstung"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IcpConfig(_Strict):
    countries: list[str] = Field(default_factory=lambda: ["DE"], max_length=30)
    company_types: list[Literal["b2b", "b2c"]] = Field(default=["b2b", "b2c"], min_length=1)
    min_employees: int | None = Field(default=1, ge=1, le=1_000_000)
    max_employees: int | None = Field(default=249, ge=1, le=1_000_000)  # EU SME definition: < 250 employees
    target_industries: list[str] = Field(default_factory=list, max_length=50)  # empty = any industry
    excluded_industries: list[str] = Field(default_factory=lambda: list(DEFAULT_EXCLUDED_INDUSTRIES), max_length=50)
    solution_categories: list[str] = Field(default_factory=lambda: list(SOLUTION_CATEGORIES), min_length=1)

    @field_validator("countries")
    @classmethod
    def _countries(cls, value: list[str]) -> list[str]:
        cleaned = [v.strip().upper() for v in value]
        if any(len(c) != 2 or not c.isalpha() for c in cleaned):
            raise ValueError("countries must be ISO 3166-1 alpha-2 codes such as DE")
        return sorted(set(cleaned))

    @field_validator("target_industries", "excluded_industries")
    @classmethod
    def _keywords(cls, value: list[str]) -> list[str]:
        cleaned = [v.strip().lower() for v in value if v.strip()]
        if any(len(v) > 60 for v in cleaned):
            raise ValueError("industry keywords must be at most 60 characters")
        return list(dict.fromkeys(cleaned))

    @field_validator("solution_categories")
    @classmethod
    def _categories(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(SOLUTION_CATEGORIES))
        if unknown:
            raise ValueError(f"unknown solution categories; allowed: {', '.join(SOLUTION_CATEGORIES)}")
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _size_range(self) -> Self:
        if self.min_employees and self.max_employees and self.min_employees > self.max_employees:
            raise ValueError("min_employees must not exceed max_employees")
        return self


class Weights(_Strict):
    opportunity: int = Field(default=35, ge=0, le=100)
    fit: int = Field(default=25, ge=0, le=100)
    triggers: int = Field(default=20, ge=0, le=100)
    intent: int = Field(default=20, ge=0, le=100)

    @model_validator(mode="after")
    def _sum(self) -> Self:
        if self.opportunity + self.fit + self.triggers + self.intent != 100:
            raise ValueError("weights must sum to 100")
        return self


class FreshnessBands(_Strict):
    """Upper bounds (days since the event) of each band; older than `older` is historical."""

    recent: int = Field(default=30, ge=1, le=3650)
    moderate: int = Field(default=90, ge=1, le=3650)
    older: int = Field(default=180, ge=1, le=3650)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.recent < self.moderate < self.older:
            raise ValueError("freshness bands must be increasing: recent < moderate < older")
        return self


class FreshnessFactors(_Strict):
    """Multipliers applied to a trigger's value by freshness band."""

    recent: float = Field(default=1.0, ge=0, le=1)
    moderate: float = Field(default=0.7, ge=0, le=1)
    older: float = Field(default=0.4, ge=0, le=1)
    historical: float = Field(default=0.1, ge=0, le=1)
    unknown: float = Field(default=0.3, ge=0, le=1)  # an undated item is never treated as current


class PriorityThresholds(_Strict):
    high: float = Field(default=60, ge=0, le=100)
    medium: float = Field(default=35, ge=0, le=100)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.medium > self.high:
            raise ValueError("the medium threshold must not exceed the high threshold")
        return self


class ScoringConfig(_Strict):
    weights: Weights = Field(default_factory=Weights)
    freshness_bands: FreshnessBands = Field(default_factory=FreshnessBands)
    freshness_factors: FreshnessFactors = Field(default_factory=FreshnessFactors)
    thresholds: PriorityThresholds = Field(default_factory=PriorityThresholds)
    # Below this share of assessed weight a score is labelled provisional.
    min_coverage: float = Field(default=0.75, ge=0, le=1)
