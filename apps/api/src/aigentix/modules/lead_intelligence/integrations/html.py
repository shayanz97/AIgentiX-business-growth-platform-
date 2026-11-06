"""Deterministic HTML processing: readable text, relevant-link discovery and observable business signals.

All page content is untrusted. Hidden elements and comments are dropped (a common prompt-injection
carrier), e-mail addresses and phone numbers are redacted, and nothing here interprets text as instructions.
"""

import hashlib
import re
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup, Comment, Tag

from aigentix.modules.lead_intelligence.domain.domains import same_site
from aigentix.modules.lead_intelligence.models import EvidenceType

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{6,}\d(?!\w)")
_WS = re.compile(r"\s+")
_REMOVE_TAGS = (
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "canvas",
    "iframe",
    "object",
    "embed",
    "head",
)
_FILE_EXTENSIONS = (
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".mp4",
    ".mp3",
    ".css",
    ".js",
    ".xml",
    ".json",
    ".ics",
)
_DOCUMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx")

# Category -> keywords matched against URL path segments and link text (lower-case).
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "about": ("about", "about-us", "company", "who-we-are", "our-story", "om-oss", "uber-uns", "meista"),
    "services": ("services", "service", "solutions", "what-we-do", "treatments", "palvelut", "tjanster"),
    "products": ("products", "product", "shop", "store", "catalog", "catalogue"),
    "contact": ("contact", "contact-us", "kontakt", "get-in-touch", "request-quote", "quote", "yhteystiedot"),
    "careers": ("careers", "career", "jobs", "join-us", "vacancies", "work-with-us", "rekry"),
    "faq": ("faq", "faqs", "questions", "help"),
    "support": (
        "support",
        "customer-service",
        "customer-care",
        "returns",
        "shipping-returns",
        "track-shipment",
        "tracking",
        "client-portal",
        "client-portal-info",
        "new-patients",
        "shipping",
    ),
    "booking": ("book", "booking", "book-appointment", "appointment", "appointments", "reserve", "schedule"),
    "technology": ("technology", "digital", "digitalization", "digitalisation", "innovation", "platform"),
}
CATEGORY_PRIORITY = (
    "about",
    "services",
    "contact",
    "support",
    "booking",
    "faq",
    "products",
    "careers",
    "technology",
)
_EXCLUDED_SEGMENTS = (
    "login",
    "log-in",
    "signin",
    "sign-in",
    "signup",
    "register",
    "account",
    "my-account",
    "cart",
    "basket",
    "checkout",
    "privacy",
    "privacy-policy",
    "cookie",
    "cookies",
    "terms",
    "legal",
    "imprint",
    "impressum",
    "team",
    "people",
    "staff",
    "profile",
    "profiles",
    "author",
    "user",
    "users",
    "wp-admin",
    "wp-login",
    "feed",
    "tag",
    "search",
    "admin",
)
_CHAT_PROVIDERS = (
    "intercom",
    "zendesk",
    "zopim",
    "drift",
    "tawk.to",
    "livechat",
    "crisp.chat",
    "freshchat",
    "olark",
    "tidio",
    "hs-scripts",
    "chatwoot",
    "userlike",
)
_BOOKING_PROVIDERS = (
    "calendly",
    "acuityscheduling",
    "simplybook",
    "setmore",
    "timely",
    "opentable",
    "booking",
)
_GENERATORS = ("wordpress", "shopify", "wix", "squarespace", "webflow", "drupal", "joomla", "hubspot")


@dataclass(frozen=True)
class Link:
    url: str
    text: str


@dataclass(frozen=True)
class Signal:
    evidence_type: EvidenceType
    observed_fact: str
    excerpt: str


@dataclass
class PageContent:
    url: str
    title: str | None
    description: str | None
    site_name: str | None
    text: str
    headings: list[str] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    content_hash: str = ""


def name_from_title(title: str | None) -> str | None:
    """`Page heading | Company` → `Company` (the shortest separated part that looks like a name)."""
    if not title:
        return None
    parts = [p.strip() for p in re.split(r"\s[|\u2013\u2014-]\s", title) if p.strip()]
    candidates = [p for p in parts if 2 <= len(p) <= 60 and p.lower() not in ("home", "homepage", "welcome")]
    if len(parts) > 1 and candidates:
        return candidates[-1]
    return candidates[0] if candidates else None


def redact(text: str) -> str:
    return _PHONE.sub("[phone]", _EMAIL.sub("[email]", text))


def normalise_space(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _clean_text(node: Tag) -> str:
    return redact(normalise_space(node.get_text(" ", strip=True)))


def _is_hidden(tag: Tag) -> bool:
    if tag.attrs is None:
        return False
    style = str(tag.get("style", "")).replace(" ", "").lower()
    return (
        tag.has_attr("hidden")
        or str(tag.get("aria-hidden", "")).lower() == "true"
        or "display:none" in style
        or "visibility:hidden" in style
        or "font-size:0" in style
    )


def _sentence_with(text: str, keywords: tuple[str, ...], limit: int = 300) -> str | None:
    lower = text.lower()
    for keyword in keywords:
        index = lower.find(keyword)
        if index == -1:
            continue
        start = max(text.rfind(". ", 0, index) + 2, index - limit // 2, 0)
        end = text.find(". ", index)
        end = len(text) if end == -1 else end + 1
        return text[start : min(end, start + limit)].strip()
    return None


def categorise(path: str, link_text: str = "") -> str | None:
    segments = [s for s in path.lower().strip("/").split("/") if s]
    text = link_text.lower().strip()
    for category in CATEGORY_PRIORITY:
        keywords = CATEGORY_KEYWORDS[category]
        if any(seg in keywords for seg in segments) or any(
            k.replace("-", " ") == text or text.startswith(k.replace("-", " ") + " ") for k in keywords
        ):
            return category
    return None


def is_excluded_path(path: str) -> bool:
    lower = path.lower()
    if lower.endswith(_FILE_EXTENSIONS):
        return True
    return any(seg in _EXCLUDED_SEGMENTS for seg in lower.strip("/").split("/"))


_TITLE_OPEN = re.compile(rb"<title[^>]*>", re.I)


def _repair_unclosed_title(body: bytes) -> bytes:
    """An unclosed <title> would swallow the whole document as RCDATA; close it at the end of its line."""
    match = _TITLE_OPEN.search(body)
    if match is None or re.search(rb"</title\s*>", body, re.I):
        return body
    line_end = body.find(b"\n", match.end())
    cut = line_end if line_end != -1 else len(body)
    cut = min(cut, match.end() + 300)
    return body[:cut] + b"</title>" + body[cut:]


def _first_paragraph(root: Tag) -> str | None:
    for p in root.find_all("p"):
        if isinstance(p, Tag):
            text = _clean_text(p)
            if len(text) >= 40:
                return text[:400]
    return None


def extract_page(body: bytes, url: str, *, max_chars: int) -> PageContent:
    soup = BeautifulSoup(_repair_unclosed_title(body), "html.parser")

    # Structural signals that live in markup we are about to remove.
    script_sources = [str(s.get("src", "")).lower() for s in soup.find_all(["script", "iframe"]) if isinstance(s, Tag)]
    generator = soup.find("meta", attrs={"name": re.compile("^generator$", re.I)})
    meta_description = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    og_site = soup.find("meta", attrs={"property": "og:site_name"})
    title_tag = soup.find("title")
    title = normalise_space(title_tag.get_text()) if isinstance(title_tag, Tag) else None

    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for tag in soup.find_all(_REMOVE_TAGS):
        tag.decompose()
    for tag in soup.find_all(True):
        if isinstance(tag, Tag) and not tag.decomposed and _is_hidden(tag):
            tag.decompose()

    root = soup.body if isinstance(soup.body, Tag) else soup
    text = _clean_text(root)[:max_chars]
    headings = [h for h in (_clean_text(t) for t in root.find_all(["h1", "h2", "h3"]) if isinstance(t, Tag)) if h][:60]

    links: list[Link] = []
    document_links: list[str] = []
    for anchor in root.find_all("a", href=True):
        if not isinstance(anchor, Tag):
            continue
        href = str(anchor.get("href", "")).strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "data:", "#")):
            continue
        absolute = urldefrag(urljoin(url, href))[0]
        label = _clean_text(anchor)[:120]
        if absolute.lower().split("?")[0].endswith(_DOCUMENT_EXTENSIONS):
            document_links.append(label or absolute.rsplit("/", 1)[-1])
        links.append(Link(url=absolute, text=label))

    content = PageContent(
        url=url,
        title=title[:500] if title else None,
        description=normalise_space(str(meta_description.get("content", ""))) or None
        if isinstance(meta_description, Tag)
        else None,
        site_name=normalise_space(str(og_site.get("content", ""))) or None if isinstance(og_site, Tag) else None,
        text=text,
        headings=headings,
        links=links,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    if content.description is None:
        content.description = _first_paragraph(root)
    content.signals = _detect_signals(root, content, script_sources, generator, document_links)
    return content


def _form_signal(form: Tag, page: PageContent, category: str | None) -> Signal | None:
    fields = [f for f in form.find_all(["input", "textarea", "select"]) if isinstance(f, Tag)]
    visible = [f for f in fields if str(f.get("type", "text")).lower() not in ("hidden", "submit", "button")]
    if any(str(f.get("type", "")).lower() == "password" for f in fields):
        return None  # login form
    if len(visible) < 2 or str(form.get("role", "")).lower() == "search":
        return None
    labels = [_clean_text(label) for label in form.find_all("label") if isinstance(label, Tag)]
    form_text = _clean_text(form)
    # Classify on what the form *is* (page category, action, heading, submit label), not on field contents:
    # a freight inquiry form asking for a "booking reference" is not an appointment booking form.
    heading = form.find_previous(["h1", "h2", "h3"])
    submit = [
        _clean_text(b) or str(b.get("value", ""))
        for b in form.find_all(["button", "input"])
        if isinstance(b, Tag) and (b.name == "button" or str(b.get("type", "")).lower() == "submit")
    ]
    heading_text = _clean_text(heading) if isinstance(heading, Tag) else ""
    haystack = f"{form.get('action', '')} {heading_text} {' '.join(submit)}".lower()
    if category == "booking" or any(k in haystack for k in ("appointment", "book a", "book now", "reservation")):
        kind, label = EvidenceType.ONLINE_BOOKING, "an online booking form"
    elif any(k in haystack for k in ("quote", "estimate")):
        kind, label = EvidenceType.QUOTE_REQUEST_FORM, "a quote request form"
    else:
        kind, label = EvidenceType.CONTACT_FORM, "a contact or inquiry form"
    shown = ", ".join(lbl for lbl in labels if lbl)[:200]
    fact = f"The page offers {label} with {len(visible)} input fields" + (f" ({shown})" if shown else "") + "."
    excerpt = form_text[:300] if form_text and form_text[:40] in page.text else (page.title or label)
    return Signal(kind, fact, excerpt)


def _detect_signals(
    root: Tag,
    page: PageContent,
    script_sources: list[str],
    generator: object,
    document_links: list[str],
) -> list[Signal]:
    signals: list[Signal] = []
    path = urlsplit(page.url).path
    category = categorise(path) or ("home" if path in ("", "/") else None)

    description = page.description or page.site_name
    if description and category in ("home", "about"):
        excerpt: str | None = description if description in page.text else page.text[:300]
        signals.append(
            Signal(
                EvidenceType.COMPANY_DESCRIPTION,
                f"The website describes the company as: {description[:300]}",
                excerpt or description,
            )
        )
    elif category == "about" and page.text:
        signals.append(
            Signal(EvidenceType.COMPANY_DESCRIPTION, "The about page describes the company.", page.text[:300])
        )

    for form in root.find_all("form"):
        if isinstance(form, Tag) and (signal := _form_signal(form, page, category)):
            signals.append(signal)

    chat = next((p for p in _CHAT_PROVIDERS for src in script_sources if p in src), None)
    if chat:
        signals.append(
            Signal(
                EvidenceType.LIVE_CHAT,
                f"The page embeds a live-chat widget ({chat}).",
                f"[embedded script: {chat}]",
            )
        )
    booking = next((p for p in _BOOKING_PROVIDERS for src in script_sources if p in src), None)
    if booking:
        signals.append(
            Signal(
                EvidenceType.ONLINE_BOOKING,
                f"The page embeds an online booking widget ({booking}).",
                f"[embedded script: {booking}]",
            )
        )

    if document_links:
        names = ", ".join(document_links[:5])
        signals.append(
            Signal(
                EvidenceType.DOCUMENT_DOWNLOAD,
                f"The page links to {len(document_links)} downloadable document(s): {names}.",
                names[:300],
            )
        )

    if category == "faq":
        questions = [h for h in page.headings if h.endswith("?")]
        if len(questions) < 3:
            questions = [s.strip() + "?" for s in page.text.split("?")[:-1] if 10 < len(s.strip()) < 200]
        if len(questions) >= 3:
            signals.append(
                Signal(
                    EvidenceType.FAQ,
                    f"The website has an FAQ page with about {len(questions)} questions.",
                    questions[0][-300:],
                )
            )
    if category == "careers":
        roles = [h for h in page.headings[1:] if 3 < len(h) < 120][:5]
        hiring_excerpt = _sentence_with(page.text, ("hiring", "position", "vacanc", "join", "job")) or page.text[:200]
        fact = "The company advertises open positions" + (f": {', '.join(roles)}." if roles else ".")
        signals.append(Signal(EvidenceType.CAREERS_HIRING, fact, hiring_excerpt))
    if category == "services" and page.headings:
        offered = [h for h in page.headings[1:] if 2 < len(h) < 100][:8]
        if offered:
            signals.append(Signal(EvidenceType.SERVICE_OFFERING, f"Listed services: {', '.join(offered)}.", offered[0]))
    if category == "support" or "customer service" in page.text.lower():
        excerpt = _sentence_with(page.text, ("customer service", "support", "inquir", "return", "track", "hours"))
        if excerpt:
            signals.append(
                Signal(
                    EvidenceType.CUSTOMER_SUPPORT,
                    "The website describes customer service or support processes.",
                    excerpt,
                )
            )
    lower = page.text.lower()
    if any(k in lower for k in ("add to cart", "add to basket", "checkout", "free shipping", "order status")):
        excerpt = _sentence_with(page.text, ("add to cart", "add to basket", "checkout", "shipping", "order"))
        signals.append(Signal(EvidenceType.ECOMMERCE, "The website sells products online.", excerpt or page.text[:200]))
    if any(k in lower for k in ("upload", "invoices", "receipts", "documents", "paperwork", "forms")):
        excerpt = _sentence_with(page.text, ("upload", "invoices", "receipts", "documents", "paperwork", "forms"))
        if excerpt and category in ("services", "support", "about", "home", "technology"):
            signals.append(
                Signal(EvidenceType.DOCUMENT_WORKFLOW, "The website mentions document-based processes.", excerpt)
            )
    if isinstance(generator, Tag):
        content = str(generator.get("content", "")).lower()
        platform = next((g for g in _GENERATORS if g in content), None)
        if platform:
            signals.append(
                Signal(
                    EvidenceType.TECHNOLOGY_SIGNAL,
                    f"The website is built with {platform.title()}.",
                    f"[meta generator: {platform}]",
                )
            )
    return signals


def discover_relevant_links(links: list[Link], *, domain: str, limit: int) -> list[tuple[str, str]]:
    """Pick up to `limit` same-site pages, prioritising one per useful category. Returns (url, category)."""
    by_category: dict[str, list[str]] = {}
    seen: set[str] = set()
    for link in links:
        parts = urlsplit(link.url)
        if parts.scheme not in ("http", "https") or not same_site(parts.hostname or "", domain):
            continue
        if is_excluded_path(parts.path) or parts.query:
            continue
        key = (parts.path.rstrip("/") or "/").lower()
        if key == "/" or key in seen:
            continue
        category = categorise(parts.path, link.text)
        if category is None:
            continue
        seen.add(key)
        by_category.setdefault(category, []).append(link.url)
    chosen: list[tuple[str, str]] = []
    for rnd in range(3):  # round-robin across categories so each gets a page before any gets a second
        for category in CATEGORY_PRIORITY:
            urls = by_category.get(category, [])
            if rnd < len(urls) and len(chosen) < limit:
                chosen.append((urls[rnd], category))
    return chosen
