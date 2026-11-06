from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, inspect, text

from aigentix.core.config import get_settings
from aigentix.db_models import Base
from tests.conftest import TEST_DATABASE_URL, alembic_config, reset_schema


def test_health_is_ok_without_auth(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_checks_database(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_database_connection(engine: Engine) -> None:
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1


def test_models_match_migrations(engine: Engine) -> None:
    """The ORM models and the migrated schema must not drift."""
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == []


def test_migrations_apply_from_empty_database_and_downgrade(engine: Engine) -> None:
    url = get_settings().sqlalchemy_url
    scratch = create_engine(url)
    try:
        reset_schema(scratch)
        assert inspect(scratch).get_table_names() == []
        cfg = alembic_config(TEST_DATABASE_URL)
        command.upgrade(cfg, "head")
        tables = set(inspect(scratch).get_table_names())
        assert {
            "organizations",
            "users",
            "organization_memberships",
            "user_sessions",
            "research_projects",
            "workflow_runs",
        } <= tables
        command.downgrade(cfg, "base")
        assert set(inspect(scratch).get_table_names()) == {"alembic_version"}
        command.upgrade(cfg, "head")
    finally:
        scratch.dispose()


def test_openapi_document_is_served(client: TestClient) -> None:
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    for path in ("/api/v1/me", "/api/v1/organizations", "/api/v1/projects", "/api/v1/projects/{project_id}"):
        assert path in paths
