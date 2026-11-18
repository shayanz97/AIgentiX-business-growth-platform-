"""Offline web backend serving bundled fixture sites (`*.example`, RFC 2606) for tests, CI and demos.

It plugs into SafeFetcher as resolver + transport, so the real SSRF, redirect, size and robots logic runs.
Never enabled in production (see config validation).
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx2

FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "sites"
# Sprint 3 growth-trigger / intent scenarios (news, careers and tender pages).
ENRICHMENT_FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures" / "enrichment" / "sites"
# A global unicast address (TEST-NETs would be rejected by the SSRF guard). Nothing ever connects to it:
# the mock transport answers every request in-process.
FIXTURE_ADDRESS = "93.184.215.14"


@lru_cache
def _site(domain: str) -> dict[str, Any] | None:
    for root in (FIXTURE_ROOT, ENRICHMENT_FIXTURE_ROOT):
        folder = root / domain
        manifest = folder / "site.json"
        if manifest.is_file():
            break
    else:
        return None
    data: dict[str, Any] = json.loads(manifest.read_text(encoding="utf-8"))
    data["_folder"] = folder
    return data


def fixture_domains(root: Path = FIXTURE_ROOT) -> list[str]:
    return sorted(p.name for p in root.iterdir() if (p / "site.json").is_file())


def fixture_resolver(host: str, _port: int) -> list[str]:
    from aigentix.modules.lead_intelligence.integrations.fetcher import FetchError

    domain = host[4:] if host.startswith("www.") else host
    if _site(domain) is None:
        raise FetchError("The domain does not resolve")
    return [FIXTURE_ADDRESS]


def _handle(request: httpx2.Request) -> httpx2.Response:
    host = request.headers.get("host", "").split(":")[0]
    domain = host[4:] if host.startswith("www.") else host
    site = _site(domain)
    if site is None:
        return httpx2.Response(404)
    path = request.url.path.rstrip("/") or "/"
    if path == "/robots.txt":
        robots = site.get("robots")
        return httpx2.Response(200, text=robots) if robots is not None else httpx2.Response(404)
    if path in site.get("redirects", {}):
        return httpx2.Response(302, headers={"location": site["redirects"][path]})
    if path in site.get("status", {}):
        return httpx2.Response(int(site["status"][path]))
    filename = site.get("pages", {}).get(path)
    if filename is None:
        return httpx2.Response(404, text="Not found")
    body = (site["_folder"] / filename).read_bytes()
    return httpx2.Response(200, content=body, headers={"content-type": "text/html; charset=utf-8"})


def fixture_transport() -> httpx2.MockTransport:
    return httpx2.MockTransport(_handle)
