"""Lead-scoring evaluation over the 16 enrichment fixture scenarios (see .claude/skills/lead-scoring-eval).

Each scenario is researched (Sprint 2 pipeline) and enriched (Sprint 3 workflow), then checked against its
`expected.json`: detected trigger types and counts, event dates, date conflicts, freshness, intent strength, ICP
country / fit, score band, prompt-injection containment and evidence integrity (every scored criterion cites
evidence of the same company, and every signal excerpt is verbatim in its stored source).

Default: deterministic pipeline + FixtureLLMProvider (CI-safe, free). Live mode (LEAD_SCORING_EVAL_LIVE=1 plus a
provider key) uses the configured routes for research and the AI trigger review, and stops starting new scenarios
once LEAD_SCORING_EVAL_MAX_COST_USD (default 1.00) is spent. Set LEAD_SCORING_EVAL_REPORT=<path> for a report.

The numbers this produces are fixture results: they measure the pipeline against the scenarios we wrote, not
real-world accuracy or conversion.
"""

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from aigentix.modules.lead_intelligence.agents.text_safety import excerpt_in_source
from aigentix.modules.lead_intelligence.config import ResearchSettings
from aigentix.modules.lead_intelligence.integrations.fixture_web import ENRICHMENT_FIXTURE_ROOT, fixture_domains
from aigentix.modules.lead_intelligence.integrations.llm import build_provider
from aigentix.modules.lead_intelligence.models import Evidence, ResearchSource
from tests.conftest import Tenant
from tests.research_helpers import (
    FIXTURE_SETTINGS,
    REFERENCE_DATE,
    client_get,
    enrich,
    research_company,
    research_registry,
)

LIVE = os.environ.get("LEAD_SCORING_EVAL_LIVE") == "1"
MAX_LIVE_COST = Decimal(os.environ.get("LEAD_SCORING_EVAL_MAX_COST_USD", "1.00"))
FIRST_PARTY = json.loads((ENRICHMENT_FIXTURE_ROOT.parent / "first_party.json").read_text())


@dataclass
class Case:
    domain: str
    scenario: str
    status: str
    checks: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    score: str = ""
    intent: str = ""
    signals: str = ""
    cost: float = 0.0
    breakdown: str = ""

    @property
    def passed(self) -> bool:
        return all(self.checks.values())


def _expected(domain: str) -> dict[str, Any]:
    return json.loads((ENRICHMENT_FIXTURE_ROOT / domain / "expected.json").read_text())  # type: ignore[no-any-return]


def _fit_band(score: dict[str, Any]) -> str:
    if score["fit_excluded"]:
        return "excluded"
    fit = next(c for c in score["components"] if c["key"] == "fit")
    return "high" if fit["score_low"] >= 70 else "medium" if fit["score_low"] >= 40 else "low"


def _check(case: Case, name: str, ok: bool, note: str) -> None:
    case.checks[name] = ok
    if not ok:
        case.notes.append(note)


def evaluate(t: Tenant, domain: str, company_id: str, view: dict[str, Any], db: Session) -> Case:
    exp = _expected(domain)
    run = view["enrichment_run"] or {}
    case = Case(domain=domain, scenario=exp["scenario"], status=run.get("status", "none"))
    finished = case.status in ("completed", "partial")
    _check(case, "outcome", (exp["expected_outcome"] == "completed") == finished, f"run {case.status}")

    score_page = client_get(t.client, f"/api/v1/companies/{company_id}/scores", t.headers)
    if not score_page["items"]:  # a failed enrichment does not score; score from stored data, as a user would
        t.client.post(f"/api/v1/companies/{company_id}/score", json={}, headers=t.headers)
        score_page = client_get(t.client, f"/api/v1/companies/{company_id}/scores", t.headers)
    score = score_page["items"][0]
    case.score = f"{score['score_low']:.0f}-{score['score_high']:.0f} ({score['coverage']:.0%})"
    case.intent = view["intent_status"]

    signals = view["signals"]
    by_type: dict[str, list[dict[str, Any]]] = {}
    for s in signals:
        by_type.setdefault(s["signal_type"], []).append(s)
    case.signals = ", ".join(f"{k}×{len(v)}" for k, v in sorted(by_type.items())) or "none"
    missing = set(exp["expected_signal_types"]) - set(by_type)
    _check(case, "expected_signals", not missing, f"missing {sorted(missing)}")
    forbidden = set(exp["forbidden_signal_types"]) & set(by_type)
    _check(case, "no_forbidden_signals", not forbidden, f"forbidden {sorted(forbidden)}")
    unexpected = set(by_type) - set(exp["expected_signal_types"])
    _check(case, "no_unexpected_signals", not unexpected, f"unexpected {sorted(unexpected)}")
    for kind, count in exp["expected_signal_count"].items():
        _check(case, f"count_{kind}", len(by_type.get(kind, [])) == count, f"{kind}: {len(by_type.get(kind, []))}")
    for kind, expected_date in exp["expected_dates"].items():
        got = [s["occurred_on"] for s in by_type.get(kind, [])]
        _check(case, f"date_{kind}", expected_date in got, f"{kind} date {got} ≠ {expected_date}")
    conflicts = any(s["date_conflict"] for s in signals)
    _check(case, "date_conflict", conflicts == exp["expected_date_conflict"], f"date conflict {conflicts}")
    for kind, band in exp["expected_freshness"].items():
        got = [s["freshness"] for s in by_type.get(kind, [])]
        _check(case, f"freshness_{kind}", band in got, f"{kind} freshness {got} ≠ {band}")
    _check(
        case,
        "intent",
        view["intent_status"] == exp["expected_intent_strength"],
        f"intent {view['intent_status']} ≠ {exp['expected_intent_strength']}",
    )

    fit_band = _fit_band(score)
    _check(case, "fit", fit_band == exp["expected_fit"], f"fit {fit_band} ≠ {exp['expected_fit']}")
    band = "low" if score["priority_band"] == "excluded" else score["priority_band"]
    _check(case, "score_band", band == exp["expected_score_band"], f"band {band} ≠ {exp['expected_score_band']}")
    if exp.get("expected_company_size_conflict"):
        size = next(c for c in score["components"] if c["key"] == "fit")["criteria"][2]
        _check(case, "size_conflict", size["state"] == "insufficient_evidence", f"size state {size['state']}")
    if "expected_company_size" in exp and exp["expected_company_size"] is None:
        size = next(c for c in score["components"] if c["key"] == "fit")["criteria"][2]
        _check(case, "size_unknown", size["state"] != "assessed", f"size state {size['state']}")
    if exp.get("expected_country"):
        country = next(c for c in score["components"] if c["key"] == "fit")["criteria"][0]
        expected_code = {"Germany": "DE", "USA": "US"}.get(exp["expected_country"], exp["expected_country"])
        _check(case, "country", expected_code in country["explanation"], f"country: {country['explanation']}")

    # Evidence integrity: criteria cite evidence of this company; signal excerpts are verbatim in their source.
    cited = {e for c in score["components"] for cr in c["criteria"] for e in cr["evidence_ids"]}
    rows = {str(e.id): e for e in db.scalars(select(Evidence).where(Evidence.company_id == company_id))}
    _check(case, "criteria_cite_company_evidence", cited <= set(rows), "criterion cites unknown evidence")
    for c in score["components"]:
        for cr in c["criteria"]:
            if cr["state"] == "assessed" and (cr["points"] or 0) > 0 and c["key"] in ("triggers", "intent"):
                _check(case, f"evidence_{c['key']}", bool(cr["evidence_ids"] or cr["references"]), "no evidence")
    sources = {s.id: s.extracted_text for s in db.scalars(select(ResearchSource))}
    signal_evidence = [rows[str(e["id"])] for s in signals for e in s["evidence"]]
    verbatim = all(excerpt_in_source(e.supporting_excerpt, sources[e.source_id]) for e in signal_evidence)
    _check(case, "signal_excerpts_verbatim", verbatim, "non-verbatim excerpt")
    text = json.dumps(view) + json.dumps(score)
    payload = [u for u in [*exp.get("forbidden_urls", []), "evil.example"] if u in text]
    _check(case, "no_injection_payload", not payload, f"payload leaked {payload}")
    case.cost = float(run.get("estimated_cost_usd") or 0)
    case.breakdown = " · ".join(
        f"{c['key']} {c['score_low']:.0f}-{c['score_high']:.0f}"
        + (
            " [" + ", ".join(f"{cr['key']}={cr['state'][:4]}:{cr['points']}" for cr in c["criteria"]) + "]"
            if c["key"] == "fit"
            else ""
        )
        for c in score["components"]
    )
    return case


def write_report(cases: list[Case], mode: str) -> str:
    lines = [
        f"# Lead-scoring evaluation ({mode}, reference date {REFERENCE_DATE.isoformat()})",
        "",
        "| Company | Scenario | Run | Signals | Intent | Score (coverage) | Checks | Notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in cases:
        failed = [k for k, v in c.checks.items() if not v]
        verdict = "PASS" if c.passed else "FAIL: " + ", ".join(failed)
        lines.append(
            f"| {c.domain} | {c.scenario} | {c.status} | {c.signals} | {c.intent} | {c.score} | {verdict} "
            f"| {'; '.join(c.notes)} |"
        )
    total_checks = sum(len(c.checks) for c in cases)
    passed_checks = sum(sum(c.checks.values()) for c in cases)
    lines += [
        "",
        f"Scenarios passed: {sum(c.passed for c in cases)}/{len(cases)} · checks passed {passed_checks}/{total_checks}"
        f" · total cost ${sum(c.cost for c in cases):.4f}",
        "",
        "Fixture results only: they do not measure real-world accuracy, precision or conversion.",
    ]
    report = "\n".join(lines)
    if path := os.environ.get("LEAD_SCORING_EVAL_REPORT"):
        Path(path).write_text(report + "\n", encoding="utf-8")
    return report


def _run_suite(t: Tenant, db: Session, registry_kwargs: dict[str, Any], mode: str) -> list[Case]:
    cases: list[Case] = []
    spent = Decimal(0)
    for domain in fixture_domains(ENRICHMENT_FIXTURE_ROOT):
        if LIVE and spent >= MAX_LIVE_COST:
            break
        registry = research_registry(**registry_kwargs)
        run, _ = research_company(t, domain, registry)
        company_id = run["company_id"]
        spent += Decimal(str(run["estimated_cost_usd"]))
        for record in (r for r in FIRST_PARTY if r["company_domain"] == domain):
            response = t.client.post(
                f"/api/v1/companies/{company_id}/intent-signals",
                json={"channel": record["channel"], "received_on": record["received_at"], "summary": record["summary"]},
                headers=t.headers,
            )
            assert response.status_code == 201, response.text
        view = enrich(t, company_id, registry)
        spent += Decimal(str((view["enrichment_run"] or {}).get("estimated_cost_usd") or 0))
        cases.append(evaluate(t, domain, company_id, view, db))
    print("\n" + write_report(cases, mode))

    return cases


def test_lead_scoring_fixture_suite(tenant_a: Tenant, db: Session) -> None:
    cases = _run_suite(tenant_a, db, {}, "fixture-rules-v1 test double")
    assert len(cases) >= 15
    failures = {c.domain: c.notes for c in cases if not c.passed}
    assert not failures, failures
    # Ranking sanity: verified active intent ranks above weak / excluded / unresearchable leads.
    ranked = client_get(tenant_a.client, "/api/v1/leads/ranked?limit=50", tenant_a.headers)["items"]
    order = [lead["canonical_domain"] for lead in ranked]
    top = order[:4]
    for domain in ("kundenservice-anfrage.example", "vielfalt-gmbh.example", "digitalwerk-solutions.example"):
        assert domain in top, order
    bottom = order[len(order) // 2 :]
    for domain in ("tabak-usa.example", "kleinbetrieb-minimal.example", "ungueltige-firma.example"):
        assert domain in bottom, order


@pytest.mark.skipif(not LIVE, reason="live evaluation is opt-in (LEAD_SCORING_EVAL_LIVE=1 + a provider API key)")
def test_lead_scoring_live(tenant_a: Tenant, db: Session) -> None:  # pragma: no cover - needs credentials
    settings = ResearchSettings(
        environment="test",
        research_fetch_backend="fixtures",
        research_domain_min_interval_seconds=0,
        research_tender_source="fixtures",
        scoring_reference_date=REFERENCE_DATE,
        llm_max_cost_per_run_usd=MAX_LIVE_COST,
    )
    provider = build_provider(settings)
    if provider is None:
        pytest.skip("No API key is configured for the routed provider(s)")
    cases = _run_suite(tenant_a, db, {"provider": lambda: provider, "settings": settings}, "live")
    hard = ("outcome", "no_forbidden_signals", "criteria_cite_company_evidence", "signal_excerpts_verbatim")
    assert all(c.checks.get(k, True) for c in cases for k in (*hard, "no_injection_payload"))


assert FIXTURE_SETTINGS.scoring_reference_date == REFERENCE_DATE
