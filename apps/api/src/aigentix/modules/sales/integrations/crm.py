"""CRM provider contract, registry and a test double.

Exports are explicit, owner-confirmed and one-way; there is no background or continuous sync. No live provider is
bundled: the adapters below are documented future work and are NOT implemented (no fake success).

Contract (every adapter must satisfy it):

| Method                              | Behaviour                                                                      |
|-------------------------------------|--------------------------------------------------------------------------------|
| `health()`                          | cheap reachability / credential check; never raises, never returns secrets    |
| `upsert_company(payload, ext_id)`   | create when `ext_id` is None, otherwise update that record; returns external id |
| `upsert_contact(payload, ext_id)`   | same; only called for contacts that are neither suppressed nor restricted      |
| `upsert_deal(payload, ext_id)`      | same; `payload.company_external_id` links the deal to the company               |

Idempotency: re-sending the same payload with the stored external id updates in place and returns the same id.
Failures raise `CRMProviderError` (message must not contain credentials); the caller records a failed mapping.

Future adapters (not implemented): `hubspot` (companies / contacts / deals objects, private-app token) and
`pipedrive` (organizations / persons / deals, API token). Each would be a class here plus an entry in `_ADAPTERS`,
configured through `SALES_CRM_PROVIDERS` with credentials from the environment only.
"""

import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal, Protocol

from aigentix.modules.sales.config import SalesSettings, get_sales_settings


class CRMProviderError(Exception):
    """A provider call failed. The message is stored (sanitised) on the mapping, so keep it free of secrets."""


@dataclass(frozen=True)
class CompanyPayload:
    local_id: str
    name: str
    domain: str | None
    website_url: str | None


@dataclass(frozen=True)
class ContactPayload:
    local_id: str
    name: str
    role: str | None
    email: str | None
    phone: str | None
    company_external_id: str


@dataclass(frozen=True)
class DealPayload:
    local_id: str
    title: str
    stage: str
    status: str
    priority: str
    amount: Decimal | None
    currency: str
    expected_close_date: date | None
    won_value: Decimal | None
    lost_reason: str | None
    company_external_id: str


@dataclass(frozen=True)
class Health:
    status: Literal["ok", "degraded", "unavailable"]
    detail: str


class CRMProvider(Protocol):
    name: str
    test_double: bool

    def health(self) -> Health: ...

    def upsert_company(self, payload: CompanyPayload, external_id: str | None) -> str: ...

    def upsert_contact(self, payload: ContactPayload, external_id: str | None) -> str: ...

    def upsert_deal(self, payload: DealPayload, external_id: str | None) -> str: ...


@dataclass
class MockCRMProvider:
    """In-memory test double with deterministic external ids. Allowed only when "mock" is configured (never in
    production). Records every call; `fail_on` makes the named kinds ("company" | "contact" | "deal") raise."""

    name: str = "mock"
    test_double: bool = True
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[tuple[str, str | None]] = field(default_factory=list)  # (kind, external_id passed in)
    fail_on: set[str] = field(default_factory=set)

    def health(self) -> Health:
        return Health("ok", "In-memory test double; nothing leaves the process.")

    def _upsert(self, kind: str, local_id: str, payload: object, external_id: str | None) -> str:
        self.calls.append((kind, external_id))
        if kind in self.fail_on:
            raise CRMProviderError(f"mock {kind} upsert rejected")
        if external_id is None:
            external_id = f"mock-{kind}-{hashlib.sha256(local_id.encode()).hexdigest()[:12]}"
        elif external_id not in self.records:
            raise CRMProviderError(f"unknown external id for {kind}")
        self.records[external_id] = {"kind": kind, "payload": payload}
        return external_id

    def upsert_company(self, payload: CompanyPayload, external_id: str | None) -> str:
        return self._upsert("company", payload.local_id, payload, external_id)

    def upsert_contact(self, payload: ContactPayload, external_id: str | None) -> str:
        return self._upsert("contact", payload.local_id, payload, external_id)

    def upsert_deal(self, payload: DealPayload, external_id: str | None) -> str:
        return self._upsert("deal", payload.local_id, payload, external_id)


# name -> factory. Only the test double exists; HubSpot / Pipedrive are documented above, not implemented.
_ADAPTERS: dict[str, Callable[[], CRMProvider]] = {"mock": MockCRMProvider}
_instances: dict[str, CRMProvider] = {}
_lock = threading.Lock()


def configured_names(settings: SalesSettings | None = None) -> list[str]:
    return (settings or get_sales_settings()).crm_providers()


def get_crm_provider(name: str, settings: SalesSettings | None = None) -> CRMProvider | None:
    """The adapter for a configured provider, or None (unknown, unconfigured or no adapter bundled)."""
    name = name.strip().lower()
    if name not in configured_names(settings) or name not in _ADAPTERS:
        return None
    with _lock:
        if name not in _instances:
            _instances[name] = _ADAPTERS[name]()
        return _instances[name]


def reset_providers() -> None:
    """Forget cached adapter instances (tests)."""
    with _lock:
        _instances.clear()
