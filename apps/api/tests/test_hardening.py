"""Security hardening and isolation edge cases (review findings H1, M2, M4, L1, L4, L5, L7)."""

import uuid
from datetime import timedelta

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from aigentix.api.app import create_app
from aigentix.api.deps import get_current_user, get_tenant
from aigentix.core.config import Settings
from aigentix.core.db import get_session_factory, utcnow
from aigentix.core.errors import Conflict
from aigentix.modules.lead_intelligence.models import ResearchProject
from aigentix.platform.identity import service as identity
from aigentix.platform.identity.models import User, UserSession
from aigentix.platform.identity.throttle import LoginThrottle, TooManyAttempts
from aigentix.platform.organizations import service as orgs
from aigentix.platform.organizations.models import Organization, Role
from aigentix.platform.workflows import service as workflows
from aigentix.platform.workflows.models import WorkflowRun, WorkflowStatus
from aigentix.platform.workflows.registry import WorkflowRegistry
from aigentix.platform.workflows.service import WorkflowError
from aigentix.worker.runner import housekeeping, run_once
from tests.conftest import PASSWORD, Tenant, login, make_user

# --- Route guard introspection -------------------------------------------------------------------

PUBLIC = {"/health", "/ready", "/api/v1/auth/login", "/api/v1/auth/logout"}
USER_SCOPED = {  # authenticated, organization taken from the path and verified in the route/service
    "/api/v1/me",
    "/api/v1/modules",
    "/api/v1/organizations",
    "/api/v1/organizations/{organization_id}",
    "/api/v1/organizations/{organization_id}/members",
}


def _dependency_calls(route: APIRoute) -> set[object]:
    calls: set[object] = set()
    stack = list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        calls.add(dep.call)
        stack.extend(dep.dependencies)
    return calls


def _api_routes(routes: list[object], prefix: str = "") -> list[tuple[str, APIRoute]]:
    """Flatten app routes into (full_path, route). FastAPI >= 0.16x keeps included routers nested."""
    found: list[tuple[str, APIRoute]] = []
    for r in routes:
        if isinstance(r, APIRoute):
            found.append((prefix + r.path, r))
        elif hasattr(r, "original_router"):
            ctx_prefix = getattr(getattr(r, "include_context", None), "prefix", "")
            found.extend(_api_routes(r.original_router.routes, ctx_prefix))
    return found


def test_every_api_route_is_guarded() -> None:
    """A new module route that forgets the `Tenant` dependency must fail CI."""
    routes = _api_routes(list(create_app().routes))
    paths = {path for path, _ in routes}
    assert {"/health", "/api/v1/auth/login", "/api/v1/projects", "/api/v1/workflows"} <= paths
    for path, route in routes:
        if path in PUBLIC:
            continue
        calls = _dependency_calls(route)
        if path in USER_SCOPED:
            assert get_current_user in calls, path
        else:
            assert get_tenant in calls, f"{route.methods} {path} is not tenant-scoped"


# --- Multi-organization user ---------------------------------------------------------------------


def test_user_in_two_orgs_only_sees_selected_org(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    org_b = db.get(Organization, tenant_b.org.id)
    user_a = db.get(User, tenant_a.user.id)
    assert org_b is not None
    assert user_a is not None
    orgs.add_member(db, organization=org_b, user=user_a, role=Role.MEMBER)
    db.commit()

    a_proj = tenant_a.client.post(
        "/api/v1/projects", json={"name": "A only"}, headers=tenant_a.headers
    ).json()
    b_proj = tenant_b.client.post(
        "/api/v1/projects", json={"name": "B only"}, headers=tenant_b.headers
    ).json()

    in_b = tenant_a.client.get("/api/v1/projects", headers=tenant_b.headers).json()
    assert [p["id"] for p in in_b["items"]] == [b_proj["id"]]
    in_a = tenant_a.client.get("/api/v1/projects", headers=tenant_a.headers).json()
    assert [p["id"] for p in in_a["items"]] == [a_proj["id"]]
    # Fetching Org A's project while Org B is selected is a 404, not a leak.
    wrong = tenant_a.client.get(f"/api/v1/projects/{a_proj['id']}", headers=tenant_b.headers)
    assert wrong.status_code == 404
    # Created in the selected org, never in the other one.
    created = tenant_a.client.post(
        "/api/v1/projects", json={"name": "into B"}, headers=tenant_b.headers
    ).json()
    assert created["organization_id"] == str(tenant_b.org.id)
    # Member (not owner) of B cannot rename B.
    assert (
        tenant_a.client.patch(f"/api/v1/organizations/{tenant_b.org.id}", json={"name": "x" * 5}).status_code
        == 403
    )


def test_workflow_filter_by_foreign_project_returns_nothing(tenant_a: Tenant, tenant_b: Tenant) -> None:
    project = tenant_a.client.post("/api/v1/projects", json={"name": "P"}, headers=tenant_a.headers).json()
    page = tenant_b.client.get(
        f"/api/v1/workflows?project_id={project['id']}", headers=tenant_b.headers
    ).json()
    assert page["total"] == 0


# --- Sessions ------------------------------------------------------------------------------------


def test_expired_session_is_rejected(tenant_a: Tenant, db: Session) -> None:
    db.execute(update(UserSession).values(expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()
    assert tenant_a.client.get("/api/v1/me").status_code == 401


def test_deactivated_user_existing_session_is_rejected(tenant_a: Tenant, db: Session) -> None:
    db.execute(update(User).where(User.id == tenant_a.user.id).values(is_active=False))
    db.commit()
    assert tenant_a.client.get("/api/v1/me").status_code == 401


def test_housekeeping_purges_expired_sessions(tenant_a: Tenant, db: Session) -> None:
    db.execute(update(UserSession).values(expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()
    housekeeping(get_session_factory(), stale_after=timedelta(minutes=30))
    assert db.scalar(select(func.count()).select_from(UserSession)) == 0


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/api/v1/auth/logout"), ("POST", "/api/v1/projects"), ("POST", "/api/v1/organizations")],
)
def test_foreign_origin_rejected_on_unsafe_routes(tenant_a: Tenant, method: str, path: str) -> None:
    response = tenant_a.client.request(
        method, path, json={"name": "csrf"}, headers={**tenant_a.headers, "Origin": "https://evil.example"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"
    assert tenant_a.client.get("/api/v1/me").status_code == 200  # session survived


# --- Login throttling ----------------------------------------------------------------------------


def test_login_is_throttled_per_account(client: TestClient, db: Session) -> None:
    make_user(db, "target@example.com")
    for _ in range(10):
        r = client.post(
            "/api/v1/auth/login", json={"email": "target@example.com", "password": "wrong-password"}
        )
        assert r.status_code == 401
    blocked = client.post("/api/v1/auth/login", json={"email": "TARGET@example.com", "password": PASSWORD})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "too_many_attempts"


def test_successful_login_resets_failures(client: TestClient, db: Session) -> None:
    make_user(db, "user@example.com")
    for _ in range(9):
        client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "wrong-password"})
    login(client, "user@example.com")
    for _ in range(9):
        r = client.post(
            "/api/v1/auth/login", json={"email": "user@example.com", "password": "wrong-password"}
        )
        assert r.status_code == 401


def test_throttle_window_expires() -> None:
    now = [0.0]
    throttle = LoginThrottle(max_failures=2, window_seconds=60, clock=lambda: now[0])
    throttle.record_failure("a")
    throttle.record_failure("a")
    with pytest.raises(TooManyAttempts):
        throttle.check("a")
    throttle.check("b")  # other accounts unaffected
    now[0] = 61
    throttle.check("a")


def test_throttle_memory_is_bounded() -> None:
    throttle = LoginThrottle(max_tracked_accounts=3)
    for i in range(10):
        throttle.record_failure(f"user{i}")
    assert len(throttle._failures) <= 3


# --- Worker robustness ---------------------------------------------------------------------------


def test_stale_running_runs_are_failed(db: Session, tenant_a: Tenant) -> None:
    run = WorkflowRun(
        organization_id=tenant_a.org.id,
        workflow_type="platform.noop",
        status=WorkflowStatus.RUNNING.value,
        started_at=utcnow() - timedelta(hours=2),
    )
    fresh = WorkflowRun(
        organization_id=tenant_a.org.id,
        workflow_type="platform.noop",
        status=WorkflowStatus.RUNNING.value,
        started_at=utcnow(),
    )
    db.add_all([run, fresh])
    db.commit()
    assert workflows.fail_stale_runs(db, older_than=timedelta(minutes=30)) == 1
    db.commit()
    db.refresh(run)
    db.refresh(fresh)
    assert run.status == WorkflowStatus.FAILED
    assert run.error_type == "StaleRun"
    assert fresh.status == WorkflowStatus.RUNNING


def _expected_failure(_db: Session, _run: WorkflowRun) -> None:
    raise WorkflowError("Website could not be reached")


def _unserialisable(_db: Session, _run: WorkflowRun) -> dict[str, object]:
    return {"bad": object()}  # cannot be stored as JSON -> commit fails


@pytest.mark.parametrize(
    ("handler", "error_type", "message"),
    [
        (_expected_failure, "WorkflowError", "Website could not be reached"),
        (_unserialisable, "TypeError", "The workflow failed due to an internal error."),
    ],
)
def test_worker_always_finalises_runs(
    db: Session, tenant_a: Tenant, handler: object, error_type: str, message: str
) -> None:
    registry = WorkflowRegistry()
    registry.register("test.handler", handler)  # type: ignore[arg-type]
    run = WorkflowRun(organization_id=tenant_a.org.id, workflow_type="test.handler")
    db.add(run)
    db.commit()
    assert run_once(get_session_factory(), registry) is True
    db.refresh(run)
    assert run.status == WorkflowStatus.FAILED
    assert run.error_message == message
    assert run.completed_at is not None
    assert error_type in (run.error_type or "")


# --- Misc ----------------------------------------------------------------------------------------


def test_production_requires_secure_cookies() -> None:
    with pytest.raises(ValidationError, match="SESSION_COOKIE_SECURE"):
        Settings(environment="production", session_cookie_secure=False, database_url="postgresql://u:p@h/db")  # type: ignore[arg-type]


def test_production_disables_interactive_docs() -> None:
    settings = Settings(
        environment="production",
        session_cookie_secure=True,
        database_url="postgresql://u:p@h/db",  # type: ignore[arg-type]
    )
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/v1/docs").status_code == 404


def test_ready_reports_pending_migrations(client: TestClient, db: Session) -> None:
    db.execute(text("UPDATE alembic_version SET version_num = 'old'"))
    db.commit()
    try:
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "migrations_pending"}
    finally:
        db.execute(text("UPDATE alembic_version SET version_num = '0001'"))
        db.commit()


@pytest.mark.parametrize("supplied", ["bad id with spaces", "x" * 65, "<script>"])
def test_unsafe_request_ids_are_replaced(client: TestClient, supplied: str) -> None:
    response = client.get("/health", headers={"X-Request-Id": supplied})
    assert response.headers["X-Request-Id"] != supplied
    uuid.UUID(response.headers["X-Request-Id"])


def test_valid_request_id_is_propagated(client: TestClient) -> None:
    assert client.get("/health", headers={"X-Request-Id": "abc-123"}).headers["X-Request-Id"] == "abc-123"


def test_duplicate_user_does_not_roll_back_caller_transaction(db: Session, tenant_a: Tenant) -> None:
    db.add(ResearchProject(organization_id=tenant_a.org.id, name="pending"))
    db.flush()
    with pytest.raises(Conflict):
        identity.create_user(db, email=tenant_a.user.email, password=PASSWORD)
    db.commit()
    assert db.scalar(select(func.count()).select_from(ResearchProject)) == 1
