"""Structured outputs requested from the LLM. Kept simple (enums, strings, lists) for schema support;
length/count limits and every grounding rule are enforced after parsing (agents/validation.py)."""

from typing import Literal

from pydantic import BaseModel, Field

Basis = Literal["observed", "hypothesis"]


class Statement(BaseModel):
    text: str = Field(description="One or two sentences.")
    evidence: list[str] = Field(description="Evidence labels such as E3 (or PROFILE) that support the statement.")
    basis: Basis = Field(description="observed = the cited evidence states it; hypothesis = interpretation.")


class BriefOutput(BaseModel):
    company_summary: Statement
    observed_situation: list[Statement] = Field(description="What the evidence shows today (observed facts).")
    main_opportunity_title: str
    main_opportunity: Statement
    supporting_evidence: list[Statement] = Field(description="The key evidence behind the main opportunity.")
    assumptions_and_uncertainty: list[str]
    potential_impact: list[Statement] = Field(description="Qualitative; usually hypotheses.")
    suggested_solution: Statement
    implementation_requirements: list[str]
    discovery_questions: list[str]
    recommended_next_action: str = Field(description="An internal human action, never automatic outreach.")


SectionStatus = Literal["draft", "needs_input"]


class ProposalSectionOutput(BaseModel):
    key: str
    title: str
    body: str = Field(description="Plain text or simple Markdown.")
    status: SectionStatus
    evidence: list[str] = Field(description="Evidence labels the section relies on (may be empty).")


class ProposalOutput(BaseModel):
    sections: list[ProposalSectionOutput]
    assumptions: list[str] = Field(description="Hypotheses and assumptions the customer must confirm.")
