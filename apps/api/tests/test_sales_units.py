"""Sales domain unit tests: pipeline transitions, reopen target, compliance gate, suppression hashing."""

from pathlib import Path

import pytest

from aigentix.modules.sales.domain.compliance import Review, contact_permission, normalise, suppression_hash
from aigentix.modules.sales.domain.pipeline import (
    PIPELINE,
    TRANSITIONS,
    StageFacts,
    TransitionError,
    check_close,
    check_move,
    reopen_stage,
)
from aigentix.modules.sales.models import Channel, ContactRestriction, LawfulBasis, Stage

NO_FACTS = StageFacts(has_contact_activity=False, has_sent_proposal=False)
ALL_FACTS = StageFacts(has_contact_activity=True, has_sent_proposal=True)


@pytest.mark.parametrize("current", list(Stage))
@pytest.mark.parametrize("target", list(Stage))
def test_transition_matrix(current: Stage, target: Stage) -> None:
    allowed = target in TRANSITIONS[current]
    if allowed:
        check_move(current, target, ALL_FACTS)
    else:
        with pytest.raises(TransitionError):
            check_move(current, target, ALL_FACTS)


def test_outcomes_and_evidence_gates() -> None:
    for stage in (Stage.WON, Stage.LOST):
        with pytest.raises(TransitionError, match="close action"):
            check_move(Stage.IN_CONVERSATION, stage, ALL_FACTS)
    with pytest.raises(TransitionError, match="contact"):
        check_move(Stage.CONTACT_PLANNED, Stage.IN_CONVERSATION, NO_FACTS)
    with pytest.raises(TransitionError, match="proposal"):
        check_move(Stage.IN_CONVERSATION, Stage.PROPOSAL_SENT, StageFacts(True, False))
    check_close(Stage.QUALIFIED, Stage.LOST)
    with pytest.raises(TransitionError):
        check_close(Stage.WON, Stage.LOST)
    with pytest.raises(TransitionError):
        check_close(Stage.QUALIFIED, Stage.RESEARCHING)
    assert all(s in PIPELINE for s in Stage)


def test_reopen_returns_last_open_stage() -> None:
    assert reopen_stage(["qualified", "contact_planned", "in_conversation"]) == Stage.IN_CONVERSATION
    assert reopen_stage(["qualified", "lost", "qualified", "researching"]) == Stage.RESEARCHING
    assert reopen_stage([]) == Stage.QUALIFIED


def _perm(channel: Channel, **kw: object) -> bool:
    base: dict[str, object] = {
        "restriction": ContactRestriction.UNVERIFIED,
        "suppressed": False,
        "has_address": True,
        "latest_review": None,
    }
    return contact_permission(channel, **{**base, **kw}).allowed  # type: ignore[arg-type]


def test_compliance_gate_german_b2b_defaults() -> None:
    assert not _perm(Channel.EMAIL)  # a public address alone permits nothing
    review = Review(Channel.EMAIL, "allowed", LawfulBasis.LEGITIMATE_INTEREST)
    assert not _perm(Channel.EMAIL, latest_review=review)  # legitimate interest is not enough for e-mail advertising
    assert _perm(Channel.EMAIL, latest_review=Review(Channel.EMAIL, "allowed", LawfulBasis.EXPLICIT_CONSENT))
    assert _perm(Channel.PHONE, latest_review=Review(Channel.PHONE, "allowed", LawfulBasis.PRESUMED_CONSENT_B2B))
    assert not _perm(Channel.EMAIL, latest_review=Review(Channel.EMAIL, "allowed", LawfulBasis.PRESUMED_CONSENT_B2B))
    assert _perm(Channel.LETTER, latest_review=Review(Channel.LETTER, "allowed", LawfulBasis.LEGITIMATE_INTEREST))
    consent = Review(Channel.EMAIL, "allowed", LawfulBasis.EXPLICIT_CONSENT)
    assert not _perm(Channel.EMAIL, latest_review=consent, suppressed=True)  # suppression always wins
    assert not _perm(Channel.EMAIL, latest_review=consent, restriction=ContactRestriction.RESTRICTED)
    assert not _perm(Channel.EMAIL, latest_review=Review(Channel.EMAIL, "not_allowed", LawfulBasis.EXPLICIT_CONSENT))
    assert not _perm(Channel.EMAIL, latest_review=consent, has_address=False)


def test_suppression_hash_normalises() -> None:
    assert suppression_hash(Channel.EMAIL, " Max@Firma.example ") == suppression_hash(
        Channel.EMAIL, "max@firma.example"
    )
    assert normalise(Channel.PHONE, "0555 0123") == normalise(Channel.PHONE, "+49 555 0123")
    assert suppression_hash(Channel.EMAIL, "a@b.example") != suppression_hash(Channel.PHONE, "a@b.example")
    assert len(suppression_hash(Channel.EMAIL, "a@b.example")) == 64


def test_sales_code_cannot_send_messages() -> None:
    """Guard against accidental outreach: no mail/SMS/telephony libraries or raw HTTP clients in the module."""
    root = Path(__file__).resolve().parents[1] / "src" / "aigentix" / "modules" / "sales"
    forbidden = (
        "smtplib",
        "email.mime",
        "twilio",
        "sendgrid",
        "mailgun",
        "import httpx",
        "import requests",
        "from httpx",
    )
    offenders = [
        f"{p.relative_to(root)}: {word}"
        for p in root.rglob("*.py")
        for word in forbidden
        if word in p.read_text(encoding="utf-8")
    ]
    assert not offenders, offenders


def test_sales_does_not_import_lead_intelligence() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "aigentix" / "modules" / "sales"
    offenders = [str(p) for p in root.rglob("*.py") if "modules.lead_intelligence" in p.read_text(encoding="utf-8")]
    assert not offenders, offenders
