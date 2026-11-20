"""FixtureSalesLLM: deterministic, rule-based stand-in for the Sales AI tasks (never used in production — enforced
by SalesSettings). It reads only the prompt it is given (labelled evidence E1.. and the other data blocks) and
answers with transparent rules: observed statements are copied from evidence it cites, everything else is a
hedged hypothesis, and with no evidence it states nothing factual. Evidence that looks like an instruction is
treated as data and never acted on. Model label "fixture-sales-v1", zero cost. Not AI analysis.
"""

import json
import re
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from aigentix.modules.sales.agents.schemas import BriefOutput, ProposalOutput, ProposalSectionOutput, Statement
from aigentix.platform.llm import LLMResponse, LLMUsage, Task

FIXTURE_SALES_MODEL = "fixture-sales-v1"
_INSTRUCTION = re.compile(
    r"(?i)(ignore (?:all|any|previous|the above|prior)|ignoriere|disregard|system prompt|you are now|new instructions"
    r"|neue anweisung|assistant:|\bai model\b|ki-modell|instructions?\b)"
)
_CONFIRM = "[TO BE CONFIRMED WITH CUSTOMER]"


def _block(prompt: str, tag: str) -> Any:
    match = re.search(rf"<{tag}>\n(.*?)\n</{tag}>", prompt, re.S)
    return json.loads(match.group(1)) if match else None


def _safe(text: str) -> bool:
    return not _INSTRUCTION.search(text)


class FixtureSalesLLM:
    name = "fixture"

    def model_for(self, task: Task) -> str:
        return FIXTURE_SALES_MODEL

    def structured[T: BaseModel](
        self, *, task: Task, system: str, messages: list[dict[str, Any]], output_model: type[T], max_tokens: int
    ) -> LLMResponse[T]:
        prompt = str(messages[-1]["content"])
        output: BaseModel
        if output_model is BriefOutput:
            output = self._brief(prompt)
        elif output_model is ProposalOutput:
            output = self._proposal(prompt)
        else:  # pragma: no cover - programming error
            raise AssertionError(f"FixtureSalesLLM cannot answer {output_model.__name__}")
        usage = LLMUsage(
            model=FIXTURE_SALES_MODEL,
            input_tokens=len(prompt) // 4,
            output_tokens=len(output.model_dump_json()) // 4,
            cost_usd=Decimal(0),
        )
        return LLMResponse(output=output, usage=usage)  # type: ignore[arg-type]

    # --- brief ------------------------------------------------------------------------------------------------

    def _brief(self, prompt: str) -> BriefOutput:
        profile: dict[str, Any] = _block(prompt, "company_profile") or {}
        evidence: list[dict[str, Any]] = [
            e for e in (_block(prompt, "evidence") or []) if _safe(f"{e['fact']} {e['excerpt']}")
        ]
        opportunities: list[dict[str, Any]] = _block(prompt, "research_opportunities") or []
        signals: list[dict[str, Any]] = _block(prompt, "signals") or []
        intents: list[dict[str, Any]] = _block(prompt, "buying_intent") or []
        requirements: list[str] = _block(prompt, "confirmed_requirements") or []
        offerings: list[dict[str, Any]] = _block(prompt, "service_offerings") or []
        gaps: list[str] = _block(prompt, "known_gaps") or []
        valid = {e["id"] for e in evidence}

        def quote(e: dict[str, Any]) -> Statement:
            text = e["fact"] if e["origin"] == "deterministic" else e["excerpt"]
            return Statement(text=text, evidence=[e["id"]], basis="observed")

        description = next((e for e in evidence if e["type"] == "company_description"), None)
        summary = (
            quote(description)
            if description
            else Statement(text=profile.get("name") or "Unknown company", evidence=["PROFILE"], basis="observed")
        )
        observed = [quote(e) for e in evidence if e["type"] != "company_description" and not e["older_than_180_days"]]

        title, main, solution_hint = self._main_opportunity(opportunities, intents, signals, valid)
        cited = [e for e in evidence if e["id"] in main.evidence]
        impact = [
            Statement(
                text=o["estimated_business_impact"],
                evidence=[x for x in o["evidence"] if x in valid],
                basis="hypothesis",
            )
            for o in opportunities[:1]
            if o["estimated_business_impact"] and _safe(o["estimated_business_impact"])
        ] or [
            Statement(
                text="Less manual effort in the process concerned may be possible, if volumes are meaningful.",
                evidence=[],
                basis="hypothesis",
            )
        ]
        offering = offerings[0]["name"] if offerings else None
        solution = Statement(
            text=f"Offer the service '{offering}' as a starting point, to be validated in discovery."
            if offering
            else solution_hint,
            evidence=[],
            basis="hypothesis",
        )
        questions = [q for o in opportunities[:1] for q in o["validation_questions"] if _safe(q)]
        questions += ["Who owns this process today, and how is it handled?", "Which systems are involved?"]
        return BriefOutput(
            company_summary=summary,
            observed_situation=observed[:5],
            main_opportunity_title=title,
            main_opportunity=main,
            supporting_evidence=[quote(e) for e in cited[:4]],
            assumptions_and_uncertainty=gaps[:6]
            or ["The evidence reflects the public website only; internal processes are unknown."],
            potential_impact=impact,
            suggested_solution=solution,
            implementation_requirements=[*requirements, "Access to the systems involved, to be confirmed."],
            discovery_questions=questions,
            recommended_next_action="Review the evidence and prepare discovery questions.",
        )

    @staticmethod
    def _main_opportunity(
        opportunities: list[dict[str, Any]],
        intents: list[dict[str, Any]],
        signals: list[dict[str, Any]],
        valid: set[str],
    ) -> tuple[str, Statement, str]:
        for o in opportunities:
            if _safe(o["title"] + o["problem_hypothesis"]):
                labels = [x for x in o["evidence"] if x in valid]
                return (
                    o["title"],
                    Statement(text=o["problem_hypothesis"], evidence=labels, basis="hypothesis"),
                    (o["proposed_ai_solution"]),
                )
        for i in intents:
            labels = [x for x in i["evidence"] if x in valid]
            if not i["deadline_passed"] and labels and _safe(i["title"]):
                return (
                    f"Respond to the published need: {i['title']}",
                    Statement(text=f"The company published: {i['title']}.", evidence=labels, basis="observed"),
                    "A solution scoped to the published request, to be validated with the customer.",
                )
        for s in signals:
            labels = [x for x in s["evidence"] if x in valid]
            if not s["older_than_180_days"] and labels and _safe(s["title"]):
                return (
                    f"Follow up on the {s['type']} trigger",
                    Statement(
                        text=f"The {s['type']} trigger ({s['title']}) may create demand for process automation.",
                        evidence=labels,
                        basis="hypothesis",
                    ),
                    "An automation pilot for the process affected by this change, to be validated.",
                )
        return (
            "No specific opportunity identified",
            Statement(
                text="The evidence does not show a specific automation need yet.", evidence=[], basis="hypothesis"
            ),
            "An exploratory discovery conversation before any solution is proposed.",
        )

    # --- proposal ---------------------------------------------------------------------------------------------

    def _proposal(self, prompt: str) -> ProposalOutput:
        profile: dict[str, Any] = _block(prompt, "company_profile") or {}
        brief: dict[str, Any] = _block(prompt, "sales_brief") or {}
        hypotheses: list[str] = _block(prompt, "hypotheses") or []
        requirements: list[str] = _block(prompt, "confirmed_requirements") or []
        offerings: list[dict[str, Any]] = _block(prompt, "service_offerings") or []
        company = profile.get("name") or "the customer"
        title = brief.get("main_opportunity_title") or "process automation"
        main = brief.get("main_opportunity") or {}
        opportunity = main.get("text") or ""
        hedge = "Hypothesis to validate: " if main.get("basis") == "hypothesis" else ""
        observed = [s["text"] for s in brief.get("observed_situation") or [] if _safe(s["text"])][:3]
        summary = (brief.get("company_summary") or {}).get("text") or company
        impact = [s["text"] for s in brief.get("potential_impact") or [] if _safe(s["text"])]
        solution = (brief.get("suggested_solution") or {}).get("text") or ""
        names = [o["name"] for o in offerings]

        def section(key: str, title_: str, body: str, status: str = "draft") -> ProposalSectionOutput:
            return ProposalSectionOutput(key=key, title=title_, body=body, status=status, evidence=[])

        scope = "\n".join(f"- {r}" for r in requirements) if requirements else f"{_CONFIRM} Scope to be agreed."
        criteria = (
            "\n".join(f"- Requirement met: {r}" for r in requirements)
            if requirements
            else f"{_CONFIRM} Success criteria."
        )
        return ProposalOutput(
            sections=[
                section(
                    "executive_summary",
                    "Executive summary",
                    f"This draft outlines how {company} could address: {title}. It is based on public information "
                    "and must be validated with the customer.",
                ),
                section("business_context", "Business context", "\n".join([summary, *observed])),
                section(
                    "identified_opportunity",
                    "Identified opportunity",
                    f"{hedge}{opportunity}" if opportunity else f"{_CONFIRM} Opportunity.",
                    "draft" if opportunity else "needs_input",
                ),
                section(
                    "proposed_solution",
                    "Proposed solution",
                    "\n".join([solution, *(f"- {n}" for n in names)]).strip() or f"{_CONFIRM} Solution.",
                ),
                section(
                    "scope_and_deliverables",
                    "Scope and deliverables",
                    scope,
                    "draft" if requirements else "needs_input",
                ),
                section(
                    "implementation_approach",
                    "Implementation approach",
                    "Phase 1: discovery workshop to confirm the process.\nPhase 2: pilot on a limited scope.\n"
                    "Phase 3: joint review and decision on rollout.",
                ),
                section(
                    "customer_dependencies",
                    "Customer dependencies",
                    f"A process owner and access to the systems involved. {_CONFIRM}",
                    "needs_input",
                ),
                section("assumptions", "Assumptions", "\n".join(f"- {h}" for h in hypotheses) or "- None recorded."),
                section(
                    "expected_benefits",
                    "Expected benefits",
                    "\n".join(f"- {t}" for t in impact) or "Benefits may include less manual effort; to be validated.",
                ),
                section("success_criteria", "Success criteria", criteria, "draft" if requirements else "needs_input"),
                section("timeline_estimate", "Timeline estimate", f"{_CONFIRM} Timeline.", "needs_input"),
                section("commercial_terms", "Commercial terms", "Filled in by the system.", "needs_input"),
                section(
                    "next_steps",
                    "Next steps",
                    "Review this draft internally, confirm the open points with the customer, then decide whether "
                    "to send it.",
                ),
            ],
            assumptions=["The draft is based on public information and the confirmed requirements only."],
        )
