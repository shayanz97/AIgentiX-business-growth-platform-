"""Regression tests for the Sprint 4 independent review (claim-level grounding, Markdown export safety)."""

from aigentix.modules.sales.agents.validation import TextGuard
from aigentix.modules.sales.services.proposals import _md
from aigentix.platform.llm.safety import certification_terms


def test_certification_claims_need_the_same_certification_in_support() -> None:
    guard = TextGuard("kunde.example")
    support = "Die Firma ist nach ISO 9001 zertifiziert."
    assert certification_terms(support) >= {"iso 9001"}
    kept = guard.text("The company states it is ISO 9001 certified.", support=support)
    assert "ISO 9001" in kept
    dropped = guard.text("Our solution is ISO 27001 certified.", support=support)
    assert "27001" not in dropped
    assert "certification_claim_removed" in guard.flags


def test_proposals_never_keep_vendor_guarantees_or_certifications() -> None:
    guard = TextGuard("kunde.example", strict_money=True, strict_claims=True)
    support = "Die Firma ist nach ISO 9001 zertifiziert. Wir garantieren kurze Reaktionszeiten."
    text = "The rollout is ISO 9001 certified. We guarantee faster responses. The pilot covers inquiry routing."
    out = guard.text(text, support=support)
    assert "ISO 9001" not in out
    assert "guarantee" not in out.lower()
    assert "inquiry routing" in out


def test_markdown_export_strips_unsafe_links_and_images() -> None:
    text = (
        "See [docs](javascript:alert(1)) and ![pixel](https://tracker.example/p.gif) or [site](https://kunde.example)."
    )
    out = _md(text)
    assert "javascript" not in out
    assert "tracker.example" not in out
    assert "![" not in out
    assert "[site](https://kunde.example)" in out
    assert "<script>" not in _md("<script>x</script>")
