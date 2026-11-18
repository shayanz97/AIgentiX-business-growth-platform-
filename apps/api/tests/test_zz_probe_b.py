import uuid
from aigentix.platform.leads import get_lead_data_provider
from tests.sales_helpers import qualified_lead


def test_probe(tenant_a, db):
    out = []
    for d in [
        "kundenservice-anfrage.example",
        "widerspruch-daten.example",
        "rhein-logistik-expansion.example",
        "kleinbetrieb-minimal.example",
        "injektion-news.example",
        "alte-meldung.example",
    ]:
        lead = qualified_lead(tenant_a, d)
        s = get_lead_data_provider().snapshot(db, tenant_a.org.id, uuid.UUID(lead["company_id"]))
        out.append(
            f"=== {d} {s.name} ind={s.industry} loc={s.location} desc={s.description!r} review={s.review_status}"
        )
        out.append(f"score {s.latest_score}")
        for o in s.opportunities:
            out.append(
                f"OPP {o.title} | {o.status} | {o.confidence} | {o.observed_context[:150]} | {len(o.evidence_ids)}"
            )
        for e in s.evidence:
            out.append(
                f"EV {e.evidence_type} | {e.basis}/{e.origin} | {e.retrieved_at} | F: {e.observed_fact[:160]} | X: {e.excerpt[:160]}"
            )
        for g in s.signals:
            out.append(
                f"SIG {g.signal_type} {g.title[:80]} {g.occurred_on} conflict={g.date_conflict} ev={len(g.evidence_ids)}"
            )
        for i in s.intents:
            out.append(
                f"INT {i.strength} {i.source_type} {i.title[:80]} {i.observed_on} {i.deadline_on} ev={len(i.evidence_ids)}"
            )
    open(
        "/tmp/claude-0/-home-user-AIgentiX-business-growth-platform-/6dc13290-5d90-5d5b-a9a1-e3c8f7067dbf/scratchpad/probe.txt",
        "w",
    ).write("\n".join(out))
