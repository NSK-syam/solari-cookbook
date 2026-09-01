"""Approval-gated, restart-safe completion of the selected Closing Rescue."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from septic_sentinel.actions import (
    ApprovalConflictError,
    ApprovalTokenError,
    RescueActionPayload,
)
from septic_sentinel.config import Settings
from septic_sentinel.domain import ActionState, ApprovalState, CaseState
from septic_sentinel.runtime import build_closing_rescue_service

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "cases"
AS_OF = datetime(2026, 8, 5, 18, tzinfo=UTC)


def _service(tmp_path: Path, name: str):
    return build_closing_rescue_service(
        Settings(
            mode="fixture",
            db_path=tmp_path / name,
            fixture_root=FIXTURE_ROOT,
        )
    )


async def _proposed(tmp_path: Path, name: str = "rescue-approval.sqlite3"):
    service = _service(tmp_path, name)
    await service.repository.initialize()
    result = await service.create_competition_demo(f"demo-{name}", as_of=AS_OF)
    assert result.approval_token
    return service, result


def _draft(result) -> RescueActionPayload:
    return RescueActionPayload.model_validate_json(result.case.approvals[0].draft_json)


def _story_data(event) -> dict:
    return {item.key: json.loads(item.value_json) for item in event.data}


@pytest.mark.parametrize(
    "field",
    [
        "portfolio_id",
        "external_loan_id",
        "vendor_option_id",
        "vendor_name",
        "service_type",
        "property_address",
    ],
)
def test_rescue_payload_rejects_blank_semantic_fields(field: str) -> None:
    payload = {
        "portfolio_id": "portfolio-1",
        "external_loan_id": "CR-0047",
        "vendor_option_id": "vendor-1",
        "vendor_name": "First State Environmental",
        "appointment_at": datetime(2026, 8, 6, 12, tzinfo=UTC),
        "price_cents": 48_000,
        "service_type": "Synthetic septic inspection",
        "property_address": "91 Marsh Road, Milton, DE 19968",
    }
    with pytest.raises(ValidationError):
        RescueActionPayload.model_validate({**payload, field: "   "})


async def test_rescue_draft_is_the_exact_selected_synthetic_vendor_slot(
    tmp_path: Path,
) -> None:
    _, result = await _proposed(tmp_path)
    selected = result.vendor_selection.selected
    assert selected is not None

    draft = _draft(result)

    assert draft.portfolio_id == result.portfolio.id
    assert draft.external_loan_id == "CR-0047"
    assert draft.vendor_option_id == selected.id
    assert draft.vendor_name == "First State Environmental"
    assert draft.appointment_at == datetime(2026, 8, 6, 12, tzinfo=UTC)
    assert draft.price_cents == 48_000
    assert draft.truth_class.value == "synthetic"
    with pytest.raises(ValidationError):
        RescueActionPayload.model_validate({**draft.model_dump(), "price_cents": "48000"})


async def test_approval_books_once_recalculates_exposure_and_completes_story(
    tmp_path: Path,
) -> None:
    service, proposed = await _proposed(tmp_path, "success.sqlite3")
    approval = proposed.case.approvals[0]

    completed = await service.complete_rescue(
        proposed.portfolio.id,
        approval_id=approval.id,
        approver_identity=approval.approver_identity,
        token=proposed.approval_token,
        approve=True,
    )

    assert completed.case.case.state is CaseState.MONITORING
    assert completed.case.approvals[0].state is ApprovalState.CONSUMED
    assert len(completed.case.actions) == 1
    action = completed.case.actions[0]
    assert action.state is ActionState.SUCCEEDED
    assert json.loads(action.result_json)["delivery"] == "simulated"
    assert completed.exposure is not None
    assert completed.exposure.delay_probability_bps == 1_800
    assert completed.exposure.residual_probability_bps == 1_800
    assert completed.exposure.intervention_cost_cents == 48_000
    assert completed.exposure.without_action_cents == 432_000
    assert completed.exposure.after_action_cents == 480_000
    assert completed.exposure.preventable_cents == 0
    assert [event.event_type for event in completed.story_events].count(
        "rescue.completed"
    ) == 1
    completion = next(
        event for event in completed.story_events if event.event_type == "rescue.completed"
    )
    assert _story_data(completion)["action_id"] == action.id
    assert _story_data(completion)["booking"] == "simulated"
    assert (
        await service.repository.get_exposure_estimate(
            proposed.portfolio.id, "CR-0047", "after_rescue"
        )
        == completed.exposure
    )

    replay = await service.complete_rescue(
        proposed.portfolio.id,
        approval_id=approval.id,
        approver_identity=approval.approver_identity,
        token=proposed.approval_token,
        approve=True,
    )
    assert replay.case.actions[0].id == action.id
    assert len(replay.case.actions) == 1
    assert [event.event_type for event in replay.story_events].count(
        "rescue.completed"
    ) == 1
    replay_event_types = [event.event_type for event in replay.case.events]
    assert replay_event_types.count("action.completed") == 1
    assert replay_event_types.count("rescue.completed") == 1
    batches = await service.repository.list_priority_assessment_batches(
        proposed.portfolio.id
    )
    assert len(batches) == 2
    initial = await service.repository.list_priority_assessments(
        proposed.portfolio.id, batches[-1]
    )
    current = await service.repository.list_priority_assessments(
        proposed.portfolio.id, batches[0]
    )
    initial_hero = next(item for item in initial if item.external_loan_id == "CR-0047")
    current_hero = next(item for item in current if item.external_loan_id == "CR-0047")
    assert initial_hero.intervention_available is True
    assert initial_hero.preventable_exposure_cents == 1_320_000
    assert current_hero.intervention_available is False
    assert current_hero.preventable_exposure_cents == 0
    assert replay.assessments == tuple(current)


async def test_consumed_approval_cannot_be_replayed_as_rejection(tmp_path: Path) -> None:
    service, proposed = await _proposed(tmp_path, "approve-then-reject.sqlite3")
    approval = proposed.case.approvals[0]
    request = dict(
        portfolio_id=proposed.portfolio.id,
        approval_id=approval.id,
        approver_identity=approval.approver_identity,
        token=proposed.approval_token,
    )
    await service.complete_rescue(**request, approve=True)

    with pytest.raises(ApprovalConflictError, match="conflicts"):
        await service.complete_rescue(**request, approve=False)


async def test_approved_checkpoint_cannot_be_changed_to_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, proposed = await _proposed(tmp_path, "approved-then-reject.sqlite3")
    approval = proposed.case.approvals[0]
    _raise_after_once(monkeypatch, service.repository, "compare_and_swap_approval")
    request = dict(
        portfolio_id=proposed.portfolio.id,
        approval_id=approval.id,
        approver_identity=approval.approver_identity,
        token=proposed.approval_token,
    )
    with pytest.raises(RuntimeError, match="crash after"):
        await service.complete_rescue(**request, approve=True)
    monkeypatch.undo()

    assert (await service.repository.get_approval(approval.id)).state is ApprovalState.APPROVED
    with pytest.raises(ApprovalConflictError, match="conflicts"):
        await service.complete_rescue(**request, approve=False)
    assert (await service.repository.get_approval(approval.id)).state is ApprovalState.APPROVED
    completed = await service.complete_rescue(**request, approve=True)
    assert completed.case.approvals[0].state is ApprovalState.CONSUMED


async def test_rescue_approval_rejects_wrong_identity_and_bad_token(
    tmp_path: Path,
) -> None:
    service, proposed = await _proposed(tmp_path, "credentials.sqlite3")
    approval = proposed.case.approvals[0]
    kwargs = {
        "portfolio_id": proposed.portfolio.id,
        "approval_id": approval.id,
        "approver_identity": approval.approver_identity,
        "token": proposed.approval_token,
        "approve": True,
    }

    with pytest.raises(ApprovalTokenError, match="identity"):
        await service.complete_rescue(
            **{**kwargs, "approver_identity": "intruder@example.test"}
        )
    with pytest.raises(ApprovalTokenError, match="token"):
        await service.complete_rescue(**{**kwargs, "token": "wrong-token"})

    stored = await service.repository.get_approval(approval.id)
    assert stored.state is ApprovalState.PENDING
    assert await service.repository.get_action_by_approval(approval.id) is None


async def test_rejection_is_idempotent_and_never_creates_a_booking(
    tmp_path: Path,
) -> None:
    service, proposed = await _proposed(tmp_path, "rejection.sqlite3")
    approval = proposed.case.approvals[0]
    request = dict(
        portfolio_id=proposed.portfolio.id,
        approval_id=approval.id,
        approver_identity=approval.approver_identity,
        token=proposed.approval_token,
        approve=False,
    )

    rejected = await service.complete_rescue(**request)
    replay = await service.complete_rescue(**request)

    assert rejected.case.case.state is CaseState.MONITORING
    assert rejected.case.approvals[0].state is ApprovalState.REJECTED
    assert rejected.case.actions == ()
    assert replay.case.actions == ()
    assert all(event.event_type != "rescue.completed" for event in replay.story_events)
    with pytest.raises(ApprovalConflictError):
        await service.complete_rescue(**{**request, "approve": True})


async def test_unknown_booking_result_cannot_be_retried_or_marked_complete(
    tmp_path: Path,
) -> None:
    service, proposed = await _proposed(tmp_path, "unknown.sqlite3")
    approval = proposed.case.approvals[0]
    request = dict(
        portfolio_id=proposed.portfolio.id,
        approval_id=approval.id,
        approver_identity=approval.approver_identity,
        token=proposed.approval_token,
        approve=True,
        simulate_timeout=True,
    )

    unknown = await service.complete_rescue(**request)
    replay = await service.complete_rescue(**{**request, "simulate_timeout": False})

    assert len(unknown.case.actions) == 1
    assert unknown.case.actions[0].state is ActionState.UNKNOWN
    assert replay.case.actions[0].id == unknown.case.actions[0].id
    assert replay.case.actions[0].state is ActionState.UNKNOWN
    assert all(event.event_type != "rescue.completed" for event in replay.story_events)
    assert (
        await service.repository.get_exposure_estimate(
            proposed.portfolio.id, "CR-0047", "after_rescue"
        )
        is None
    )


def _raise_after_once(monkeypatch: pytest.MonkeyPatch, target, method_name: str) -> None:
    original: Callable = getattr(target, method_name)
    raised = False

    async def wrapped(*args, **kwargs):
        nonlocal raised
        result = await original(*args, **kwargs)
        if not raised:
            raised = True
            raise RuntimeError(f"crash after {method_name}")
        return result

    monkeypatch.setattr(target, method_name, wrapped)


@pytest.mark.parametrize(
    "checkpoint",
    [
        "approval_cas",
        "case_to_action",
        "action_insert",
        "action_update",
        "approval_consumption",
        "case_to_monitoring",
        "exposure_recalculation",
        "priority_recalculation",
        "completion_event",
    ],
)
async def test_approval_resumes_after_every_durable_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    checkpoint: str,
) -> None:
    service, proposed = await _proposed(tmp_path, f"crash-{checkpoint}.sqlite3")
    approval = proposed.case.approvals[0]

    if checkpoint == "approval_cas":
        _raise_after_once(monkeypatch, service.repository, "compare_and_swap_approval")
    elif checkpoint == "approval_consumption":
        original_cas = service.repository.compare_and_swap_approval
        calls = 0

        async def consume(*args, **kwargs):
            nonlocal calls
            result = await original_cas(*args, **kwargs)
            calls += 1
            if calls == 2:
                raise RuntimeError("crash after approval consumption")
            return result

        monkeypatch.setattr(
            service.repository, "compare_and_swap_approval", consume
        )
    elif checkpoint == "action_insert":
        _raise_after_once(monkeypatch, service.repository, "add_action")
    elif checkpoint == "action_update":
        _raise_after_once(monkeypatch, service.repository, "update_action")
    elif checkpoint == "exposure_recalculation":
        _raise_after_once(monkeypatch, service.repository, "add_exposure_estimate")
    elif checkpoint == "priority_recalculation":
        _raise_after_once(monkeypatch, service.repository, "add_priority_assessments")
    elif checkpoint == "completion_event":
        _raise_after_once(monkeypatch, service.repository, "add_event")
    else:
        original = service.repository.transition_case
        target = (
            CaseState.ACTION_IN_PROGRESS
            if checkpoint == "case_to_action"
            else CaseState.MONITORING
        )
        raised = False

        async def transition(*args, **kwargs):
            nonlocal raised
            result = await original(*args, **kwargs)
            if result.state is target and not raised:
                raised = True
                raise RuntimeError(f"crash after {target}")
            return result

        monkeypatch.setattr(service.repository, "transition_case", transition)

    request = dict(
        portfolio_id=proposed.portfolio.id,
        approval_id=approval.id,
        approver_identity=approval.approver_identity,
        token=proposed.approval_token,
        approve=True,
    )
    with pytest.raises(RuntimeError, match="crash after"):
        await service.complete_rescue(**request)

    restarted = _service(tmp_path, f"crash-{checkpoint}.sqlite3")
    await restarted.repository.initialize()
    completed = await restarted.complete_rescue(**request)

    assert completed.case.case.state is CaseState.MONITORING
    assert completed.case.approvals[0].state is ApprovalState.CONSUMED
    assert len(completed.case.actions) == 1
    assert completed.case.actions[0].state is ActionState.SUCCEEDED
    assert [event.event_type for event in completed.story_events].count(
        "rescue.completed"
    ) == 1
    assert len(
        await restarted.repository.list_priority_assessment_batches(
            proposed.portfolio.id
        )
    ) == 2


@pytest.mark.parametrize("checkpoint", ["approval_cas", "case_to_monitoring"])
async def test_rejection_resumes_after_each_durable_checkpoint_without_reopening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checkpoint: str
) -> None:
    database = f"reject-{checkpoint}.sqlite3"
    service, proposed = await _proposed(tmp_path, database)
    approval = proposed.case.approvals[0]
    if checkpoint == "approval_cas":
        _raise_after_once(monkeypatch, service.repository, "compare_and_swap_approval")
    else:
        original = service.repository.transition_case
        raised = False

        async def transition(*args, **kwargs):
            nonlocal raised
            result = await original(*args, **kwargs)
            if result.state is CaseState.MONITORING and not raised:
                raised = True
                raise RuntimeError("crash after rejection monitoring")
            return result

        monkeypatch.setattr(service.repository, "transition_case", transition)
    request = dict(
        portfolio_id=proposed.portfolio.id,
        approval_id=approval.id,
        approver_identity=approval.approver_identity,
        token=proposed.approval_token,
        approve=False,
    )

    with pytest.raises(RuntimeError, match="crash after"):
        await service.complete_rescue(**request)

    restarted = _service(tmp_path, database)
    await restarted.repository.initialize()
    rejected = await restarted.complete_rescue(**request)
    replay = await restarted.complete_rescue(**request)

    assert rejected.case.case.state is CaseState.MONITORING
    assert rejected.case.approvals[0].state is ApprovalState.REJECTED
    assert replay.case.approvals[0].state is ApprovalState.REJECTED
    assert replay.case.actions == ()
