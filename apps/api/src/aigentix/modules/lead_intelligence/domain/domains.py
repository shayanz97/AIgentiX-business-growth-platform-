"""Website URL / domain normalisation used for validation and organization-level deduplication."""

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp", ".intranet", ".arpa")
MAX_URL_LENGTH = 2048


class InvalidWebsite(ValueError):
    """The input is not a usable public company website."""


@dataclass(frozen=True)
class Website:
    url: str  # normalised homepage URL, e.g. https://acme.com/
    canonical_domain: str  # dedup key, e.g. acme.com


def _hostname(raw: str) -> str:
    host = raw.strip().rstrip(".").lower()
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise InvalidWebsite("Invalid domain name") from exc
    if len(host) > 253 or "." not in host:
        raise InvalidWebsite("A full domain name such as example.com is required")
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        raise InvalidWebsite("IP addresses are not accepted; use the company's domain name")
    if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
        raise InvalidWebsite("Internal or local domain names are not allowed")
    labels = host.split(".")
    if not all(_LABEL.match(label) for label in labels) or labels[-1].isdigit():
        raise InvalidWebsite("Invalid domain name")
    return host


def canonical_domain(host: str) -> str:
    """Dedup key: lower-case IDNA hostname without a leading `www.`."""
    host = _hostname(host)
    return host[4:] if host.startswith("www.") and host.count(".") >= 2 else host


def parse_website(value: str) -> Website:
    """Accept `acme.com`, `www.acme.com`, `https://acme.com/about` …; return the homepage + dedup domain."""
    raw = (value or "").strip()
    if not raw:
        raise InvalidWebsite("Website is required")
    if len(raw) > MAX_URL_LENGTH or any(ch.isspace() for ch in raw):
        raise InvalidWebsite("Invalid website URL")
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise InvalidWebsite("Only http and https websites are supported")
    if parts.username or parts.password:
        raise InvalidWebsite("URLs with credentials are not allowed")
    try:
        port = parts.port
    except ValueError as exc:
        raise InvalidWebsite("Invalid port") from exc
    if port not in (None, 80, 443):
        raise InvalidWebsite("Only standard web ports are allowed")
    host = _hostname(parts.hostname or "")
    return Website(url=f"{scheme}://{host}/", canonical_domain=canonical_domain(host))


def same_site(host: str, domain: str) -> bool:
    """True when `host` is the company's domain or its www. variant."""
    try:
        return canonical_domain(host) == domain
    except InvalidWebsite:
        return False
