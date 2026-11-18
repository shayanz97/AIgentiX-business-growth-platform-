"""Split fetched pages into news items / job postings ("segments") for growth-trigger detection.

The same cleaning rules as `html.extract_page` apply (hidden elements, comments, scripts and site chrome are
dropped; e-mail addresses and phone numbers are redacted), so a segment's text is a verbatim part of the stored
page text and can be cited as evidence.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Comment, Tag

from aigentix.modules.lead_intelligence.integrations.html import (
    _REMOVE_TAGS,
    _clean_text,
    _is_hidden,
    _repair_unclosed_title,
)

MAX_SEGMENTS_PER_PAGE = 40
MAX_SEGMENT_CHARS = 1_500

# Path keywords of pages that carry announcements, job postings or project requests (DE + EN).
SIGNAL_PAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "news": (
        "news", "neuigkeiten", "aktuelles", "aktuell", "blog", "press", "presse", "pressemitteilungen",
        "newsroom", "media", "announcements", "meldungen", "updates", "insights",
    ),
    "careers": ("careers", "career", "jobs", "karriere", "stellen", "stellenangebote", "join-us", "vacancies"),
    "requests": (
        "ausschreibungen", "ausschreibung", "vergabe", "tenders", "tender", "procurement", "projektanfragen",
        "projektanfrage", "anfragen", "rfp", "partner-gesucht", "einkauf",
    ),
    "about": ("about", "about-us", "ueber-uns", "uber-uns", "über-uns", "unternehmen", "company", "wir"),
}  # fmt: skip

_INJECTION = re.compile(
    r"(?i)(ignore (?:all |any )?(?:previous|prior|above) instructions|ignoriere (?:alle )?(?:vorherigen )?anweisungen"
    r"|\bsystem\s*:|\bassistant\s*:|you are now|act as an?|classify this company|set the (?:event )?date"
    r"|developer mode|admin mode|<\s*/?\s*(?:website_content|evidence)\b)"
)


def signal_page_category(path: str) -> str | None:
    segments = [s for s in path.lower().strip("/").split("/") if s]
    for category in ("requests", "careers", "news", "about"):
        if any(seg in SIGNAL_PAGE_KEYWORDS[category] for seg in segments):
            return category
    return None


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION.search(text))


@dataclass
class Segment:
    kind: str  # article | job | page
    page_url: str
    page_category: str
    headline: str
    text: str  # cleaned, redacted text of the item (headline included)
    machine_dates: list[str] = field(default_factory=list)  # <time datetime> values inside the item
    page_dates: list[str] = field(default_factory=list)  # page-level published-date metadata
    suspicious: bool = False

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Segment":
        return cls(**data)


def _page_dates(soup: BeautifulSoup) -> list[str]:
    dates: list[str] = []
    for prop in ("article:published_time", "og:published_time", "datePublished"):
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"itemprop": prop})
        if isinstance(tag, Tag) and tag.get("content"):
            dates.append(str(tag.get("content")))
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        if not isinstance(script, Tag):
            continue
        try:
            data = json.loads(script.get_text() or "null")
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and isinstance(item.get("datePublished"), str):
                dates.append(item["datePublished"])
    return dates[:5]


def _headline(node: Tag) -> str:
    heading = node.find(["h1", "h2", "h3", "h4"])
    return _clean_text(heading)[:300] if isinstance(heading, Tag) else ""


def _times(node: Tag) -> list[str]:
    return [str(t.get("datetime")) for t in node.find_all("time") if isinstance(t, Tag) and t.get("datetime")][:5]


def extract_segments(body: bytes, url: str) -> list[Segment]:
    soup = BeautifulSoup(_repair_unclosed_title(body), "html.parser")
    page_dates = _page_dates(soup)
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for tag in soup.find_all(_REMOVE_TAGS):
        tag.decompose()
    for tag in soup.find_all(True):
        if isinstance(tag, Tag) and not tag.decomposed and _is_hidden(tag):
            tag.decompose()
    root = soup.body if isinstance(soup.body, Tag) else soup
    for chrome in root.find_all(["nav", "header", "footer"]):
        if isinstance(chrome, Tag) and not chrome.decomposed:
            chrome.decompose()

    path = urlsplit(url).path
    category = signal_page_category(path) or ("home" if path in ("", "/") else "other")
    items: list[Tag] = [a for a in root.find_all("article") if isinstance(a, Tag)]
    if not items and category == "careers":
        items = [li for li in root.find_all("li") if isinstance(li, Tag) and li.find(["h2", "h3", "h4"])]
    segments: list[Segment] = []
    for item in items[:MAX_SEGMENTS_PER_PAGE]:
        text = _clean_text(item)[:MAX_SEGMENT_CHARS]
        if len(text) < 10:
            continue
        segments.append(
            Segment(
                kind="job" if category == "careers" else "article",
                page_url=url,
                page_category=category,
                headline=_headline(item),
                text=text,
                machine_dates=_times(item),
                page_dates=page_dates,
                suspicious=looks_like_injection(text),
            )
        )
    if not segments and category in ("news", "requests", "careers"):
        text = _clean_text(root)[:MAX_SEGMENT_CHARS]
        if len(text) >= 10:
            segments.append(
                Segment(
                    kind="page",
                    page_url=url,
                    page_category=category,
                    headline=_headline(root),
                    text=text,
                    machine_dates=_times(root)[:1],
                    page_dates=page_dates,
                    suspicious=looks_like_injection(text),
                )
            )
    return segments
