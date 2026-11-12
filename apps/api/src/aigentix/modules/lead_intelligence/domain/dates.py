"""Event-date parsing and freshness.

Rules (Sprint 3):
  * Only dates written on the page (or in its machine-readable metadata) are event dates. The retrieval date is
    never used as an event date; a page without a date yields an *unknown* date, which is never "current".
  * Partial dates keep their precision ("Oktober 2026" → month). For freshness the earliest possible day is used,
    so a partial date never looks fresher than it is.
  * Dates after the reference date are not event dates (they are deadlines or planned dates).
  * Conflicting dates for the same event are reported as a conflict instead of picking one.
"""

import re
from dataclasses import dataclass
from datetime import date

from aigentix.modules.lead_intelligence.models import DatePrecision

_MONTHS = {
    # German
    "januar": 1, "jänner": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7,
    "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
    # English
    "january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7, "october": 10, "december": 12,
    # Short forms
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10,
    "okt": 10, "nov": 11, "dec": 12, "dez": 12,
}  # fmt: skip
_MONTH_NAMES = "|".join(sorted(_MONTHS, key=len, reverse=True))

_ISO = re.compile(r"\b(20\d{2}|19\d{2})-(\d{2})-(\d{2})(?:[T ][\d:.+\-Z]*)?\b")
_DE_NUMERIC = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2}|19\d{2})\b")
_DE_TEXT = re.compile(rf"\b(\d{{1,2}})\.\s*({_MONTH_NAMES})\.?\s+(20\d{{2}}|19\d{{2}})\b", re.I)
_EN_TEXT = re.compile(rf"\b({_MONTH_NAMES})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}}|19\d{{2}})\b", re.I)
_EN_DAY_FIRST = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_NAMES})\.?,?\s+(20\d{{2}}|19\d{{2}})\b", re.I)
_MONTH_YEAR = re.compile(rf"\b({_MONTH_NAMES})\.?\s+(20\d{{2}}|19\d{{2}})\b", re.I)


@dataclass(frozen=True)
class ParsedDate:
    value: date  # earliest possible day for partial dates
    precision: DatePrecision

    def to_json(self) -> dict[str, str]:
        return {"date": self.value.isoformat(), "precision": self.precision.value}


def _safe(year: int, month: int, day: int, precision: DatePrecision) -> ParsedDate | None:
    try:
        return ParsedDate(date(year, month, day), precision)
    except ValueError:
        return None


def parse_machine_date(value: str) -> ParsedDate | None:
    """`<time datetime>`, `article:published_time`, JSON-LD `datePublished`: ISO date, year-month or year."""
    value = value.strip()
    if m := _ISO.match(value):
        return _safe(int(m[1]), int(m[2]), int(m[3]), DatePrecision.DAY)
    if m := re.fullmatch(r"(\d{4})-(\d{2})", value):
        return _safe(int(m[1]), int(m[2]), 1, DatePrecision.MONTH)
    if m := re.fullmatch(r"(\d{4})", value):
        return _safe(int(m[1]), 1, 1, DatePrecision.YEAR)
    return None


def find_text_dates(text: str) -> list[tuple[int, ParsedDate]]:
    """All dates written in text, as (position, date). Day-precision matches win over overlapping month matches."""
    found: list[tuple[int, int, ParsedDate]] = []
    for m in _ISO.finditer(text):
        if p := _safe(int(m[1]), int(m[2]), int(m[3]), DatePrecision.DAY):
            found.append((m.start(), m.end(), p))
    for m in _DE_NUMERIC.finditer(text):
        if p := _safe(int(m[3]), int(m[2]), int(m[1]), DatePrecision.DAY):
            found.append((m.start(), m.end(), p))
    for m in _DE_TEXT.finditer(text):
        if p := _safe(int(m[3]), _MONTHS[m[2].lower()], int(m[1]), DatePrecision.DAY):
            found.append((m.start(), m.end(), p))
    for m in _EN_TEXT.finditer(text):
        if p := _safe(int(m[3]), _MONTHS[m[1].lower()], int(m[2]), DatePrecision.DAY):
            found.append((m.start(), m.end(), p))
    for m in _EN_DAY_FIRST.finditer(text):
        if p := _safe(int(m[3]), _MONTHS[m[2].lower()], int(m[1]), DatePrecision.DAY):
            found.append((m.start(), m.end(), p))
    covered = [(s, e) for s, e, _ in found]
    for m in _MONTH_YEAR.finditer(text):
        if any(s <= m.start() < e or s < m.end() <= e for s, e in covered):
            continue
        if p := _safe(int(m[2]), _MONTHS[m[1].lower()], 1, DatePrecision.MONTH):
            found.append((m.start(), m.end(), p))
    found.sort(key=lambda f: f[0])
    result: list[tuple[int, ParsedDate]] = []
    last_end = -1
    for start, end, parsed in found:
        if start < last_end:
            continue  # overlapping match (e.g. "20. Oktober 2026" also matched as "Oktober 2026")
        result.append((start, parsed))
        last_end = end
    return result


@dataclass(frozen=True)
class EventDate:
    value: ParsedDate | None
    deadline: ParsedDate | None
    source: str  # time_element | metadata | text | none


def event_date(machine: list[str], text: str, *, reference: date, page_metadata: list[str] | None = None) -> EventDate:
    """The date an item reports on, from its own markup first, then its text, then page-level metadata.

    Dates later than `reference` are never event dates; the latest of them is kept as a possible deadline.
    """
    future: list[ParsedDate] = []

    def pick(candidates: list[ParsedDate]) -> ParsedDate | None:
        past = [c for c in candidates if c.value <= reference]
        future.extend(c for c in candidates if c.value > reference)
        return past[0] if past else None

    chosen = pick([p for v in machine if (p := parse_machine_date(v))])
    source = "time_element" if chosen else "none"
    text_dates = [p for _, p in find_text_dates(text)]
    if chosen is None:
        chosen = pick(text_dates)
        source = "text" if chosen else source
    else:
        future.extend(p for p in text_dates if p.value > reference)
    if chosen is None and page_metadata:
        chosen = pick([p for v in page_metadata if (p := parse_machine_date(v))])
        source = "metadata" if chosen else source
    deadline = max(future, key=lambda p: p.value) if future else None
    return EventDate(value=chosen, deadline=deadline, source=source)


def same_event_date(a: ParsedDate, b: ParsedDate) -> bool:
    """Compatible dates: equal at the coarser of the two precisions."""
    coarse = max((a.precision, b.precision), key=[DatePrecision.DAY, DatePrecision.MONTH, DatePrecision.YEAR].index)
    if coarse == DatePrecision.YEAR:
        return a.value.year == b.value.year
    if coarse == DatePrecision.MONTH:
        return (a.value.year, a.value.month) == (b.value.year, b.value.month)
    return a.value == b.value


@dataclass(frozen=True)
class MergedDate:
    value: ParsedDate | None
    conflict: bool


def merge_dates(candidates: list[ParsedDate]) -> MergedDate:
    """One date for several mentions of the same event; incompatible dates → conflict, no date chosen."""
    if not candidates:
        return MergedDate(None, False)
    order = [DatePrecision.DAY, DatePrecision.MONTH, DatePrecision.YEAR]
    best = min(candidates, key=lambda p: (order.index(p.precision), p.value))
    if all(same_event_date(best, c) for c in candidates):
        return MergedDate(best, False)
    return MergedDate(None, True)


FRESHNESS_BANDS = ("recent", "moderate", "older", "historical", "unknown")


def freshness(event: date | None, reference: date, bands: dict[str, int]) -> str:
    """recent ≤ bands['recent'] days, moderate ≤ bands['moderate'], older ≤ bands['older'], else historical."""
    if event is None:
        return "unknown"
    age = (reference - event).days
    if age < 0:
        return "unknown"  # a future "event" date is not a verified past event
    if age <= bands["recent"]:
        return "recent"
    if age <= bands["moderate"]:
        return "moderate"
    if age <= bands["older"]:
        return "older"
    return "historical"
