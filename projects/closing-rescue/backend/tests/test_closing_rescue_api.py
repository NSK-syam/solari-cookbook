"""HTTP contract for the immutable Closing Rescue investigation read model."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from septic_sentinel import api
from septic_sentinel.config import Settings
from septic_sentinel.runtime import build_service

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "cases"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    case_service = build_service(
        Settings(
            mode="fixture",
            db_path=tmp_path / "closing-rescue-api.sqlite3",
            fixture_root=FIXTURE_ROOT,
        )
    )
    monkeypatch.setattr(api, "service", case_service)
    monkeypatch.setattr(api, "solari_execution_service", None)
    with TestClient(api.app) as test_client:
        yield test_client


def _create(client: TestClient, key: str = "demo-v2"):
    return client.post("/api/v2/closing-rescue/demo", headers={"Idempotency-Key": key})


def _approval_request(body: dict, **changes: object) -> dict:
    approval = body["approval"]
    request = {
        "approval_id": approval["id"],
        "approver_identity": approval["approver_identity"],
        "approval_token": body["approval_token"],
        "approve": True,
        "simulate_timeout": False,
    }
    return {**request, **changes}


def test_solari_proof_refuses_to_fake_a_cloud_run_without_a_key(
    client: TestClient,
) -> None:
    portfolio_id = _create(client, "missing-solari-key").json()["portfolio_id"]

    response = client.post(f"/api/v2/closing-rescue/{portfolio_id}/solari")

    assert response.status_code == 503
    assert response.json() == {"detail": "SOLARI_API_KEY is not configured"}


def test_demo_read_model_contains_truth_labels_citations_and_explicit_batches(
    client: TestClient,
) -> None:
    response = _create(client)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["selected_case"]["external_loan_id"] == "CR-0047"
    assert body["portfolio_summary"] == {
        "loan_count": 47,
        "pipeline_value_cents": 1_420_000_000,
        "attention_candidate_count": 4,
        "total_estimated_exposure_cents": sum(
            item["exposure_without_intervention_cents"]
            for item in body["priority"]["initial"]
        ),
        "truth_class": "synthetic",
    }
    assert body["exposure"]["preventable_cents"] == 1_320_000
    assert body["seller_claim"]["truth_class"] == "synthetic"
    assert body["seller_claim"]["value"] == 2018
    assert body["permit_claim"]["truth_class"] == "external_cited"
    assert body["permit_claim"]["value"] == 1991
    assert body["permit_claim"]["citation_ids"]
    assert body["evidence"]
    assert all(item["truth_class"] == "external_cited" for item in body["evidence"])
    assert all(item["retrieved_at"] for item in body["evidence"])
    successful = [item for item in body["evidence"] if item["status"] == "success"]
    assert all(item["citations"] for item in successful)
    assert all(citation["retrieved_at"] for item in successful for citation in item["citations"])
    assert body["priority"]["initial_batch_id"] == body["priority"]["current_batch_id"]
    assert body["priority"]["initial"] == body["priority"]["current"]
    assert body["priority"]["truth_class"] == "synthetic"
    assert body["exposure"]["truth_class"] == "synthetic"
    assert body["approval"]["state"] == "pending"
    assert body["approval_token"]
    serialized = response.text.lower()
    assert "token_hash" not in serialized
    assert "idempotency_key" not in body["selected_case"]


def test_demo_is_idempotent_and_token_is_returned_only_on_creation(
    client: TestClient,
) -> None:
    first = _create(client, "same-demo")
    replay = _create(client, "same-demo")

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["portfolio_id"] == first.json()["portfolio_id"]
    assert replay.json()["approval_token"] is None
    assert replay.json()["story_events"] == first.json()["story_events"]


def test_true_concurrent_demo_creation_delivers_exactly_one_token(
    client: TestClient,
) -> None:
    def create() -> tuple[int, dict]:
        response = _create(client, "concurrent-api-demo")
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: create(), range(2)))

    assert sorted(status for status, _ in responses) == [200, 201]
    bodies = [body for _, body in responses]
    assert len({body["portfolio_id"] for body in bodies}) == 1
    assert sum(body["approval_token"] is not None for body in bodies) == 1
    assert bodies[0]["story_events"] == bodies[1]["story_events"]


def test_resume_after_pre_token_crash_returns_new_token_without_false_creation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = api.service.create_and_collect
    crashed = False

    async def fail_once(*args, **kwargs):
        nonlocal crashed
        if not crashed:
            crashed = True
            raise RuntimeError("private pre-token crash detail")
        return await original(*args, **kwargs)

    monkeypatch.setattr(api.service, "create_and_collect", fail_once)
    first = _create(client, "resume-api-demo")
    resumed = _create(client, "resume-api-demo")
    replay = _create(client, "resume-api-demo")

    assert first.status_code == 500
    assert first.json() == {"detail": "Closing Rescue encountered an unexpected error"}
    assert "private pre-token" not in first.text
    assert resumed.status_code == 200
    assert resumed.json()["approval_token"]
    assert replay.status_code == 200
    assert replay.json()["approval_token"] is None


def test_get_and_event_cursor_reconstruct_persisted_state_without_secret(
    client: TestClient,
) -> None:
    created = _create(client).json()
    portfolio_id = created["portfolio_id"]

    fetched = client.get(f"/api/v2/closing-rescue/{portfolio_id}")
    assert fetched.status_code == 200
    assert fetched.json()["approval_token"] is None
    assert fetched.json()["priority"]["truth_class"] == "synthetic"
    assert fetched.json()["exposure"]["truth_class"] == "synthetic"
    assert fetched.json()["story_events"] == created["story_events"]

    events = created["story_events"]
    cursor = events[2]["id"]
    tail = client.get(f"/api/v2/closing-rescue/{portfolio_id}/events", params={"after": cursor})
    assert tail.status_code == 200
    assert tail.json() == events[3:]

    all_events = client.get(f"/api/v2/closing-rescue/{portfolio_id}/events")
    assert all_events.json() == events
    unknown = client.get(
        f"/api/v2/closing-rescue/{portfolio_id}/events", params={"after": "evt_unknown"}
    )
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "Story event not found"}


def test_approval_success_replay_and_reload_are_coherent(client: TestClient) -> None:
    proposed = _create(client).json()
    portfolio_id = proposed["portfolio_id"]
    request = _approval_request(proposed)

    approved = client.post(f"/api/v2/closing-rescue/{portfolio_id}/approve", json=request)
    replay = client.post(f"/api/v2/closing-rescue/{portfolio_id}/approve", json=request)
    fetched = client.get(f"/api/v2/closing-rescue/{portfolio_id}")

    assert approved.status_code == 200, approved.text
    assert replay.status_code == 200, replay.text
    assert fetched.status_code == 200
    body = approved.json()
    assert body["approval"]["state"] == "consumed"
    assert body["case_state"] == "monitoring"
    assert body["exposure"]["after_action_cents"] == 480_000
    assert body["exposure"]["preventable_cents"] == 0
    assert body["exposure"]["truth_class"] == "synthetic"
    assert body["priority"]["truth_class"] == "synthetic"
    assert body["priority"]["initial_batch_id"] != body["priority"]["current_batch_id"]
    initial_hero = body["priority"]["initial"][0]
    current_hero = next(
        item for item in body["priority"]["current"] if item["external_loan_id"] == "CR-0047"
    )
    assert initial_hero["preventable_exposure_cents"] == 1_320_000
    assert current_hero["preventable_exposure_cents"] == 0
    assert len(body["actions"]) == 1
    assert replay.json()["actions"] == body["actions"]
    assert fetched.json()["actions"] == body["actions"]
    assert fetched.json()["exposure"]["truth_class"] == "synthetic"
    assert fetched.json()["priority"]["truth_class"] == "synthetic"
    assert fetched.json()["approval_token"] is None


@pytest.mark.parametrize(
    ("change", "status_code", "detail"),
    [
        ({"approval_token": "bad-token"}, 403, "Approval token is invalid"),
        (
            {"approver_identity": "attacker@example.test"},
            403,
            "Approver identity does not match the case",
        ),
        ({"approval_id": "apr_missing"}, 404, "Approval not found"),
    ],
)
def test_approval_errors_are_stable_domain_responses(
    client: TestClient, change: dict, status_code: int, detail: str
) -> None:
    proposed = _create(client).json()
    response = client.post(
        f"/api/v2/closing-rescue/{proposed['portfolio_id']}/approve",
        json=_approval_request(proposed, **change),
    )

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}


def test_rejection_and_unknown_outcomes_are_readable_and_not_retried(
    client: TestClient,
) -> None:
    rejected = _create(client, "reject-demo").json()
    rejection = client.post(
        f"/api/v2/closing-rescue/{rejected['portfolio_id']}/approve",
        json=_approval_request(rejected, approve=False),
    )
    assert rejection.status_code == 200
    assert rejection.json()["approval"]["state"] == "rejected"
    assert rejection.json()["actions"] == []

    unknown = _create(client, "unknown-demo").json()
    request = _approval_request(unknown, simulate_timeout=True)
    timed_out = client.post(
        f"/api/v2/closing-rescue/{unknown['portfolio_id']}/approve", json=request
    )
    replay = client.post(f"/api/v2/closing-rescue/{unknown['portfolio_id']}/approve", json=request)
    assert timed_out.status_code == 200
    assert timed_out.json()["actions"][0]["state"] == "unknown"
    assert replay.status_code == 200
    assert replay.json()["actions"] == timed_out.json()["actions"]


def test_missing_and_invalid_requests_do_not_raise_raw_server_errors(
    client: TestClient,
) -> None:
    assert _create(client, "   ").status_code == 422
    missing = client.get("/api/v2/closing-rescue/portfolio_missing")
    missing_events = client.get("/api/v2/closing-rescue/portfolio_missing/events")
    missing_approve = client.post(
        "/api/v2/closing-rescue/portfolio_missing/approve",
        json={
            "approval_id": "apr_missing",
            "approver_identity": "ops@example.test",
            "approval_token": "unused-token",
            "approve": True,
        },
    )
    assert missing.status_code == 404
    assert missing_events.status_code == 404
    assert missing_approve.status_code == 404
    assert missing.json() == {"detail": "Closing Rescue portfolio not found"}


@pytest.mark.parametrize("bad_approve", ["yes", 1, 0])
def test_approval_boolean_is_strict(client: TestClient, bad_approve: object) -> None:
    proposed = _create(client).json()
    response = client.post(
        f"/api/v2/closing-rescue/{proposed['portfolio_id']}/approve",
        json=_approval_request(proposed, approve=bad_approve),
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "approve"


def test_idempotency_key_limit_is_enforced_before_service_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    called = False

    async def should_not_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("service was called")

    monkeypatch.setattr(
        api.ClosingRescueService, "create_competition_demo_delivery", should_not_run
    )
    response = _create(client, "x" * 201)

    assert response.status_code == 422
    assert called is False


@pytest.mark.parametrize(
    "fault",
    [RuntimeError("private runtime detail"), ValueError("private decoding detail")],
)
def test_unexpected_faults_are_generic_500_without_internal_strings(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, fault: Exception
) -> None:
    created = _create(client).json()

    def fail(_: object):
        raise fault

    monkeypatch.setattr(api, "_claim_views", fail)
    response = client.get(f"/api/v2/closing-rescue/{created['portfolio_id']}")

    assert response.status_code == 500
    assert response.json() == {"detail": "Closing Rescue encountered an unexpected error"}
    assert str(fault) not in response.text


def test_repository_unavailability_has_a_stable_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unavailable(_: str):
        raise sqlite3.OperationalError("database path must not leak")

    monkeypatch.setattr(api.service.repository, "get_portfolio", unavailable)
    response = client.get("/api/v2/closing-rescue/portfolio_unavailable")

    assert response.status_code == 503
    assert response.json() == {"detail": "Closing Rescue is temporarily unavailable"}
    assert "database path" not in response.text


def test_v1_health_and_case_validation_remain_compatible(client: TestClient) -> None:
    assert client.get("/api/v1/health").json() == {
        "status": "ok",
        "mode": "fixture",
    }
    assert client.post("/api/v1/cases", json={"address": "short"}).status_code == 422


def test_readiness_reports_database_failure_without_leaking_details(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unavailable() -> None:
        raise sqlite3.OperationalError("private database path")

    monkeypatch.setattr(api.service.repository, "ping", unavailable)
    response = client.get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "mode": "fixture",
        "database": "unavailable",
    }
    assert "private database path" not in response.text


def test_privileged_recovery_operations_are_not_exposed(client: TestClient) -> None:
    created = _create(client).json()
    base = f"/api/v2/closing-rescue/{created['portfolio_id']}"

    clear = client.post(
        f"{base}/clear-recovery", json={"actor_identity": "forged"}
    )
    assert clear.status_code == 404
    assert client.post(f"{base}/rotate-token", json={"actor_identity": "forged"}).status_code == 404


def test_openapi_does_not_describe_demo_identity_as_authentication(
    client: TestClient,
) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]

    request_description = schemas["ClosingRescueApprovalRequest"]["properties"][
        "approver_identity"
    ]["description"]
    response_description = schemas["ClosingApprovalProjection"]["properties"][
        "approver_identity"
    ]["description"]
    assert "not an authenticated identity" in request_description
    assert "not an authenticated identity" in response_description
