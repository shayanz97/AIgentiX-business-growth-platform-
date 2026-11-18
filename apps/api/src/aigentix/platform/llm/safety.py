"""Generic guards for untrusted text going into prompts and for model output coming back.

Module-independent (no business-module imports): prompt-delimiter neutralisation, verbatim excerpt checks,
foreign-link stripping, contact-data redaction and detectors for numbers, money, guarantees and certification
promises. Business modules decide what to do with a hit (drop, downgrade, flag); these helpers only find them.
"""

import re
from collections.abc import Callable
from urllib.parse import urlsplit

_LT, _GT = "‹", "›"  # single angle quotation marks: look like < > but cannot open or close tags
_WS = re.compile(r"\s+")
_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "…": "..."})


def neutralise_markup(text: str) -> str:
    """Untrusted text cannot open or close our prompt delimiters (or inject HTML into an export)."""
    return text.replace("<", _LT).replace(">", _GT)


def normalise_for_match(text: str) -> str:
    return _WS.sub(" ", neutralise_markup(text).translate(_QUOTES)).strip().lower()


def excerpt_in_source(excerpt: str, source_text: str, *, min_length: int = 10) -> bool:
    """Is `excerpt` (whitespace/quote-insensitive) a verbatim part of `source_text`?"""
    needle = normalise_for_match(excerpt).strip(" .\"'")
    if len(needle) < min_length:
        return False
    return needle in normalise_for_match(source_text)


# --- links ----------------------------------------------------------------------------------------------

_LINKISH = re.compile(
    r"(?i)\b(?:https?://[^\s<>\"')\]]+"  # explicit URLs
    r"|www\.[^\s<>\"')\]]+"  # www. hosts
    r"|(?:[a-z0-9-]+\.)+(?:com|net|org|io|ai|co|app|dev|info|biz|xyz|example|online|site|me|ly|to|de|eu)\b"
    r"(?:/[^\s<>\"')\]]*)?"
    r"|(?:[a-z0-9-]+\.)+[a-z]{2,24}/[^\s<>\"')\]]*)"  # bare host followed by a path
)


def _host_of(link: str) -> str:
    candidate = link if "://" in link else f"http://{link}"
    try:
        return (urlsplit(candidate).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def is_company_host(host: str, company_domain: str | None) -> bool:
    """The company's own domain or a subdomain of it (exact host comparison, not substring)."""
    if not company_domain or not host:
        return False
    host = host[4:] if host.startswith("www.") else host
    return host == company_domain or host.endswith("." + company_domain)


def strip_foreign_urls(text: str, allowed_domain: str | None) -> tuple[str, bool]:
    """Remove links (URLs, www. hosts, bare domains) not on `allowed_domain`. Returns (text, removed?)."""
    removed = False

    def _replace(match: re.Match[str]) -> str:
        nonlocal removed
        if is_company_host(_host_of(match.group(0)), allowed_domain):
            return match.group(0)
        removed = True
        return "[link removed]"

    return _LINKISH.sub(_replace, text), removed


# --- personal contact data ------------------------------------------------------------------------------------

_EMAIL = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,24}\b")
_PHONE = re.compile(r"(?<![\w.,/-])(?:\+|00)?\d[\d ()/.-]{6,}\d(?![\w.,/-])")
_DATE_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{1,2}\.\d{1,2}\.\d{2,4}$")


def strip_contact_data(text: str) -> tuple[str, bool]:
    """Redact e-mail addresses and phone-number-like digit runs (dates and plain numbers are kept)."""
    removed = False

    def _email(match: re.Match[str]) -> str:
        nonlocal removed
        removed = True
        return "[contact removed]"

    def _phone(match: re.Match[str]) -> str:
        nonlocal removed
        value = match.group(0)
        digits = re.sub(r"\D", "", value)
        if len(digits) < 8 or _DATE_LIKE.match(value.strip()):
            return value
        removed = True
        return "[contact removed]"

    text = _EMAIL.sub(_email, text)
    return _PHONE.sub(_phone, text), removed


# --- numbers, money, guarantees, certifications -----------------------------------------------------------------

_LABEL_TOKEN = re.compile(r"\b[A-Z]\d+\b")  # citation labels such as E3 are not numbers
_NUMBER = re.compile(r"\d+(?:[.,']\d+)*")
_CURRENCY = re.compile(
    r"(?i)(?:[€$£]|\b(?:eur|euro|euros|usd|dollars?|chf|gbp|franken)\b|\b(?:tsd|mio|mrd)\.?\s*(?:€|eur)|\bk€)"
)


def numbers_in(text: str) -> list[str]:
    """Numeric tokens, normalised to their digits ("1.500", "1,500" and "1500" compare equal)."""
    cleaned = _LABEL_TOKEN.sub(" ", text)
    tokens = (re.sub(r"\D", "", m.group(0)).lstrip("0") or "0" for m in _NUMBER.finditer(cleaned))
    return list(dict.fromkeys(tokens))


def unsupported_numbers(statement: str, support: str) -> list[str]:
    """Numbers stated in `statement` that do not occur in `support` (e.g. the cited evidence text)."""
    available = set(numbers_in(support))
    return [n for n in numbers_in(statement) if n not in available]


def mentions_money(text: str) -> bool:
    """A currency symbol / code / word — prices, costs, savings or revenue figures."""
    return bool(_CURRENCY.search(text))


_GUARANTEE = re.compile(
    r"(?i)(guarant|garantie|garantier|zugesichert|risk[- ]free|risikolos|risikofrei|no[- ]risk|zero[- ]risk"
    r"|ohne risiko|\bensures? (?:a |an )?(?:roi|return)|\b\d+\s?%\s*(?:roi|return|savings|ersparnis|einsparung)"
    r"|\broi\b[^.!?\n]{0,40}\b\d|\bpayback\b[^.!?\n]{0,30}\b\d|amorti[sz]\w*[^.!?\n]{0,30}\b\d)"
)
_CERTIFICATION = re.compile(
    r"(?i)(\biso[ /-]?(?:iec[ /-]?)?\d{4,5}\b|\bsoc ?2\b|\btisax\b|\bbsi[- ]grundschutz\b"
    r"|\b(?:dsgvo|gdpr|ds-gvo)[- ]?(?:zertifi|certifi|konform|compliant)"
    r"|\bcertified\b|\bzertifiziert|\bzertifizierung|\bcertification\b"
    r"|\b(?:fully|100\s?%|vollständig|garantiert)\s+(?:compliant|konform)"
    r"|\bcompliance (?:is )?guaranteed|\bcompliant guaranteed)"
)


def contains_guarantee(text: str) -> bool:
    """Guaranteed outcomes / ROI promises ("guaranteed", "garantiert", "risk-free", "300% ROI", ...)."""
    return bool(_GUARANTEE.search(text))


def contains_certification_claim(text: str) -> bool:
    """Certification or compliance promises (ISO 27001, "DSGVO-zertifiziert", "GDPR-certified", ...)."""
    return bool(_CERTIFICATION.search(text))


# --- sentence-level filtering --------------------------------------------------------------------------------

# A sentence ends after . ! ? that follows a letter or closing mark (so "1. Item" and "z.B. 3" stay whole).
_SENTENCE_END = re.compile(r"(?<=[^\W\d_][.!?]|[)\]\"'][.!?])\s+(?=[A-ZÄÖÜ0-9\[\"(])")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for line in text.splitlines() for s in _SENTENCE_END.split(line) if s.strip()]


def drop_sentences(text: str, predicate: Callable[[str], bool]) -> tuple[str, int]:
    """Remove every sentence for which `predicate` is true, keeping line structure (lists, paragraphs).
    Returns (remaining text, number of sentences removed)."""
    lines: list[str] = []
    removed = 0
    for line in text.splitlines():
        if not line.strip():
            lines.append("")
            continue
        sentences = [s for s in _SENTENCE_END.split(line.strip()) if s.strip()]
        kept = [s for s in sentences if not predicate(s)]
        removed += len(sentences) - len(kept)
        if kept:
            indent = line[: len(line) - len(line.lstrip())]
            lines.append(indent + " ".join(kept))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip(), removed
