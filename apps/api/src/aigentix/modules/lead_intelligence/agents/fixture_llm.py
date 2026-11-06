"""Deterministic LLM test doubles (never used in production — enforced by ResearchSettings).

* FixtureLLMProvider: rule-based stand-in used by CI, E2E and offline demos. It reads the same prompts the
  real model gets and answers with simple, transparent rules, labelled model "fixture-rules-v1" with zero cost.
  Its output is not AI analysis and the UI shows the model name.
* ScriptedLLMProvider: returns pre-written outputs (or raises errors) in order — for testing validation,
  repair and failure handling.
"""

import json
import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from aigentix.modules.lead_intelligence.agents.schemas import (
    AuditOutput,
    ExtractedAssertion,
    ExtractionOutput,
    ProposedOpportunity,
)
from aigentix.modules.lead_intelligence.integrations.llm import LLMResponse, LLMUsage, Task

FIXTURE_MODEL = "fixture-rules-v1"
_SOURCE = re.compile(r'<website_content source_id="(S\d+)" page_type="(\w+)"[^>]*>\n(.*?)\n</website_content>', re.S)
_EVIDENCE = re.compile(r"<evidence>\n(.*?)\n</evidence>", re.S)
_SENTENCE = re.compile(r"(?:^|(?<=[.!?] ))[A-Z][^.!?]{40,240}[.!?]")

_TEMPLATES: list[tuple[set[str], dict[str, str]]] = [
    (
        {"contact_form", "quote_request_form", "customer_support", "faq", "live_chat"},
        {
            "title": "AI-assisted triage of incoming customer inquiries",
            "problem": "Inquiries arriving through web forms and support channels may need manual sorting before "
            "they reach the right person.",
            "solution": "Classify incoming inquiries by topic and urgency, draft answers to common questions from "
            "the FAQ, and route the rest to the right team.",
            "benefit": "Faster first responses and less time spent sorting messages, if inquiry volume is meaningful.",
        },
    ),
    (
        {"online_booking"},
        {
            "title": "Automated appointment scheduling assistance",
            "problem": "Appointment requests and changes may require back-and-forth with staff.",
            "solution": "An assistant that answers availability questions, books and reschedules appointments, and "
            "sends reminders.",
            "benefit": "Fewer missed appointments and less staff time on scheduling, if booking volume is high.",
        },
    ),
    (
        {"document_download", "document_workflow"},
        {
            "title": "Document intake and data extraction",
            "problem": "Forms and documents submitted by customers may be re-keyed into internal systems.",
            "solution": "Extract fields from submitted documents and forms, validate them and pre-fill records "
            "for staff review.",
            "benefit": "Less re-typing and fewer data-entry errors, if document volume is significant.",
        },
    ),
    (
        {"ecommerce"},
        {
            "title": "Order and returns self-service assistant",
            "problem": "Customers may ask repetitive questions about order status, shipping and returns.",
            "solution": "A support assistant grounded in the shipping and returns policy that answers order "
            "questions and hands off exceptions.",
            "benefit": "Shorter wait times for routine order questions.",
        },
    ),
]


def _zero_usage() -> LLMUsage:
    return LLMUsage(model=FIXTURE_MODEL, input_tokens=0, output_tokens=0, cost_usd=Decimal(0))


class FixtureLLMProvider:
    name = "fixture"

    def model_for(self, task: Task) -> str:
        return FIXTURE_MODEL

    def structured[T: BaseModel](
        self,
        *,
        task: Task,
        system: str,
        messages: list[dict[str, Any]],
        output_model: type[T],
        max_tokens: int,
    ) -> LLMResponse[T]:
        prompt = str(messages[-1]["content"])
        if output_model is ExtractionOutput:
            output: BaseModel = self._extract(prompt)
        elif output_model is AuditOutput:
            output = self._audit(prompt)
        else:  # pragma: no cover - programming error
            raise TypeError(f"Unsupported output model {output_model}")
        return LLMResponse(output=output, usage=_zero_usage())  # type: ignore[arg-type]

    def _extract(self, prompt: str) -> ExtractionOutput:
        assertions: list[ExtractedAssertion] = []
        for label, page_type, text in _SOURCE.findall(prompt):
            sentence = _SENTENCE.search(text)
            if sentence and page_type in ("home", "about", "services"):
                quote = sentence.group(0).strip()
                field = "description" if page_type in ("home", "about") else "service"
                assertions.append(
                    ExtractedAssertion(
                        field=field,
                        value=quote,
                        basis="observed",
                        confidence="medium",
                        source_id=label,
                        supporting_excerpt=quote,
                    )
                )
        return ExtractionOutput(company_name=None, assertions=assertions[:6], unknown_fields=["industry"])

    def _audit(self, prompt: str) -> AuditOutput:
        match = _EVIDENCE.search(prompt)
        evidence: list[dict[str, str]] = json.loads(match.group(1)) if match else []
        opportunities: list[ProposedOpportunity] = []
        for types, template in _TEMPLATES:
            cited = [e for e in evidence if e["type"] in types][:3]
            if not cited:
                continue
            facts = " ".join(e["fact"] for e in cited)[:600]
            opportunities.append(
                ProposedOpportunity(
                    title=template["title"],
                    observed_context=facts,
                    problem_hypothesis=template["problem"],
                    supporting_evidence_ids=[e["id"] for e in cited],
                    proposed_solution=template["solution"],
                    expected_benefit=template["benefit"],
                    implementation_complexity="medium",
                    confidence="medium" if len(cited) >= 2 else "low",
                    assumptions=["The process shown on the website is used regularly."],
                    validation_questions=[
                        "How many of these requests does the company handle per week?",
                        "Which systems are used today to handle them?",
                    ],
                    next_step="Interview the process owner to confirm volumes and current tooling.",
                )
            )
            if len(opportunities) == 3:
                break
        reason = None if opportunities else "The website shows no customer-facing process that suggests automation."
        return AuditOutput(opportunities=opportunities, no_opportunity_reason=reason)


Step = BaseModel | Exception | Callable[[str], BaseModel]


class ScriptedLLMProvider:
    """Returns the queued items in order: a model instance, an exception to raise, or fn(prompt)->model."""

    name = "scripted"

    def __init__(self, steps: list[Step], *, cost_per_call: Decimal = Decimal("0.001")) -> None:
        self.steps = list(steps)
        self.calls: list[dict[str, Any]] = []
        self.cost_per_call = cost_per_call

    def model_for(self, task: Task) -> str:
        return f"scripted-{task}"

    def structured[T: BaseModel](
        self,
        *,
        task: Task,
        system: str,
        messages: list[dict[str, Any]],
        output_model: type[T],
        max_tokens: int,
    ) -> LLMResponse[T]:
        self.calls.append({"task": task, "system": system, "messages": messages})
        if not self.steps:
            raise AssertionError("ScriptedLLMProvider ran out of scripted responses")
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        output = step(str(messages[-1]["content"])) if callable(step) and not isinstance(step, BaseModel) else step
        usage = LLMUsage(model=f"scripted-{task}", input_tokens=100, output_tokens=50, cost_usd=self.cost_per_call)
        return LLMResponse(output=output, usage=usage)  # type: ignore[arg-type]
