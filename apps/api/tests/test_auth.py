import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aigentix.platform.identity.models import User, UserSession
from tests.conftest import PASSWORD, Tenant, make_user

PROTECTED = [
    ("GET", "/api/v1/me"),
    ("GET", "/api/v1/organizations"),
    ("POST", "/api/v1/organizations"),
    ("GET", "/api/v1/modules"),
    ("GET", "/api/v1/projects"),
    ("POST", "/api/v1/projects"),
    ("GET", "/api/v1/projects/00000000-0000-0000-0000-000000000000"),
    ("GET", "/api/v1/workflows"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_protected_endpoints_require_authentication(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path, json={})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_login_sets_secure_session_cookie_and_stores_only_hash(client: TestClient, db: Session) -> None:
    make_user(db, "carol@example.com")
    response = client.post("/api/v1/auth/login", json={"email": "Carol@Example.com", "password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["email"] == "carol@example.com"
    assert "password_hash" not in response.json()

    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "SameSite=lax" in cookie_header
    token = response.cookies["aigx_session"]
    assert len(token) >= 40
    stored = db.scalars(select(UserSession.token_hash)).all()
    assert len(stored) == 1
    assert token not in stored  # only the SHA-256 digest is persisted

    assert client.get("/api/v1/me").status_code == 200


def test_password_is_hashed_with_argon2(db: Session) -> None:
    user = make_user(db, "dave@example.com")
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash


@pytest.mark.parametrize(
    ("email", "password"),
    [("carol@example.com", "wrong-password-123"), ("nobody@example.com", PASSWORD)],
)
def test_login_rejects_bad_credentials_uniformly(
    client: TestClient, db: Session, email: str, password: str
) -> None:
    make_user(db, "carol@example.com")
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid e-mail or password"
    assert "aigx_session" not in response.cookies


def test_inactive_user_cannot_login(client: TestClient, db: Session) -> None:
    user = make_user(db, "erin@example.com")
    user.is_active = False
    db.commit()
    response = client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert response.status_code == 401


def test_logout_revokes_server_side_session(tenant_a: Tenant, db: Session) -> None:
    client = tenant_a.client
    token = client.cookies["aigx_session"]
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert db.scalar(select(func.count()).select_from(UserSession)) == 0
    # Replaying the old cookie must not work after sign-out.
    client.cookies.set("aigx_session", token)
    assert client.get("/api/v1/me").status_code == 401


def test_login_rotates_existing_session(tenant_a: Tenant, db: Session) -> None:
    client = tenant_a.client
    old = client.cookies["aigx_session"]
    response = client.post("/api/v1/auth/login", json={"email": tenant_a.user.email, "password": PASSWORD})
    assert response.status_code == 200
    assert response.cookies["aigx_session"] != old
    assert db.scalar(select(func.count()).select_from(UserSession)) == 1


def test_forged_session_cookie_is_rejected(client: TestClient) -> None:
    client.cookies.set("aigx_session", "forged-token-value")
    assert client.get("/api/v1/me").status_code == 401


def test_validation_errors_do_not_echo_password(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"email": "not-an-email", "password": "s3cret-value"})
    assert response.status_code == 422
    assert "s3cret-value" not in response.text
    assert response.json()["error"]["code"] == "validation_error"


def test_cross_origin_unsafe_request_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "a@example.com", "password": "x"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"


def test_cors_allows_only_configured_origin(client: TestClient) -> None:
    ok = client.options(
        "/api/v1/me",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = client.options(
        "/api/v1/me",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in bad.headers


def test_me_returns_user_and_memberships(tenant_a: Tenant) -> None:
    body = tenant_a.client.get("/api/v1/me").json()
    assert body["user"]["email"] == "alice@a.example"
    assert [m["organization"]["name"] for m in body["memberships"]] == ["Org A"]
    assert body["memberships"][0]["role"] == "owner"


def test_emails_are_unique_case_insensitively(db: Session) -> None:
    from aigentix.core.errors import Conflict

    make_user(db, "frank@example.com")
    with pytest.raises(Conflict):
        make_user(db, "FRANK@example.com")
    assert db.scalar(select(func.count()).select_from(User)) == 1
