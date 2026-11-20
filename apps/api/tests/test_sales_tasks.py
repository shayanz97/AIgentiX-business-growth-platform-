"""Follow-up tasks, suggestions, summary and CSV export: unit tests (no DB) and API tests (tenant isolation)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from aigentix.core.errors import InvalidInput
from aigentix.modules.sales.domain.followup import DealState, boundaries, bucket, parse_tz, suggest
from aigentix.modules.sales.services.export import OPPORTUNITY_COLUMNS, cell, to_csv
from tests.conftest import Tenant, random_uuid
from tests.sales_helpers import move, new_deal

BERLIN = parse_tz("Europe/Berlin")
NOW = datetime(2026, 11, 18, 22, 30, tzinfo=UTC)  # 23:30 in Berlin (UTC+1)


# --- unit: buckets -----------------------------------------------------------------------------------------


def test_bucket_edges_in_berlin() -> None:
    b = boundaries(NOW, BERLIN)
    assert bucket(NOW - timedelta(seconds=1), "open", b) == "overdue"
    assert bucket(NOW + timedelta(minutes=10), "open", b) == "today"  # 23:40 Berlin
    assert bucket(NOW + timedelta(hours=1), "open", b) == "upcoming"  # 00:30 Berlin tomorrow
    # Last upcoming day is today + 7 (Nov 25 Berlin); Nov 26 00:00 Berlin is "later".
    assert bucket(datetime(2026, 11, 25, 22, 59, tzinfo=UTC), "open", b) == "upcoming"
    assert bucket(datetime(2026, 11, 25, 23, 0, tzinfo=UTC), "open", b) == "later"
    assert bucket(NOW - timedelta(days=3), "completed", b) == "completed"


def test_same_instant_is_today_in_utc_but_tomorrow_in_berlin() -> None:
    due = NOW + timedelta(hours=1)
    assert bucket(due, "open", boundaries(NOW, parse_tz("UTC"))) == "today"
    assert bucket(due, "open", boundaries(NOW, BERLIN)) == "upcoming"


def test_dst_day_boundary() -> None:
    now = datetime(2026, 3, 28, 12, 0, tzinfo=UTC)  # Berlin switches to CEST on 2026-03-29
    b = boundaries(now, BERLIN)
    assert b.tomorrow_start == datetime(2026, 3, 28, 23, 0, tzinfo=UTC)
    assert b.upcoming_end == datetime(2026, 4, 4, 22, 0, tzinfo=UTC)  # midnight CEST = 22:00 UTC


def test_invalid_timezone() -> None:
    with pytest.raises(InvalidInput):
        parse_tz("Mars/Olympus")
    with pytest.raises(InvalidInput):
        parse_tz("../etc/passwd")


# --- unit: suggestions ---------------------------------------------------------------------------------------


def _keys(**kw: Any) -> list[str]:
    base: dict[str, Any] = {"stage": "qualified", "has_brief": False, "days_since_contact": None}
    return [s.key for s in suggest(DealState(**{**base, **kw}))]


def test_suggestions_per_stage() -> None:
    assert _keys(stage="qualified") == ["review_research_findings"]
    assert _keys(stage="qualified", has_brief=True) == ["review_research_findings", "review_sales_brief"]
    assert _keys(stage="researching") == ["review_research_findings", "prepare_discovery_questions"]
    assert _keys(stage="contact_planned") == ["prepare_discovery_questions", "schedule_permitted_followup"]
    assert _keys(stage="in_conversation") == ["check_customer_reply"]
    assert _keys(stage="in_conversation", days_since_contact=1) == []
    assert _keys(stage="in_conversation", days_since_contact=9) == [
        "check_customer_reply",
        "schedule_permitted_followup",
    ]
    assert _keys(stage="proposal_sent") == ["review_submitted_proposal", "update_sales_outcome"]
    assert _keys(stage="won") == [] == _keys(stage="lost")


def test_suggestions_exclude_open_keys_and_never_imply_contact() -> None:
    assert _keys(stage="qualified", open_suggestion_keys=frozenset({"review_research_findings"})) == []
    for stage in ("qualified", "researching", "contact_planned", "in_conversation", "proposal_sent"):
        for s in suggest(DealState(stage=stage, has_brief=True, days_since_contact=20)):
            assert s.due_in_days >= 1
            if s.key == "schedule_permitted_followup":
                assert "permission" in s.reason
                assert "contacted" not in s.reason.lower()


# --- unit: CSV -----------------------------------------------------------------------------------------------


def test_csv_cells_are_formula_safe_and_escaped() -> None:
    assert cell('=HYPERLINK("x")') == '\'=HYPERLINK("x")'
    assert cell("+1") == "'+1"
    assert cell("-2") == "'-2"
    assert cell("@SUM(A1)") == "'@SUM(A1)"
    assert cell("\tx") == "'\tx"
    assert cell(None) == ""
    assert cell("plain") == "plain"
    out = to_csv(["a", "b"], [['he said "hi", ok', "=1+1"]])
    assert out == 'a,b\r\n"he said ""hi"", ok",\'=1+1\r\n'


# --- API -----------------------------------------------------------------------------------------------------


def _task(t: Tenant, deal_id: str, *, due: datetime | None = None, **extra: Any) -> dict[str, Any]:
    body = {
        "sales_opportunity_id": deal_id,
        "title": "Call prep",
        "due_at": (due or datetime.now(UTC) + timedelta(days=2)).isoformat(),
        **extra,
    }
    response = t.client.post("/api/v1/sales/tasks", json=body, headers=t.headers)
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def _list(t: Tenant, **params: Any) -> dict[str, Any]:
    response = t.client.get("/api/v1/sales/tasks", params=params, headers=t.headers)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_task_crud_reschedule_complete_reopen(tenant_a: Tenant) -> None:
    deal = new_deal(tenant_a)
    task = _task(tenant_a, deal["id"], description="Prepare")
    assert task["assigned_user_id"] == str(tenant_a.user.id)  # defaults to the current user
    assert task["deal_title"] == deal["title"]
    assert task["company_name"] == deal["company"]["name"]
    assert task["overdue"] is False
    url = f"/api/v1/sales/tasks/{task['id']}"
    new_due = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    patched = tenant_a.client.patch(url, json={"title": "Renamed", "due_at": new_due}, headers=tenant_a.headers)
    assert patched.status_code == 200
    assert patched.json()["title"] == "Renamed"
    done = tenant_a.client.patch(url, json={"status": "completed"}, headers=tenant_a.headers).json()
    assert done["status"] == "completed"
    assert done["completed_at"] is not None
    reopened = tenant_a.client.patch(url, json={"status": "open"}, headers=tenant_a.headers).json()
    assert reopened["status"] == "open"
    assert reopened["completed_at"] is None
    cancelled = tenant_a.client.patch(url, json={"status": "cancelled"}, headers=tenant_a.headers).json()
    assert cancelled["status"] == "cancelled"
    assert tenant_a.client.patch(url, json={}, headers=tenant_a.headers).status_code == 400
    assert tenant_a.client.patch(url, json={"status": "bogus"}, headers=tenant_a.headers).status_code == 422
    activities = tenant_a.client.get(
        f"/api/v1/sales/opportunities/{deal['id']}/activities", headers=tenant_a.headers
    ).json()
    texts = [a["description"] for a in activities if a["activity_type"] == "system"]
    assert any("rescheduled" in x for x in texts)
    assert any("completed" in x for x in texts)
    assert any("reopened" in x for x in texts)
    assert any("cancelled" in x for x in texts)


def test_task_validation(tenant_a: Tenant, tenant_b: Tenant) -> None:
    deal = new_deal(tenant_a)
    naive = tenant_a.client.post(
        "/api/v1/sales/tasks",
        json={"sales_opportunity_id": deal["id"], "title": "x", "due_at": "2026-12-01T10:00:00"},
        headers=tenant_a.headers,
    )
    assert naive.status_code == 422  # due_at must be timezone-aware
    due = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    outsider = tenant_a.client.post(
        "/api/v1/sales/tasks",
        json={
            "sales_opportunity_id": deal["id"],
            "title": "x",
            "due_at": due,
            "assigned_user_id": str(tenant_b.user.id),
        },
        headers=tenant_a.headers,
    )
    assert outsider.status_code == 400
    task = _task(tenant_a, deal["id"])
    bad = tenant_a.client.patch(
        f"/api/v1/sales/tasks/{task['id']}", json={"assigned_user_id": str(tenant_b.user.id)}, headers=tenant_a.headers
    )
    assert bad.status_code == 400
    unknown_deal = tenant_a.client.post(
        "/api/v1/sales/tasks",
        json={"sales_opportunity_id": random_uuid(), "title": "x", "due_at": due},
        headers=tenant_a.headers,
    )
    assert unknown_deal.status_code == 404


def test_views_filters_and_assignment(tenant_a: Tenant, member_of_a: Tenant) -> None:
    deal = new_deal(tenant_a)
    other = new_deal(tenant_a, domain="digitalwerk-solutions.example")
    now = datetime.now(UTC)
    overdue = _task(tenant_a, deal["id"], due=now - timedelta(days=1), title="late")
    later = _task(tenant_a, deal["id"], due=now + timedelta(days=3), title="soon")
    far = _task(tenant_a, deal["id"], due=now + timedelta(days=30), title="far")
    theirs = _task(
        tenant_a, other["id"], due=now + timedelta(days=4), title="theirs", assigned_user_id=str(member_of_a.user.id)
    )
    done = _task(tenant_a, deal["id"], due=now + timedelta(days=1), title="done")
    tenant_a.client.patch(f"/api/v1/sales/tasks/{done['id']}", json={"status": "completed"}, headers=tenant_a.headers)

    assert overdue["overdue"] is True
    ids = lambda **p: [i["id"] for i in _list(tenant_a, **p)["items"]]  # noqa: E731
    assert ids(view="overdue") == [overdue["id"]]
    assert set(ids(view="upcoming", tz="UTC")) == {later["id"], theirs["id"]}
    assert far["id"] in ids(view="open")
    assert done["id"] not in ids(view="open")
    assert ids(view="completed") == [done["id"]]
    assert len(ids(view="all")) == 5
    assert ids(view="open")[:2] == [overdue["id"], later["id"]]  # sorted by due_at
    assert theirs["id"] not in ids(mine="true")
    assert ids(assigned_user_id=str(member_of_a.user.id)) == [theirs["id"]]
    assert set(ids(sales_opportunity_id=other["id"])) == {theirs["id"]}
    assert _list(tenant_a, limit=2)["total"] == 4
    assert len(_list(tenant_a, limit=2)["items"]) == 2
    assert tenant_a.client.get("/api/v1/sales/tasks?tz=Nope/Zone", headers=tenant_a.headers).status_code == 400
    assert tenant_a.client.get("/api/v1/sales/tasks?view=weird", headers=tenant_a.headers).status_code == 422
    # A member sees the same org tasks; "mine" is relative to the caller.
    mine = [i["id"] for i in _list(member_of_a, mine="true")["items"]]
    assert mine == [theirs["id"]]

    summary = tenant_a.client.get("/api/v1/sales/tasks/summary?tz=UTC", headers=tenant_a.headers).json()
    assert summary == {
        "overdue": 1,
        "today": summary["today"],
        "upcoming": summary["upcoming"],
        "open": 4,
        "completed_last_7_days": 1,
        "mine_open": 3,
    }
    assert summary["overdue"] + summary["today"] + summary["upcoming"] <= summary["open"]
    assert tenant_a.client.get("/api/v1/sales/tasks/summary?tz=bad", headers=tenant_a.headers).status_code == 400


def test_task_suggestions_follow_recorded_state(tenant_a: Tenant) -> None:
    deal = new_deal(tenant_a)
    url = f"/api/v1/sales/opportunities/{deal['id']}/task-suggestions"
    first = tenant_a.client.get(url, headers=tenant_a.headers)
    assert first.status_code == 200
    assert [s["key"] for s in first.json()] == ["review_research_findings"]
    assert first.json()[0]["reason"]
    assert _list(tenant_a)["total"] == 0  # never auto-created
    _task(tenant_a, deal["id"], suggestion_key="review_research_findings")
    assert tenant_a.client.get(url, headers=tenant_a.headers).json() == []
    planned = move(tenant_a, deal, "contact_planned")
    assert planned.status_code == 200, planned.text
    keys = [s["key"] for s in tenant_a.client.get(url, headers=tenant_a.headers).json()]
    assert keys == ["prepare_discovery_questions", "schedule_permitted_followup"]
    assert (
        tenant_a.client.get(
            f"/api/v1/sales/opportunities/{random_uuid()}/task-suggestions", headers=tenant_a.headers
        ).status_code
        == 404
    )


def test_csv_export(tenant_a: Tenant) -> None:
    deal = new_deal(tenant_a)
    tenant_a.client.patch(
        f"/api/v1/sales/opportunities/{deal['id']}",
        json={"expected_version": deal["version"], "title": "=cmd|' /C calc'!A0"},
        headers=tenant_a.headers,
    )
    _task(tenant_a, deal["id"], title="@evil")
    response = tenant_a.client.get("/api/v1/sales/export", headers=tenant_a.headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    lines = response.text.strip().split("\r\n")
    assert lines[0] == ",".join(OPPORTUNITY_COLUMNS)
    assert len(lines) == 2
    assert "'=cmd" in lines[1]
    assert deal["company"]["canonical_domain"] in lines[1]
    tasks = tenant_a.client.get("/api/v1/sales/export?entity=tasks", headers=tenant_a.headers).text
    assert "'@evil" in tasks
    acts = tenant_a.client.get("/api/v1/sales/export?entity=activities", headers=tenant_a.headers).text
    assert "activity_type" in acts.split("\r\n")[0]
    assert "contact" not in acts.split("\r\n")[0]
    filtered = tenant_a.client.get("/api/v1/sales/export?stage=won", headers=tenant_a.headers).text
    assert len(filtered.strip().split("\r\n")) == 1
    assert tenant_a.client.get("/api/v1/sales/export?entity=contacts", headers=tenant_a.headers).status_code == 400
    assert tenant_a.client.get("/api/v1/sales/export?stage=nope", headers=tenant_a.headers).status_code == 400
    assert tenant_a.client.get("/api/v1/sales/export?status=nope", headers=tenant_a.headers).status_code == 400


def test_cross_tenant_isolation(tenant_a: Tenant, tenant_b: Tenant) -> None:
    deal = new_deal(tenant_a)
    task = _task(tenant_a, deal["id"])
    due = datetime.now(UTC).isoformat()
    h = tenant_b.headers
    assert tenant_b.client.patch(f"/api/v1/sales/tasks/{task['id']}", json={"title": "x"}, headers=h).status_code == 404
    assert (
        tenant_b.client.post(
            "/api/v1/sales/tasks", json={"sales_opportunity_id": deal["id"], "title": "x", "due_at": due}, headers=h
        ).status_code
        == 404
    )
    assert (
        tenant_b.client.get(f"/api/v1/sales/opportunities/{deal['id']}/task-suggestions", headers=h).status_code == 404
    )
    assert _list(tenant_b, view="all")["total"] == 0
    summary = tenant_b.client.get("/api/v1/sales/tasks/summary", headers=h).json()
    assert set(summary.values()) == {0}
    for entity in ("opportunities", "activities", "tasks"):
        body = tenant_b.client.get(f"/api/v1/sales/export?entity={entity}", headers=h).text
        assert len(body.strip().split("\r\n")) == 1  # header only


ENDPOINTS = [
    ("POST", "/api/v1/sales/tasks"),
    ("GET", "/api/v1/sales/tasks"),
    ("GET", "/api/v1/sales/tasks/summary"),
    ("PATCH", f"/api/v1/sales/tasks/{random_uuid()}"),
    ("GET", f"/api/v1/sales/opportunities/{random_uuid()}/task-suggestions"),
    ("GET", "/api/v1/sales/export"),
]


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
def test_auth_required(client: Any, method: str, path: str) -> None:
    assert client.request(method, path, json={}).status_code == 401


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
def test_spoofed_org_header_gets_403(tenant_a: Tenant, tenant_b: Tenant, method: str, path: str) -> None:
    response = tenant_b.client.request(method, path, json={"title": "x"}, headers=tenant_a.headers)
    assert response.status_code == 403
