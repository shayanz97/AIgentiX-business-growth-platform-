"""Helpers shared by the agents for handling untrusted text and checking citations."""

import re

_URL = re.compile(r"(?i)\b(?:https?://|www\.)[^\s)>\]]+")
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


def strip_foreign_urls(text: str, allowed_domain: str | None) -> tuple[str, bool]:
    """Remove URLs not on the company's own domain (prompt-injection exfiltration). Returns (text, removed?)."""
    removed = False

    def _replace(match: re.Match[str]) -> str:
        nonlocal removed
        url = match.group(0).lower()
        if allowed_domain and allowed_domain in url:
            return match.group(0)
        removed = True
        return "[link removed]"

    return _URL.sub(_replace, text), removed
