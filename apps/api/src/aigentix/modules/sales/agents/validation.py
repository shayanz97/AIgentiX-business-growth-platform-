"""Post-validation shared by the Sales agents: model output is untrusted until it passes these checks.

`TextGuard` cleans one piece of model text against the evidence it may rely on and records quality flags:
foreign links and contact data are removed; sentences with numbers / money that the support text does not
contain, guarantee or certification promises, a lead score phrased as a purchase probability, or automatic
outreach are dropped. Nothing here adds content; it only removes or downgrades.
"""

import re
from dataclasses import dataclass, field

from aigentix.platform.llm.safety import (
    REMOVED_CONTACT,
    REMOVED_LINK,
    contains_certification_claim,
    contains_guarantee,
    drop_sentences,
    mentions_money,
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

_INSTRUCTION_LIKE = re.compile(
    r"(?i)(ignore (?:all |any |the |previous |prior |above )*(?:instructions|evidence|rules|data)|ignoriere"
    r"|disregard (?:the|all|previous)|system prompt|you are now|new instructions|neue anweisung)"
)
_WORD = re.compile(r"[^\W\d_]{4,}")

HUMAN_NEXT_ACTION = "Review the evidence and prepare discovery questions before any contact."


def _numbers_text(sentence: str) -> str:
    return _STRUCTURE_NUMBER.sub(" ", _LIST_NUMBER.sub(" ", sentence))


def is_hedged(text: str) -> bool:
    return bool(_HEDGE.search(text))


def mentions_probability(text: str) -> bool:
    return bool(_PROBABILITY.search(text))


def is_outreach_action(text: str) -> bool:
    return bool(_OUTREACH.search(text))


def word_overlap(claim: str, support: str) -> float:
    """Share of the claim's content words (4+ letters) that occur in `support` (cheap grounding check)."""
    words = {w.lower() for w in _WORD.findall(claim)}
    if not words:
        return 1.0
    present = {w.lower() for w in _WORD.findall(support)}
    return len(words & present) / len(words)


@dataclass
class TextGuard:
    """Cleans model text for one output; `flags` collects what was removed (shared across the output)."""

    company_domain: str | None
    flags: set[str] = field(default_factory=set)
    # True: every amount of money is removed (proposals quote prices only from approved offerings).
    strict_money: bool = False

    def clean(self, text: str, limit: int) -> str:
        cleaned, contact_removed = strip_contact_data(text.strip()[:limit])
        if contact_removed:
            self.flags.add("contact_data_removed")
        cleaned, link_removed = strip_foreign_urls(cleaned, self.company_domain)
        if link_removed:
            self.flags.add("external_link_removed")
        return cleaned.strip()

    def filter(self, text: str, *, support: str, allow_money: bool = False) -> str:
        """Drop the sentences that break a grounding rule. `support` = the text the statement may rely on."""
        support_has_certification = contains_certification_claim(support)

        def violates(sentence: str) -> bool:
            if REMOVED_LINK in sentence or REMOVED_CONTACT in sentence:
                return True  # a sentence built around a foreign link or contact data is not kept at all
            if _INSTRUCTION_LIKE.search(sentence):
                self.flags.add("instruction_like_text_removed")
                return True
            if mentions_probability(sentence):
                self.flags.add("score_as_probability_removed")
                return True
            if contains_certification_claim(sentence) and not support_has_certification:
                self.flags.add("certification_claim_removed")
                return True
            if contains_guarantee(sentence) and not contains_guarantee(support):
                self.flags.add("guarantee_removed")
                return True
            money = not allow_money and mentions_money(sentence)
            if money and self.strict_money:
                self.flags.add("unapproved_price_removed")
                return True
            if unsupported_numbers(_numbers_text(sentence), support):
                self.flags.add("unsupported_number")
                return True
            if money and not mentions_money(support):
                self.flags.add("unsupported_amount")
                return True
            return False

        kept, _ = drop_sentences(text, violates)
        return kept.strip()

    def text(self, text: str, *, support: str, limit: int = 1_000, allow_money: bool = False) -> str:
        return self.filter(self.clean(text, limit), support=support, allow_money=allow_money)


def restates(text: str, hypothesis: str, *, min_overlap: float = 0.7) -> bool:
    """Does `text` restate `hypothesis` (most of its content words, hedges aside)?"""
    stripped = _HEDGE.sub(" ", hypothesis)
    return len(_WORD.findall(stripped)) >= 4 and word_overlap(stripped, text) >= min_overlap
