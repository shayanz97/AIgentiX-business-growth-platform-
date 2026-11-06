"""SSRF and fetch-safety tests for SafeFetcher (direct URLs, DNS, redirects, sizes, timeouts, robots)."""

import httpx2
import pytest

from aigentix.modules.lead_intelligence.integrations.fetcher import (
    BlockedDestination,
    FetcherConfig,
    FetchError,
    ResponseTooLarge,
    SafeFetcher,
    TransientFetchError,
    is_public_address,
)
from aigentix.modules.lead_intelligence.integrations.robots import load_robots

PUBLIC_IP = "93.184.215.14"


def make_fetcher(
    handler: httpx2.MockTransport | None = None,
    dns: dict[str, list[str]] | None = None,
    **config: int,
) -> tuple[SafeFetcher, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []
    table = {"acme.example": [PUBLIC_IP], "www.acme.example": [PUBLIC_IP], **(dns or {})}

    def resolver(host: str, _port: int) -> list[str]:
        if host not in table:
            raise FetchError("The domain does not resolve")
        return table[host]

    def default(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, text="<p>ok</p>", headers={"content-type": "text/html"})

    def recording(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return (handler or default)(request)  # type: ignore[operator]

    fetcher = SafeFetcher(
        FetcherConfig(user_agent="test-bot", **config),  # type: ignore[arg-type]
        resolver=resolver,
        transport=httpx2.MockTransport(recording),
    )
    return fetcher, seen


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "240.0.0.1",
        "192.0.2.1",
        "198.18.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "64:ff9b::a00:1",
        "2002:a00:1::1",
        "fd00:ec2::254",
        "not-an-ip",
    ],
)
def test_non_public_addresses_are_rejected(address: str) -> None:
    assert is_public_address(address) is False


@pytest.mark.parametrize("address", ["93.184.215.14", "8.8.8.8", "2606:4700:4700::1111"])
def test_public_addresses_are_accepted(address: str) -> None:
    assert is_public_address(address) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost/",
        "http://[::1]/",
        "http://acme.example:8080/",
        "gopher://acme.example/",
        "file:///etc/passwd",
        "http://admin:secret@acme.example/",
        "http://metadata.google.internal/",
    ],
)
def test_ssrf_direct_urls_blocked_without_any_request(url: str) -> None:
    fetcher, seen = make_fetcher()
    with pytest.raises(BlockedDestination):
        fetcher.get(url)
    assert seen == []


@pytest.mark.parametrize(
    "addresses",
    [["10.0.0.5"], ["127.0.0.1"], ["169.254.169.254"], [PUBLIC_IP, "192.168.0.10"], ["::ffff:10.0.0.1"]],
)
def test_ssrf_via_dns_blocked(addresses: list[str]) -> None:
    """A public-looking name that resolves (even partly) to an internal address is refused."""
    fetcher, seen = make_fetcher(dns={"evil-rebind.example": addresses})
    with pytest.raises(BlockedDestination):
        fetcher.get("https://evil-rebind.example/")
    assert seen == []


def test_connection_is_pinned_to_validated_ip_with_original_host_and_sni() -> None:
    fetcher, seen = make_fetcher()
    page = fetcher.get("https://acme.example/about?x=1")
    assert page.ok
    request = seen[0]
    assert request.url.host == PUBLIC_IP  # no second DNS lookup can redirect the connection
    assert request.url.path == "/about"
    assert request.url.query == b"x=1"
    assert request.headers["host"] == "acme.example"
    assert request.extensions["sni_hostname"] == "acme.example"
    assert page.url == "https://acme.example/about?x=1"


@pytest.mark.parametrize(
    "location",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:8000/admin",
        "http://internal-svc.example/",  # resolves to a private address
        "file:///etc/passwd",
        "http://[::1]/",
    ],
)
def test_ssrf_via_redirect_blocked(location: str) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(302, headers={"location": location})

    fetcher, seen = make_fetcher(handler, dns={"internal-svc.example": ["10.0.0.7"]})  # type: ignore[arg-type]
    with pytest.raises(BlockedDestination):
        fetcher.get("https://acme.example/")
    assert len(seen) == 1  # the internal target was never contacted


def test_redirects_are_followed_with_revalidation_and_limit() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/start":
            return httpx2.Response(301, headers={"location": "https://www.acme.example/final"})
        if request.url.path == "/loop":
            return httpx2.Response(302, headers={"location": "/loop"})
        return httpx2.Response(200, text="<p>final</p>", headers={"content-type": "text/html"})

    fetcher, _ = make_fetcher(handler)  # type: ignore[arg-type]
    page = fetcher.get("https://acme.example/start")
    assert page.url == "https://www.acme.example/final"
    with pytest.raises(FetchError, match="Too many redirects"):
        fetcher.get("https://acme.example/loop")


def test_oversized_responses_rejected_by_header_and_by_stream() -> None:
    def declared(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, headers={"content-length": "999999999", "content-type": "text/html"}, content=b"x")

    fetcher, _ = make_fetcher(declared, max_bytes=1_000)  # type: ignore[arg-type]
    with pytest.raises(ResponseTooLarge):
        fetcher.get("https://acme.example/")

    def streamed(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=iter([b"a" * 600, b"b" * 600]), headers={"content-type": "text/html"})

    fetcher, _ = make_fetcher(streamed, max_bytes=1_000)  # type: ignore[arg-type]
    with pytest.raises(ResponseTooLarge):
        fetcher.get("https://acme.example/")


def test_timeouts_and_connection_errors_are_transient() -> None:
    def timeout(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    fetcher, _ = make_fetcher(timeout)  # type: ignore[arg-type]
    with pytest.raises(TransientFetchError):
        fetcher.get("https://acme.example/")

    def refused(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    fetcher, _ = make_fetcher(refused)  # type: ignore[arg-type]
    with pytest.raises(TransientFetchError):
        fetcher.get("https://acme.example/")


def test_unresolvable_domain_is_permanent() -> None:
    fetcher, _ = make_fetcher()
    with pytest.raises(FetchError) as info:
        fetcher.get("https://does-not-exist.example/")
    assert not info.value.transient


@pytest.mark.parametrize(
    ("status", "body", "allowed"),
    [
        (200, "User-agent: *\nDisallow: /private\n", {"/": True, "/private/x": False}),
        (200, "User-agent: AIgentiXResearchBot\nDisallow: /\n", {"/": False}),
        (404, "", {"/": True, "/anything": True}),
        (503, "", {"/": False}),
    ],
)
def test_robots_policy(status: int, body: str, allowed: dict[str, bool]) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, text=body, headers={"content-type": "text/plain"})

    fetcher, _ = make_fetcher(handler)  # type: ignore[arg-type]
    policy = load_robots(fetcher, "https://acme.example/", "AIgentiXResearchBot")
    for path, expected in allowed.items():
        assert policy.allows("AIgentiXResearchBot", f"https://acme.example{path}") is expected
