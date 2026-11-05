import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from aigentix.core.db import get_session_factory
from aigentix.core.errors import InvalidInput
from aigentix.modules.lead_intelligence import service as projects
from aigentix.modules.lead_intelligence.schemas import ProjectCreate
from aigentix.platform.organizations.models import Organization
from aigentix.platform.organizations.service import resolve_tenant
from aigentix.platform.workflows import service
from aigentix.platform.workflows.models import WorkflowRun, WorkflowStatus
from aigentix.platform.workflows.registry import NOOP_WORKFLOW, WorkflowRegistry, build_registry
from aigentix.worker.runner import run_once
from tests.conftest import Tenant


def _boom(_db: Session, _run: WorkflowRun) -> None:
    raise RuntimeError("upstream exploded")


@pytest.fixture
def registry() -> WorkflowRegistry:
    reg = build_registry()
    reg.register("test.failing", _boom)
    return reg


def _tenant(db: Session, t: Tenant):  # type: ignore[no-untyped-def]
    return resolve_tenant(db, user=t.user, organization_id=t.org.id)


def test_registry_contains_platform_workflow() -> None:
    assert NOOP_WORKFLOW in build_registry()


def test_registry_rejects_duplicates(registry: WorkflowRegistry) -> None:
    with pytest.raises(ValueError, match="already registered"):
        registry.register(NOOP_WORKFLOW, _boom)


def test_enqueue_rejects_unknown_type(db: Session, tenant_a: Tenant, registry: WorkflowRegistry) -> None:
    with pytest.raises(InvalidInput):
        service.enqueue(db, _tenant(db, tenant_a), workflow_type="nope", registry=registry)


def test_worker_executes_queued_run(db: Session, tenant_a: Tenant, registry: WorkflowRegistry) -> None:
    run = service.enqueue(
        db, _tenant(db, tenant_a), workflow_type=NOOP_WORKFLOW, registry=registry, metadata={"input": 42}
    )
    db.commit()
    assert run_once(get_session_factory(), registry) is True
    db.refresh(run)
    assert run.status == WorkflowStatus.SUCCEEDED
    assert run.started_at is not None
    assert run.completed_at is not None
    assert run.completed_at >= run.started_at
    assert run.attempts == 1
    assert run.run_metadata["result"] == {"echo": 42}
    assert run_once(get_session_factory(), registry) is False  # queue drained


def test_worker_records_failures(db: Session, tenant_a: Tenant, registry: WorkflowRegistry) -> None:
    run = service.enqueue(db, _tenant(db, tenant_a), workflow_type="test.failing", registry=registry)
    db.commit()
    run_once(get_session_factory(), registry)
    db.refresh(run)
    assert run.status == WorkflowStatus.FAILED
    assert run.error_type == "RuntimeError"
    assert run.error_message == "upstream exploded"
    assert run.completed_at is not None


def test_worker_fails_runs_without_handler(db: Session, tenant_a: Tenant, registry: WorkflowRegistry) -> None:
    run = WorkflowRun(organization_id=tenant_a.org.id, workflow_type="removed.workflow")
    db.add(run)
    db.commit()
    run_once(get_session_factory(), WorkflowRegistry())
    db.refresh(run)
    assert run.status == WorkflowStatus.FAILED
    assert run.error_type == "UnknownWorkflowType"


def test_workflow_listing_is_tenant_scoped(
    db: Session, tenant_a: Tenant, tenant_b: Tenant, registry: WorkflowRegistry
) -> None:
    project = projects.create_project(db, _tenant(db, tenant_a), ProjectCreate(name="P"))
    service.enqueue(
        db, _tenant(db, tenant_a), workflow_type=NOOP_WORKFLOW, registry=registry, project_id=project.id
    )
    db.commit()

    mine = tenant_a.client.get("/api/v1/workflows", headers=tenant_a.headers).json()
    assert mine["total"] == 1
    assert mine["items"][0]["status"] == "queued"
    assert mine["items"][0]["project_id"] == str(project.id)
    by_project = tenant_a.client.get(
        f"/api/v1/workflows?project_id={project.id}", headers=tenant_a.headers
    ).json()
    assert by_project["total"] == 1

    theirs = tenant_b.client.get("/api/v1/workflows", headers=tenant_b.headers).json()
    assert theirs["total"] == 0


def test_database_rejects_run_linking_project_of_other_org(
    db: Session, tenant_a: Tenant, tenant_b: Tenant
) -> None:
    """Composite FK: a run in Org B cannot reference a project of Org A."""
    project = projects.create_project(db, _tenant(db, tenant_a), ProjectCreate(name="P"))
    db.commit()
    org_b = db.get(Organization, tenant_b.org.id)
    assert org_b is not None
    db.add(WorkflowRun(organization_id=org_b.id, project_id=project.id, workflow_type=NOOP_WORKFLOW))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_invalid_status_rejected_by_database(db: Session, tenant_a: Tenant) -> None:
    db.add(WorkflowRun(id=uuid.uuid4(), organization_id=tenant_a.org.id, workflow_type="x", status="bogus"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
