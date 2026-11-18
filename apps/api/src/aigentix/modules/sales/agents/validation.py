"""Post-validation shared by the Sales agents: model output is untrusted until it passes these checks.

`TextGuard` cleans one piece of model text against the evidence it may rely on and records quality flags:
foreign links and contact data are removed; sentences with numbers / money that the support text does not
contain, guarantee or certification promises, a lead score phrased as a purchase probability, or automatic
outreach are dropped. Nothing here adds content; it only removes or downgrades.
"""

import re
from dataclasses import dataclass, field

from aigentix.platform.llm.safety import (
    contains_certification_claim,
    contains_guarantee,
    drop_sentences,
    mentions_money,
    normalise_for_match,
    strip_contact_data,
    strip_foreign_urls,
    unsupported_numbers,
)

# Ordinal structure words ("Phase 2", "Schritt 1") and list numbering are not factual numbers.
_STRUCTURE_NUMBER = re.compile(
    r"(?i)\b(?:phase|step|stage|schritt|stufe|milestone|meilenstein|option|paket|package|section|abschnitt|"
    r"workshop|sprint|iteration|teil|part)\s+\d{1,2}\b"
)
_LIST_NUMBER = re.compile(r"^\s*(?:[-*]\s*)?\d{1,2}[.)]\s+")
_PROBABILITY = re.compile(
    r"(?i)(probab|likelihood|wahrscheinlich|\bchance (?:of|to|that)\b|\bodds\b|\b\d+\s?%\s*(?:chance|likely|sure)"
    r"|\blikely to (?:buy|purchase|convert|sign|close|order)\b|\bwill (?:buy|purchase|sign|convert)\b"
    r"|\bcertain to (?:buy|purchase|sign)\b|conversion rate)"
)
_OUTREACH = re.compile(
    r"(?i)\b(send|sending|e-?mail|sms|text message|linkedin|whatsapp|dm|message the|newsletter|cold[- ]call"
    r"|anschreiben|senden|verschicken|schicken|automatic(?:ally)?|automatisch|auto-send)\b"
)
_HEDGE = re.compile(
    r"(?i)\b(may|might|could|possibly|potentially|perhaps|hypothes\w*|to be validated|to be confirmed|assum\w*"
    r"|möglicherweise|vermutlich|könnte|eventuell|zu prüfen|zu validieren)\b"
)

HUMAN_NEXT_ACTION = "Review the evidence and prepare discovery questions before any contact."


def _numbers_text(sentence: str) -> str:
    return _STRUCTURE_NUMBER.sub(" ", _LIST_NUMBER.sub(" ", sentence))


def is_hedged(text: str) -> bool:
    return bool(_HEDGE.search(text))


def mentions_probability(text: str) -> bool:
    return bool(_PROBABILITY.search(text))


def is_outreach_action(text: str) -> bool:
    return bool(_OUTREACH.search(text))


@dataclass
class TextGuard:
    """Cleans model text for one output; `flags` collects what was removed (shared across the output)."""

    company_domain: str | None
    flags: set[str] = field(default_factory=set)

    def clean(self, text: str, limit: int) -> str:
        cleaned, link_removed = strip_foreign_urls(text.strip()[:limit], self.company_domain)
        if link_removed:
            self.flags.add("external_link_removed")
        cleaned, contact_removed = strip_contact_data(cleaned)
        if contact_removed:
            self.flags.add("contact_data_removed")
        return cleaned.strip()

    def filter(self, text: str, *, support: str, allow_money: bool = False) -> str:
        """Drop the sentences that break a grounding rule. `support` = the text the statement may rely on."""
        support_has_certification = contains_certification_claim(support)

        def violates(sentence: str) -> bool:
            if mentions_probability(sentence):
                self.flags.add("score_as_probability_removed")
                return True
            if contains_guarantee(sentence) and not contains_guarantee(support):
                self.flags.add("guarantee_removed")
                return True
            if contains_certification_claim(sentence) and not support_has_certification:
                self.flags.add("certification_claim_removed")
                return True
            if not allow_money and mentions_money(sentence) and not mentions_money(support):
                self.flags.add("unapproved_price_removed")
                return True
            if unsupported_numbers(_numbers_text(sentence), support):
                self.flags.add("unsupported_number")
                return True
            return False

        kept, _ = drop_sentences(text, violates)
        return kept.strip()

    def text(self, text: str, *, support: str, limit: int = 1_000, allow_money: bool = False) -> str:
        return self.filter(self.clean(text, limit), support=support, allow_money=allow_money)


def contains_phrase(haystack: str, needle: str, *, min_length: int = 25) -> bool:
    """Does `haystack` contain `needle` (normalised, at least `min_length` characters)?"""
    n = normalise_for_match(needle).strip(" .")
    return len(n) >= min_length and n in normalise_for_match(haystack)
