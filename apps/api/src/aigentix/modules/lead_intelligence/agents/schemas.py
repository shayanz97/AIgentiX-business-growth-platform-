"""Structured outputs requested from the LLM. Kept simple (enums, strings, lists) for schema support;
length/count limits are enforced after parsing in the agents' validation step."""

from typing import Literal

from pydantic import BaseModel, Field

Level = Literal["low", "medium", "high"]
ProfileField = Literal[
    "description",
    "industry",
    "service",
    "target_customer",
    "business_model",
    "customer_interaction",
    "document_workflow",
    "operational_signal",
    "location",
]


class ExtractedAssertion(BaseModel):
    field: ProfileField
    value: str = Field(description="Short statement in your own words (max ~2 sentences).")
    basis: Literal["observed", "inferred"] = Field(
        description="observed = stated on the website; inferred = your interpretation of what is stated."
    )
    confidence: Level
    source_id: str = Field(description="ID of the source the excerpt is copied from, e.g. S2.")
    supporting_excerpt: str = Field(description="Verbatim quote (10-300 characters) copied from that source.")


class ExtractionOutput(BaseModel):
    company_name: str | None = Field(description="Company name as written on the website, or null if unclear.")
    assertions: list[ExtractedAssertion]
    unknown_fields: list[ProfileField] = Field(description="Profile fields the sources do not answer.")


class ProposedOpportunity(BaseModel):
    title: str
    observed_context: str = Field(description="What the cited evidence shows. Facts only.")
    problem_hypothesis: str = Field(description="A hypothesis to validate, phrased as such.")
    supporting_evidence_ids: list[str] = Field(description="Evidence IDs such as E3 that support this.")
    proposed_solution: str
    expected_benefit: str = Field(description="Qualitative; no invented numbers.")
    implementation_complexity: Level
    confidence: Level
    assumptions: list[str]
    validation_questions: list[str] = Field(description="Questions a human must answer before acting.")
    next_step: str


class AuditOutput(BaseModel):
    opportunities: list[ProposedOpportunity] = Field(description="0 to 3 opportunities.")
    no_opportunity_reason: str | None = Field(
        description="If the list is empty (or short), explain what evidence is missing."
    )
