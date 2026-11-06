"""Helpers shared by the agents for handling untrusted text and checking citations."""

import re
from urllib.parse import urlsplit

_WS = re.compile(r"\s+")
_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "…": "..."})


def neutralise_markup(text: str) -> str:
    """Untrusted text cannot open or close our prompt delimiters."""
    return text.replace("<", "‹").replace(">", "›")


def normalise_for_match(text: str) -> str:
    return _WS.sub(" ", neutralise_markup(text).translate(_QUOTES)).strip().lower()


def excerpt_in_source(excerpt: str, source_text: str) -> bool:
    needle = normalise_for_match(excerpt).strip(" .\"'")
    if len(needle) < 10:
        return False
    return needle in normalise_for_match(source_text)


_LINKISH = re.compile(
    r"(?i)\b(?:https?://[^\s<>\"')\]]+"  # explicit URLs
    r"|www\.[^\s<>\"')\]]+"  # www. hosts
    r"|(?:[a-z0-9-]+\.)+(?:com|net|org|io|ai|co|app|dev|info|biz|xyz|example|online|site|me|ly|to)\b(?:/[^\s<>\"')\]]*)?"
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
    """Remove links (URLs, www. hosts, bare domains) not on the company's own domain — prompt-injection
    exfiltration and look-alike hosts such as `acme.com.evil.io` or `evil.com/?x=acme.com`. Returns (text, removed?)."""
    removed = False

    def _replace(match: re.Match[str]) -> str:
        nonlocal removed
        if is_company_host(_host_of(match.group(0)), allowed_domain):
            return match.group(0)
        removed = True
        return "[link removed]"

    return _LINKISH.sub(_replace, text), removed


def supports(claim: str, excerpt: str, *, min_overlap: float = 0.5) -> bool:
    """Do the content words of `claim` appear in `excerpt`? (cheap guard against values the excerpt doesn't back)."""
    words = {w for w in re.findall(r"[a-z0-9]{4,}", claim.lower())}
    if not words:
        return True
    present = set(re.findall(r"[a-z0-9]{4,}", excerpt.lower()))
    return len(words & present) / len(words) >= min_overlap


# Negative characterisations that need explicit support in the cited evidence.
UNSUPPORTED_TERMS = (
    "inefficien",
    "slow",
    "outdated",
    "manual process",
    "manually",
    "struggl",
    "poor ",
    "wasting",
    "waste of",
    "bottleneck",
    "understaffed",
    "overwhelmed",
    "backlog",
    "legacy system",
    "error-prone",
)
