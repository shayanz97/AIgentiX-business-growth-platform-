"""Deterministic firmographic facts for ICP matching: country, industry statement and company size.

Each fact carries the verbatim sentence it comes from. Contradicting statements are reported as conflicts
(e.g. "team of 40" vs "over 200 employees"); nothing is guessed when the website says nothing.
"""

import re
from dataclasses import dataclass

# Country name forms → ISO code. Matched at word starts in sentences.
COUNTRIES: dict[str, tuple[str, ...]] = {
    "DE": ("deutschland", "germany", "bundesrepublik"),
    "AT": ("österreich", "austria"),
    "CH": ("schweiz", "switzerland"),
    "NL": ("niederlande", "netherlands"),
    "FR": ("frankreich", "france"),
    "PL": ("polen", "poland"),
    "GB": ("united kingdom", "großbritannien", "england"),
    "US": ("usa", "united states", "u.s.", "vereinigte staaten"),
}
_HQ_HINTS = ("sitz in", "based in", "headquartered", "hauptsitz", "located in", "ansässig")
_SENTENCES = re.compile(r"(?<=[.!?])(?<!\d\.)\s+")  # "3. November" is not a sentence end
_SIZE = re.compile(
    r"(?i)(?P<qual>rund|ca\.|circa|etwa|über|mehr als|knapp|around|about|approximately|over|more than)?\s*"
    r"(?P<n>\d{1,3}(?:[.,]\d{3})*|\d+)\s*"
    r"(?:mitarbeitende[n]?|mitarbeiter(?:innen)?|beschäftigte[n]?|angestellte[n]?|employees|staff|people)\b"
)
_TEAM = re.compile(r"(?i)(?:team (?:von|of))\s+(?P<n>\d{1,5})\b")
_INDUSTRY = re.compile(r"(?i)\b(?:branche|industry|sector|sektor)\s*:\s*(?P<v>[^.()]{2,80})")


@dataclass(frozen=True)
class Fact:
    value: str
    excerpt: str
    source_index: int  # index of the page text it came from


@dataclass(frozen=True)
class SizeFact:
    employees: int
    qualifier: str | None
    excerpt: str
    source_index: int


@dataclass
class Firmographics:
    countries: list[Fact]
    industry_statements: list[Fact]
    sizes: list[SizeFact]

    @property
    def country(self) -> str | None:
        """Headquarters country: a sentence with a location hint wins; otherwise a unique mentioned country."""
        hq = [f for f in self.countries if any(h in f.excerpt.lower() for h in _HQ_HINTS)]
        pool = hq or self.countries
        codes = {f.value for f in pool}
        return next(iter(codes)) if len(codes) == 1 else None

    @property
    def country_conflict(self) -> bool:
        hq = {f.value for f in self.countries if any(h in f.excerpt.lower() for h in _HQ_HINTS)}
        return len(hq) > 1 or (not hq and len({f.value for f in self.countries}) > 1)

    @property
    def employees(self) -> int | None:
        values = sorted({s.employees for s in self.sizes})
        if not values or self.size_conflict:
            return None
        return values[0]

    @property
    def size_conflict(self) -> bool:
        values = sorted({s.employees for s in self.sizes})
        return len(values) > 1 and values[-1] > values[0] * 1.5


def _matches(text: str, needle: str) -> bool:
    return re.search(rf"(?<![\wäöüß]){re.escape(needle)}(?![\wäöüß])", text, re.I) is not None


def extract_firmographics(texts: list[str]) -> Firmographics:
    countries: list[Fact] = []
    industries: list[Fact] = []
    sizes: list[SizeFact] = []
    for index, text in enumerate(texts):
        for sentence in _SENTENCES.split(text):
            if len(sentence) > 600:
                sentence = sentence[:600]
            for code, names in COUNTRIES.items():
                if any(_matches(sentence, n) for n in names):
                    countries.append(Fact(code, sentence.strip(), index))
            if m := _INDUSTRY.search(sentence):
                industries.append(Fact(m["v"].strip(" ,;"), sentence.strip(), index))
            for m in _SIZE.finditer(sentence):
                n = int(m["n"].replace(".", "").replace(",", ""))
                if 1 <= n <= 1_000_000:
                    sizes.append(SizeFact(n, (m["qual"] or "").lower() or None, sentence.strip(), index))
            for m in _TEAM.finditer(sentence):
                n = int(m["n"])
                if 1 <= n <= 100_000 and not any(s.excerpt == sentence.strip() and s.employees == n for s in sizes):
                    sizes.append(SizeFact(n, "team", sentence.strip(), index))
    return Firmographics(countries=countries, industry_statements=industries, sizes=sizes)


def mentions_any(text: str, keywords: list[str] | tuple[str, ...]) -> str | None:
    """The first keyword mentioned at a word start (prefix match: "tabak" matches "Tabakwaren")."""
    for keyword in keywords:
        if keyword and re.search(rf"(?<![\wäöüß]){re.escape(keyword)}", text, re.I):
            return keyword
    return None
