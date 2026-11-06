"""SSRF-safe public web fetching.

Rules applied to the first request and to every redirect hop:
  * only http/https on ports 80/443, no credentials in URLs, no IP-literal hosts, no internal TLDs;
  * the hostname is resolved once and **every** resolved address must be a global unicast address
    (blocks loopback, private, link-local/cloud metadata, CGNAT, multicast, reserved, NAT64/6to4 tunnels);
  * the connection is made to the validated IP with the original Host header and TLS SNI, so a second DNS
    answer (DNS rebinding) can never redirect the request;
  * redirects are followed manually (bounded), responses are streamed with a hard byte limit, and requests to
    the same domain are spaced by a minimum interval.
No proxies from the environment are used (they would resolve DNS themselves).
"""

import ipaddress
import socket
import ssl
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx2

from aigentix.modules.lead_intelligence.domain.domains import InvalidWebsite, parse_website

Resolver = Callable[[str, int], list[str]]

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_TUNNEL_NETWORKS = (
    ipaddress.ip_network("64:ff9b::/96"),  # NAT64 well-known prefix
    ipaddress.ip_network("64:ff9b:1::/48"),  # local-use NAT64
    ipaddress.ip_network("2002::/16"),  # 6to4
    ipaddress.ip_network("2001::/32"),  # Teredo
)


class FetchError(Exception):
    """A page could not be fetched. `transient` errors may succeed on retry."""

    transient = False

    def __init__(self, message: str, *, url: str | None = None) -> None:
        super().__init__(message)
        self.url = url


class BlockedDestination(FetchError):
    """The URL or one of its redirects points somewhere we must not connect to (SSRF guard)."""


class TransientFetchError(FetchError):
    transient = True


class ResponseTooLarge(FetchError):
    pass


def is_public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return is_public_address(str(address.ipv4_mapped))
        if any(address in network for network in _TUNNEL_NETWORKS):
            return False
    return bool(address.is_global and not address.is_multicast and not address.is_reserved)


def system_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        if exc.errno in (socket.EAI_AGAIN,):
            raise TransientFetchError("DNS lookup failed temporarily") from exc
        raise FetchError("The domain does not resolve") from exc
    addresses: list[str] = []
    for info in infos:
        ip = str(info[4][0])
        if ip not in addresses:
            addresses.append(ip)
    return addresses


class DomainRateLimiter:
    """Minimum spacing between requests to the same host (process-wide)."""

    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._next_slot: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_slot.get(host, 0.0))
            self._next_slot[host] = slot + self.min_interval
        delay = slot - now
        if delay > 0:
            time.sleep(delay)


@dataclass(frozen=True)
class FetchedPage:
    url: str  # final URL after redirects
    status: int
    content_type: str
    body: bytes

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def is_html(self) -> bool:
        return self.content_type in ("text/html", "application/xhtml+xml")


@dataclass(frozen=True)
class FetcherConfig:
    user_agent: str
    timeout_seconds: float = 10.0
    connect_timeout_seconds: float = 5.0
    max_bytes: int = 2_000_000
    max_redirects: int = 5
    # Wall-clock limit for one get() including redirects: read timeouts alone do not stop a slow-drip server.
    total_timeout_seconds: float = 30.0


class SafeFetcher:
    def __init__(
        self,
        config: FetcherConfig,
        *,
        resolver: Resolver = system_resolver,
        transport: httpx2.BaseTransport | None = None,
        rate_limiter: DomainRateLimiter | None = None,
    ) -> None:
        self.config = config
        self._resolver = resolver
        self._rate_limiter = rate_limiter or DomainRateLimiter(0)
        self._client = httpx2.Client(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            verify=ssl.create_default_context(),
            timeout=httpx2.Timeout(config.timeout_seconds, connect=config.connect_timeout_seconds),
            # No connection reuse: the pool is keyed by IP, so a kept-alive connection could otherwise serve a
            # different hostname without a certificate check for that name.
            limits=httpx2.Limits(max_keepalive_connections=0),
        )

    def close(self) -> None:
        self._client.close()

    def _validated_target(self, url: str) -> tuple[str, str, int, str]:
        """Return (scheme, host, port, ip) for a URL that passes every SSRF rule."""
        parts = urlsplit(url)
        try:
            parse_website(url)  # scheme, credentials, port, IP-literal and internal-name rules
        except InvalidWebsite as exc:
            raise BlockedDestination(f"Blocked URL: {exc}", url=url) from exc
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower().rstrip(".")
        port = parts.port or (443 if scheme == "https" else 80)
        addresses = self._resolver(host, port)
        if not addresses:
            raise FetchError("The domain does not resolve", url=url)
        if not all(is_public_address(ip) for ip in addresses):
            raise BlockedDestination("Blocked URL: the domain resolves to a non-public address", url=url)
        return scheme, host, port, addresses[0]

    def get(self, url: str) -> FetchedPage:
        current = url
        deadline = time.monotonic() + self.config.total_timeout_seconds
        for _hop in range(self.config.max_redirects + 1):
            if time.monotonic() > deadline:
                raise TransientFetchError("The website responded too slowly", url=current)
            scheme, host, port, ip = self._validated_target(current)
            parts = urlsplit(current)
            ip_host = f"[{ip}]" if ":" in ip else ip
            target = f"{scheme}://{ip_host}:{port}{parts.path or '/'}"
            if parts.query:
                target += f"?{parts.query}"
            default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
            headers = {
                "Host": host if default_port else f"{host}:{port}",
                "User-Agent": self.config.user_agent,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.1",
                # No compression: avoids decompression bombs inflating far past the byte limit in memory.
                "Accept-Encoding": "identity",
            }
            self._rate_limiter.wait(host)
            request = self._client.build_request(
                "GET", target, headers=headers, extensions={"sni_hostname": host} if scheme == "https" else {}
            )
            try:
                response = self._client.send(request, stream=True)
            except httpx2.TimeoutException as exc:
                raise TransientFetchError("The website did not respond in time", url=current) from exc
            except httpx2.TransportError as exc:
                raise TransientFetchError("Could not connect to the website", url=current) from exc
            try:
                if response.status_code in REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        raise FetchError("Redirect without a location", url=current)
                    current = urljoin(current, location)
                    continue
                body = self._read_limited(response, current, deadline)
                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                return FetchedPage(url=current, status=response.status_code, content_type=content_type, body=body)
            finally:
                response.close()
        raise FetchError("Too many redirects", url=current)

    def _read_limited(self, response: httpx2.Response, url: str, deadline: float) -> bytes:
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self.config.max_bytes:
            raise ResponseTooLarge("The page is larger than the allowed size", url=url)
        chunks: list[bytes] = []
        size = 0
        try:
            for chunk in response.iter_bytes():
                if time.monotonic() > deadline:
                    raise TransientFetchError("The website responded too slowly", url=url)
                size += len(chunk)
                if size > self.config.max_bytes:
                    raise ResponseTooLarge("The page is larger than the allowed size", url=url)
                chunks.append(chunk)
        except httpx2.TimeoutException as exc:
            raise TransientFetchError("The website stopped responding", url=url) from exc
        except httpx2.TransportError as exc:
            raise TransientFetchError("The connection to the website failed", url=url) from exc
        return b"".join(chunks)
