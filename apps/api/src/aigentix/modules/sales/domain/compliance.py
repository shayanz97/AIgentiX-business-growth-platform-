"""Contact eligibility — the single permission gate for any future outreach.

AIgentiX never sends messages or places calls. This gate records whether a *person* may contact someone through a
channel, so that the UI can show it and any future feature that prepares outreach must call `contact_permission`
first (tests assert that sales code contains no sending integrations).

Defaults reflect German B2B practice (UWG § 7, GDPR); they are a conservative product rule, not legal advice:
  * e-mail advertising needs prior express consent or the § 7 (3) UWG existing-customer exception, or the contact
    asked to be contacted (inbound request);
  * phone calls to businesses need at least presumed consent (documented reason), consent or an inbound request;
  * LinkedIn messages need consent, an inbound request or an existing customer relationship;
  * postal letters may rely on a documented legitimate-interest assessment;
  * a publicly listed business address or number alone permits nothing;
  * a suppression (opt-out / objection) always wins and is never overridden by a review.
"""

import hashlib
import re
from dataclasses import dataclass

from aigentix.modules.sales.models import Channel, ContactRestriction, LawfulBasis

ALLOWED_BASES: dict[Channel, frozenset[LawfulBasis]] = {
    Channel.EMAIL: frozenset(
        {LawfulBasis.EXPLICIT_CONSENT, LawfulBasis.EXISTING_CUSTOMER, LawfulBasis.INBOUND_REQUEST}
    ),
    Channel.PHONE: frozenset(
        {
            LawfulBasis.EXPLICIT_CONSENT,
            LawfulBasis.PRESUMED_CONSENT_B2B,
            LawfulBasis.INBOUND_REQUEST,
            LawfulBasis.EXISTING_CUSTOMER,
        }
    ),
    Channel.LINKEDIN: frozenset(
        {LawfulBasis.EXPLICIT_CONSENT, LawfulBasis.INBOUND_REQUEST, LawfulBasis.EXISTING_CUSTOMER}
    ),
    Channel.LETTER: frozenset(
        {
            LawfulBasis.LEGITIMATE_INTEREST,
            LawfulBasis.EXPLICIT_CONSENT,
            LawfulBasis.EXISTING_CUSTOMER,
            LawfulBasis.INBOUND_REQUEST,
        }
    ),
}


def normalise(channel: Channel, value: str) -> str:
    value = value.strip().lower()
    if channel == Channel.PHONE:
        digits = re.sub(r"\D", "", value)
        return "49" + digits[1:] if digits.startswith("0") and not digits.startswith("00") else digits.lstrip("0")
    return value


def suppression_hash(channel: Channel, value: str) -> str:
    return hashlib.sha256(f"{channel.value}:{normalise(channel, value)}".encode()).hexdigest()


@dataclass(frozen=True)
class Review:
    channel: Channel
    decision: str  # allowed | not_allowed
    lawful_basis: LawfulBasis


@dataclass(frozen=True)
class Permission:
    allowed: bool
    reason: str


def basis_valid_for(channel: Channel, basis: LawfulBasis) -> bool:
    return basis in ALLOWED_BASES[channel]


def contact_permission(
    channel: Channel,
    *,
    restriction: ContactRestriction,
    suppressed: bool,
    has_address: bool,
    latest_review: Review | None,
) -> Permission:
    if suppressed or restriction == ContactRestriction.SUPPRESSED:
        return Permission(False, "The contact opted out or objected (suppressed); never contact.")
    if restriction == ContactRestriction.RESTRICTED:
        return Permission(False, "The contact is restricted until reviewed again.")
    if not has_address:
        return Permission(False, f"No business {channel.value} is recorded.")
    if latest_review is None:
        return Permission(
            False, f"No eligibility review for {channel.value} yet; a public address alone permits nothing."
        )
    if latest_review.decision != "allowed":
        return Permission(False, f"The latest review does not allow {channel.value}.")
    if not basis_valid_for(channel, latest_review.lawful_basis):
        return Permission(False, f"{latest_review.lawful_basis.value} is not a sufficient basis for {channel.value}.")
    return Permission(True, f"Allowed for {channel.value} ({latest_review.lawful_basis.value}, reviewed by a person).")
