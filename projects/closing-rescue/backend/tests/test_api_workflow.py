"""Integration coverage for the fixture-mode API workflow."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from septic_sentinel import api
from septic_sentinel.config import Settings
from septic_sentinel.runtime import build_service
from septic_sentinel.service import SepticSentinelService

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "cases"
ADDRESSES = {
    "clear": "18 Meadow Run, Dover, DE 19901",
    "investigate": "247 Cedar Lane, Harrington, DE 19952",
    "inspect": "91 Marsh Road, Milton, DE 19968",
}


@pytest.fixture
def api_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, SepticSentinelService]]:
    """Run the real API and repository against deterministic local fixtures."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    service = build_service(
        Settings(
            mode="fixture",
            db_path=tmp_path / "workflow.sqlite3",
            fixture_root=FIXTURE_ROOT,
        )
    )
    monkeypatch.setattr(api, "service", service)
    with TestClient(api.app) as client:
        yield client, service


def _case_payload(scenario: str, *, idempotency_key: str | None = None) -> dict[str, Any]:
    return {
        "external_case_id": f"LOAN-{scenario.upper()}-001",
        "address": ADDRESSES[scenario],
        "closing_date": (datetime.now(UTC).date() + timedelta(days=14)).isoformat(),
        "approved_vendors": ["First State Septic"],
        "approver_identity": "underwriter@example.test",
        "idempotency_key": idempotency_key or f"fixture-{scenario}-request-001",
        "fixture_scenario": scenario,
    }


def _ingest(client: TestClient, scenario: str) -> dict[str, Any]:
    response = client.post("/api/v1/cases", json=_case_payload(scenario))
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    ("scenario", "expected_state", "expected_action_kind"),
    [
        ("clear", "resolved", None),
        ("investigate", "waiting_for_approval", "county_record_request"),
        ("inspect", "waiting_for_approval", "inspection_order"),
    ],
)
def test_fixture_cases_reach_all_three_dispositions(
    api_client: tuple[TestClient, SepticSentinelService],
    scenario: str,
    expected_state: str,
    expected_action_kind: str | None,
) -> None:
    client, _ = api_client

    body = _ingest(client, scenario)

    assert body["created"] is True
    assert body["view"]["case"]["disposition"] == scenario
    assert body["view"]["case"]["state"] == expected_state
    assert body["view"]["decisions"][-1]["result"]["disposition"] == scenario
    assert len(body["view"]["evidence"]) == 5
    assert all(
        citation["source_name"] and citation["retrieved_at"]
        for item in body["view"]["evidence"]
        for citation in item["citations"]
    )

    if expected_action_kind is None:
        assert body["approval_token"] is None
        assert body["view"]["approvals"] == []
    else:
        assert body["approval_token"]
        assert body["view"]["approvals"][0]["action_kind"] == expected_action_kind
        assert body["view"]["approvals"][0]["state"] == "pending"

    case_id = body["view"]["case"]["id"]
    fetched = client.get(f"/api/v1/cases/{case_id}")
    assert fetched.status_code == 200
    assert fetched.json()["case"] == body["view"]["case"]

    evidence = client.get(f"/api/v1/cases/{case_id}/evidence")
    assert evidence.status_code == 200
    assert evidence.json() == fetched.json()["evidence"]

    memo = client.get(f"/api/v1/cases/{case_id}/memo")
    assert memo.status_code == 200
    assert memo.headers["content-type"].startswith("text/markdown")
    assert scenario in memo.text.lower()


def test_case_ingestion_is_idempotent(
    api_client: tuple[TestClient, SepticSentinelService],
) -> None:
    client, _ = api_client
    payload = _case_payload("investigate", idempotency_key="same-delivery-key")

    first = client.post("/api/v1/cases", json=payload)
    replay = client.post("/api/v1/cases", json=payload)

    assert first.status_code == 201
    assert replay.status_code == 200
    first_body = first.json()
    replay_body = replay.json()
    assert first_body["created"] is True
    assert replay_body["created"] is False
    assert replay_body["approval_token"] is None
    assert replay_body["view"]["case"]["id"] == first_body["view"]["case"]["id"]
    assert len(replay_body["view"]["evidence"]) == len(first_body["view"]["evidence"])
    assert len(replay_body["view"]["decisions"]) == 1
    assert len(replay_body["view"]["approvals"]) == 1

    listed = client.get("/api/v1/cases")
    assert listed.status_code == 200
    assert [case["id"] for case in listed.json()] == [first_body["view"]["case"]["id"]]


def test_approval_rejects_bad_token_then_succeeds_and_replays_idempotently(
    api_client: tuple[TestClient, SepticSentinelService],
) -> None:
    client, _ = api_client
    processed = _ingest(client, "investigate")
    approval = processed["view"]["approvals"][0]
    approval_url = f"/api/v1/approvals/{approval['id']}"
    request = {
        "approver_identity": "underwriter@example.test",
        "approval_token": processed["approval_token"],
        "approve": True,
    }

    denied = client.post(approval_url, json={**request, "approval_token": "invalid-token"})
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Approval token is invalid"

    succeeded = client.post(approval_url, json=request)
    replay = client.post(approval_url, json=request)

    assert succeeded.status_code == 200
    assert replay.status_code == 200
    action = succeeded.json()["action"]
    assert action["state"] == "succeeded"
    assert action["result"]["delivery"] == "simulated"
    assert succeeded.json()["view"]["case"]["state"] == "monitoring"
    assert succeeded.json()["view"]["approvals"][0]["state"] == "consumed"
    assert replay.json()["action"]["id"] == action["id"]
    assert len(replay.json()["view"]["actions"]) == 1


def test_explicit_approval_rejection_moves_case_to_monitoring(
    api_client: tuple[TestClient, SepticSentinelService],
) -> None:
    client, _ = api_client
    processed = _ingest(client, "inspect")
    approval = processed["view"]["approvals"][0]

    response = client.post(
        f"/api/v1/approvals/{approval['id']}",
        json={
            "approver_identity": "underwriter@example.test",
            "approval_token": processed["approval_token"],
            "approve": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] is None
    assert response.json()["view"]["case"]["state"] == "monitoring"
    assert response.json()["view"]["approvals"][0]["state"] == "rejected"
    assert response.json()["view"]["actions"] == []


def test_action_timeout_is_unknown_and_cannot_be_retried(
    api_client: tuple[TestClient, SepticSentinelService],
) -> None:
    client, _ = api_client
    processed = _ingest(client, "inspect")
    approval = processed["view"]["approvals"][0]
    request = {
        "approver_identity": "underwriter@example.test",
        "approval_token": processed["approval_token"],
        "approve": True,
        "simulate_timeout": True,
    }

    timed_out = client.post(f"/api/v1/approvals/{approval['id']}", json=request)
    replay = client.post(f"/api/v1/approvals/{approval['id']}", json=request)

    assert timed_out.status_code == 200
    action = timed_out.json()["action"]
    assert action["state"] == "unknown"
    assert action["result"] == {"delivery": "unknown", "requires_reconciliation": True}
    assert timed_out.json()["view"]["case"]["state"] == "monitoring"
    assert "action.unknown" in {event["event_type"] for event in timed_out.json()["view"]["events"]}
    assert replay.status_code == 200
    assert replay.json()["action"]["id"] == action["id"]
    assert replay.json()["action"]["state"] == "unknown"
    assert len(replay.json()["view"]["actions"]) == 1


def test_unknown_fixture_address_waits_for_clarification(
    api_client: tuple[TestClient, SepticSentinelService],
) -> None:
    client, _ = api_client
    payload = _case_payload("clear", idempotency_key="ambiguous-address-key")
    payload["external_case_id"] = "LOAN-AMBIGUOUS-001"
    payload["address"] = "999 Unmatched Road, Dover, DE 19901"

    response = client.post("/api/v1/cases", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["view"]["case"]["state"] == "waiting_for_clarification"
    assert body["view"]["case"]["disposition"] is None
    assert body["view"]["decisions"] == []
    assert body["view"]["approvals"] == []
    assert body["approval_token"] is None
    assert len(body["view"]["evidence"]) == 1
    assert body["view"]["evidence"][0]["status"] == "ambiguous"
    assert body["view"]["evidence"][0]["payload"]["reason"] == "fixture_address_not_found"

    memo = client.get(f"/api/v1/cases/{body['view']['case']['id']}/memo")
    assert memo.status_code == 409
    assert memo.json()["detail"] == "Case does not have a decision memo"


def test_api_rejects_invalid_input_and_returns_not_found_contract(
    api_client: tuple[TestClient, SepticSentinelService],
) -> None:
    client, _ = api_client

    health = client.get("/api/v1/health")
    invalid = client.post("/api/v1/cases", json={"address": "short"})
    missing_case = client.get("/api/v1/cases/case-does-not-exist")
    missing_approval = client.post(
        "/api/v1/approvals/apr-does-not-exist",
        json={
            "approver_identity": "underwriter@example.test",
            "approval_token": "unused-token",
            "approve": True,
        },
    )

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "mode": "fixture"}
    assert invalid.status_code == 422
    assert missing_case.status_code == 404
    assert missing_case.json() == {"detail": "Case not found"}
    assert missing_approval.status_code == 404
    assert missing_approval.json() == {"detail": "Approval not found"}
