"""Deterministic growth-trigger detection: classify page segments, attach dates, and deduplicate mentions.

Signals are only created from text that states them; every candidate keeps the verbatim sentence it is based on.
Job postings of one company collapse into a single `hiring` signal (one trigger, with the roles listed), and
repeated announcements of the same event (news page, press page, homepage teaser) collapse into one signal whose
`mention_count` grows — repetition never multiplies the score.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date

from aigentix.modules.lead_intelligence.domain.dates import EventDate, ParsedDate, event_date, merge_dates
from aigentix.modules.lead_intelligence.integrations.segments import Segment
from aigentix.modules.lead_intelligence.models import SignalType

# Keyword stems per signal type, matched at word starts, case-insensitive (German and English).
SIGNAL_KEYWORDS: dict[SignalType, tuple[str, ...]] = {
    SignalType.PROCUREMENT_TENDER: (
        "ausschreibung", "öffentliche ausschreibung", "offenes verfahren", "vergabeverfahren", "vergabe",
        "angebotsfrist", "auftragnehmer", "tender", "invitation to tender", "procurement", "request for tender",
    ),
    SignalType.PUBLIC_PROJECT_REQUEST: (
        "projektanfrage", "wir suchen einen externen partner", "suchen einen externen", "externen partner",
        "suchen einen dienstleister", "dienstleister gesucht", "partner gesucht", "request for proposal",
        "looking for a partner", "looking for a provider", "seeking a provider", "seeking a partner",
        "we are looking for an agency", "angebote senden",
    ),
    SignalType.FUNDING: (
        "finanzierungsrunde", "finanzierung über", "series a", "series b", "series c", "seed-finanzierung",
        "seed round", "seed-runde", "funding round", "raised", "secured eur", "secured $", "kapitalerhöhung",
        "investoren", "investors", "investment round", "series-a",
    ),
    SignalType.EXPANSION: (
        "neuer standort", "neuen standort", "neues büro", "neuen büros", "neues werk", "erweiterung unseres",
        "erweitern die produktion", "eröffnet", "eröffnung", "niederlassung", "new location", "new office",
        "new warehouse", "new distribution", "opens", "opened", "expansion", "expands", "expand", "second warehouse",
        "zweiter standort", "logistikzentrum",
    ),
    SignalType.HIRING: (
        "wir stellen ein", "stellen ein", "suchen verstärkung", "we are hiring", "we're hiring", "now hiring",
        "join our team", "offene stellen", "(m/w/d)", "(w/m/d)", "stellenangebot", "open positions",
    ),
    SignalType.LEADERSHIP_CHANGE: (
        "neuer geschäftsführer", "neue geschäftsführerin", "geschäftsführung übernommen", "übernimmt die leitung",
        "new ceo", "appointed", "ernannt", "new managing director", "joins as", "neuer vorstand", "neue vorständin",
    ),
    SignalType.DIGITAL_TRANSFORMATION: (
        "digitalisierung", "digitalisierungsoffensive", "digitalisieren", "digital transformation", "digitalise",
        "digitalize", "papierlos", "paperless", "digitale prozesse", "digital processes",
    ),
    SignalType.TECHNOLOGY_ADOPTION: (
        "erp-system", "erp system", "neues erp", "crm-system", "crm system", "neue software", "new software",
        "implemented", "eingeführt", "einführung eines", "einführung einer", "migrated", "cloud-plattform",
        "goes live", "im echtbetrieb", "rolled out",
    ),
    SignalType.OPERATIONAL_CHANGE: (
        "kundenservice-team", "customer service team", "neues team", "new team", "servicezeiten",
        "umstrukturierung", "reorganisation", "reorganization", "service center", "servicecenter",
        "zentralisiert", "centralised", "centralized", "neue prozesse",
    ),
    SignalType.PRODUCT_LAUNCH: (
        "neues produkt", "neue produktlinie", "neu im sortiment", "neu:", "markteinführung", "ab sofort",
        "new product", "launches", "launched", "introduces", "now available", "neue serie", "product launch",
    ),
    SignalType.OTHER: ("partnerschaft", "partnership", "kooperation", "vertriebspartner", "zusammenarbeit"),
}  # fmt: skip

# Tie-break: more specific / more sales-relevant types first.
TYPE_PRIORITY: tuple[SignalType, ...] = (
    SignalType.PROCUREMENT_TENDER,
    SignalType.PUBLIC_PROJECT_REQUEST,
    SignalType.FUNDING,
    SignalType.HIRING,
    SignalType.LEADERSHIP_CHANGE,
    SignalType.DIGITAL_TRANSFORMATION,
    SignalType.TECHNOLOGY_ADOPTION,
    SignalType.EXPANSION,
    SignalType.OPERATIONAL_CHANGE,
    SignalType.PRODUCT_LAUNCH,
    SignalType.OTHER,
)
_HEADLINE_WEIGHT = 3
_STOPWORDS = {
    "der", "die", "das", "und", "oder", "für", "mit", "von", "den", "dem", "des", "ein", "eine", "einen", "unser",
    "unsere", "unseres", "unseren", "wir", "ihr", "sich", "auf", "aus", "bei", "zum", "zur", "the", "and", "for",
    "with", "our", "new", "neue", "neuer", "neues", "neuen", "into", "from", "this", "that",
}  # fmt: skip
_WORD = re.compile(r"[\wäöüß]+", re.I)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])(?<!\d\.)\s+")  # "3. November" is not a sentence end


def _matches(text: str, keyword: str) -> bool:
    if keyword[0].isalnum():
        return re.search(rf"(?<![\wäöüß]){re.escape(keyword)}", text, re.I) is not None
    return keyword.lower() in text.lower()


def classify(headline: str, text: str) -> tuple[SignalType, list[str]] | None:
    """Best-matching type for a segment and the keywords that matched; None when nothing matches."""
    body = text[len(headline) :] if headline and text.startswith(headline) else text
    best: tuple[int, int, SignalType, list[str]] | None = None
    for rank, kind in enumerate(TYPE_PRIORITY):
        hits_head = [k for k in SIGNAL_KEYWORDS[kind] if headline and _matches(headline, k)]
        hits_body = [k for k in SIGNAL_KEYWORDS[kind] if _matches(body, k)]
        score = _HEADLINE_WEIGHT * len(hits_head) + len(hits_body)
        if score and (best is None or (score, -rank) > (best[0], -best[1])):
            best = (score, rank, kind, sorted(set(hits_head + hits_body)))
    return (best[2], best[3]) if best else None


def supporting_sentence(text: str, keywords: list[str], limit: int = 300) -> str:
    """The first sentence of the segment containing a matched keyword (verbatim), else its start."""
    for sentence in _SENTENCE_SPLIT.split(text):
        if any(_matches(sentence, k) for k in keywords):
            return sentence[:limit].strip()
    return text[:limit].strip()


def _tokens(text: str) -> set[str]:
    return {w.lower()[:4] for w in _WORD.findall(text) if len(w) >= 4 and w.lower() not in _STOPWORDS}


def _numbers(text: str) -> set[str]:
    return {n.replace(",", ".") for n in re.findall(r"\d+(?:[.,]\d+)?", text) if not re.fullmatch(r"(19|20)\d\d", n)}


@dataclass
class Candidate:
    signal_type: SignalType
    segment: Segment
    keywords: list[str]
    excerpt: str
    date: EventDate


@dataclass
class DetectedSignal:
    signal_type: SignalType
    title: str
    summary: str
    candidates: list[Candidate]
    occurred: ParsedDate | None
    date_conflict: bool
    deadline: ParsedDate | None
    confidence: str
    dedupe_key: str
    details: dict[str, object] = field(default_factory=dict)

    @property
    def source_urls(self) -> list[str]:
        return sorted({c.segment.page_url for c in self.candidates})


@dataclass
class DetectionResult:
    signals: list[DetectedSignal]
    quarantined: list[Segment]  # segments that looked like prompt injection: never used as signals
    unclassified: int


def _same_event(a: Candidate, b: Candidate) -> bool:
    if a.signal_type != b.signal_type:
        return False
    head_a, head_b = _tokens(a.segment.headline or a.excerpt), _tokens(b.segment.headline or b.excerpt)
    if head_a and head_b:
        overlap = len(head_a & head_b) / len(head_a | head_b)
        if overlap >= 0.5 or (overlap >= 0.3 and _numbers(a.segment.text) & _numbers(b.segment.text)):
            return True
    return False


def _dedupe_key(kind: SignalType, title: str) -> str:
    basis = f"{kind.value}:{' '.join(sorted(_tokens(title)))}" if kind != SignalType.HIRING else "hiring:open-roles"
    return hashlib.sha256(basis.encode()).hexdigest()[:32]


def detect(segments: list[Segment], *, reference: date) -> DetectionResult:
    candidates: list[Candidate] = []
    quarantined: list[Segment] = []
    unclassified = 0
    for segment in segments:
        if segment.suspicious:
            quarantined.append(segment)
            continue
        if segment.kind == "job":
            kind, keywords = SignalType.HIRING, ["(m/w/d)"]
            excerpt = segment.headline or segment.text[:200]
        else:
            match = classify(segment.headline, segment.text)
            if match is None:
                unclassified += 1
                continue
            kind, keywords = match
            excerpt = supporting_sentence(segment.text, keywords)
        when = event_date(segment.machine_dates, segment.text, reference=reference, page_metadata=segment.page_dates)
        candidates.append(Candidate(kind, segment, keywords, excerpt, when))

    signals: list[DetectedSignal] = []
    jobs = [c for c in candidates if c.signal_type == SignalType.HIRING]
    if jobs:
        signals.append(_hiring_signal(jobs))
    clusters: list[list[Candidate]] = []
    for candidate in (c for c in candidates if c.signal_type != SignalType.HIRING):
        cluster = next((cl for cl in clusters if any(_same_event(candidate, other) for other in cl)), None)
        if cluster is None:
            clusters.append([candidate])
        else:
            cluster.append(candidate)
    for cluster in clusters:
        signals.append(_event_signal(cluster))
    signals.sort(key=lambda s: (TYPE_PRIORITY.index(s.signal_type), s.title))
    return DetectionResult(signals=signals, quarantined=quarantined, unclassified=unclassified)


def _confidence(cluster: list[Candidate]) -> str:
    strong_headline = any(any(_matches(c.segment.headline, k) for k in c.keywords) for c in cluster)
    return "high" if strong_headline else "medium"


def _event_signal(cluster: list[Candidate]) -> DetectedSignal:
    # Representative: the most detailed mention (longest text) — the press release rather than the teaser.
    main = max(cluster, key=lambda c: (len(c.segment.text), c.segment.page_url))
    merged = merge_dates([c.date.value for c in cluster if c.date.value is not None])
    deadlines = [c.date.deadline for c in cluster if c.date.deadline is not None]
    title = main.segment.headline or main.excerpt[:120]
    return DetectedSignal(
        signal_type=main.signal_type,
        title=title[:300],
        summary=main.excerpt,
        candidates=cluster,
        occurred=merged.value,
        date_conflict=merged.conflict,
        deadline=max(deadlines, key=lambda d: d.value) if deadlines else None,
        confidence="low" if merged.conflict else _confidence(cluster),
        dedupe_key=_dedupe_key(main.signal_type, title),
        details={"keywords": sorted({k for c in cluster for k in c.keywords})},
    )


def _hiring_signal(jobs: list[Candidate]) -> DetectedSignal:
    roles = list(dict.fromkeys(c.segment.headline or c.excerpt[:120] for c in jobs))
    dated = [c.date.value for c in jobs if c.date.value is not None]
    latest = max(dated, key=lambda d: d.value) if dated else None
    title = f"Hiring: {len(roles)} open role(s)" if len(roles) > 1 else f"Hiring: {roles[0]}"
    return DetectedSignal(
        signal_type=SignalType.HIRING,
        title=title[:300],
        summary="; ".join(roles)[:1000],
        candidates=jobs,
        occurred=latest,
        date_conflict=False,
        deadline=None,
        confidence="high" if any(c.segment.kind == "job" for c in jobs) else "medium",
        dedupe_key=_dedupe_key(SignalType.HIRING, title),
        details={
            "roles": roles[:20],
            "undated_roles": sum(1 for c in jobs if c.date.value is None),
            "date_basis": "most recent posting date" if latest else "no posting dates published",
        },
    )
