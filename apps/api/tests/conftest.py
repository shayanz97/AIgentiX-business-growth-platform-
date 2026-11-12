"""Test fixtures. Tests run against a real PostgreSQL database (TEST_DATABASE_URL), migrated with Alembic."""

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://aigentix:aigentix-local-dev@localhost:5432/aigentix_test"
)
# The suite drops and recreates the schema: refuse anything that is not clearly a test database.
if not TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?")[0].endswith("_test"):
    raise RuntimeError("TEST_DATABASE_URL must point to a database whose name ends with '_test'")
# Configure the application *before* importing it.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENVIRONMENT"] = "test"
os.environ["SESSION_COOKIE_SECURE"] = "false"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["LOG_JSON"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"
# Freshness bands are relative to "today": pin it so fixture dates keep their meaning (see enrichment fixtures).
os.environ["SCORING_REFERENCE_DATE"] = "2026-11-12"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from aigentix.api.app import create_app  # noqa: E402
from aigentix.core.config import get_settings  # noqa: E402
from aigentix.core.db import get_engine, get_session_factory  # noqa: E402
from aigentix.platform.identity import service as identity  # noqa: E402
from aigentix.platform.identity.models import User  # noqa: E402
from aigentix.platform.identity.throttle import login_throttle  # noqa: E402
from aigentix.platform.organizations import service as orgs  # noqa: E402
from aigentix.platform.organizations.models import Organization, Role  # noqa: E402

API_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASSWORD = "correct-horse-battery-staple"


def alembic_config(url: str) -> Config:
    cfg = Config(os.path.join(API_DIR, "alembic.ini"))
    cfg.attributes["database_url"] = get_settings().sqlalchemy_url if url == TEST_DATABASE_URL else url
    cfg.attributes["configure_logger"] = False
    return cfg


def reset_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    eng = get_engine()
    reset_schema(eng)
    command.upgrade(alembic_config(TEST_DATABASE_URL), "head")
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _reset_login_throttle() -> Iterator[None]:
    yield
    login_throttle._failures.clear()


@pytest.fixture(autouse=True)
def _clean_tables(request: pytest.FixtureRequest) -> Iterator[None]:
    yield
    if "engine" in request.fixturenames:
        with get_engine().begin() as conn:
            conn.execute(
                text(
                    "TRUNCATE lead_reviews, lead_score_evidence, lead_scores, scoring_profiles, icp_profiles, "
                    "buying_intent_evidence, buying_intent_signals, business_signal_evidence, business_signals, "
                    "opportunity_evidence, opportunities, evidence, research_sources, research_runs, "
                    "research_project_companies, companies, workflow_runs, research_projects, user_sessions, "
                    "organization_memberships, organizations, users CASCADE"
                )
            )


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with get_session_factory()() as session:
        yield session


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


@dataclass
class Tenant:
    user: User
    org: Organization
    client: TestClient

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Organization-Id": str(self.org.id)}


def make_user(db: Session, email: str) -> User:
    user = identity.create_user(db, email=email, password=PASSWORD, full_name=email.split("@")[0])
    db.commit()
    return user


def make_tenant(db: Session, email: str, org_name: str) -> tuple[User, Organization]:
    user = make_user(db, email)
    membership = orgs.create_organization(db, name=org_name, owner=user)
    db.commit()
    return user, membership.organization


def login(client: TestClient, email: str, password: str = PASSWORD) -> None:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


@pytest.fixture
def tenant_a(engine: Engine, db: Session) -> Iterator[Tenant]:
    user, org = make_tenant(db, "alice@a.example", "Org A")
    with TestClient(create_app()) as c:
        login(c, user.email)
        yield Tenant(user=user, org=org, client=c)


@pytest.fixture
def tenant_b(engine: Engine, db: Session) -> Iterator[Tenant]:
    user, org = make_tenant(db, "bob@b.example", "Org B")
    with TestClient(create_app()) as c:
        login(c, user.email)
        yield Tenant(user=user, org=org, client=c)


@pytest.fixture
def member_of_a(tenant_a: Tenant, db: Session) -> Iterator[Tenant]:
    user = make_user(db, "max@a.example")
    org = db.get(Organization, tenant_a.org.id)
    assert org is not None
    orgs.add_member(db, organization=org, user=user, role=Role.MEMBER)
    db.commit()
    with TestClient(create_app()) as c:
        login(c, user.email)
        yield Tenant(user=user, org=org, client=c)


def random_uuid() -> str:
    return str(uuid.uuid4())
