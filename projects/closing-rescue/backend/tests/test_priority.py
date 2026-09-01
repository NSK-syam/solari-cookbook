"""Deterministic priority scoring contracts."""

from __future__ import annotations

from datetime import date

import openai
import pytest
from pydantic import ValidationError

import septic_sentinel.priority as priority_module
from septic_sentinel.models import (
    PortfolioLoan,
    PriorityAssessment,
    PrioritySignals,
    PrioritySourceInput,
)
from septic_sentinel.portfolio_fixtures import load_competition_portfolio
from septic_sentinel.priority import PriorityEngine

AS_OF = date(2026, 8, 5)


def loan(
    external_loan_id: str = "TEST-0001",
    *,
    closing_date: date = date(2026, 8, 11),
    fixture_scenario: str = "routine",
    staff_cost_cents: int = 10_000,
) -> PortfolioLoan:
    return PortfolioLoan(
        external_loan_id=external_loan_id,
        address="1 Test Lane, Milton, DE 19968",
        loan_amount_cents=20_000_000,
        closing_date=closing_date,
        rate_lock_daily_cost_cents=10_000,
        expected_extension_days=5,
        rescheduling_cost_cents=20_000,
        staff_cost_cents=staff_cost_cents,
        fixture_scenario=fixture_scenario,
    )


def signals(**overrides: object) -> PrioritySignals:
    values: dict[str, object] = {
        "delay_probability_bps": 4_000,
        "residual_probability_after_intervention_bps": 2_000,
        "intervention_cost_cents": 5_000,
        "intervention_available": True,
        "evidence_completeness_bps": 10_000,
        "contradiction_score": 10,
        "uncertainty_score": 5,
        "source_failed": False,
        "source_inputs": (
            {"name": "permit_status", "value": "complete"},
            {"name": "inspection_count", "value": 2},
        ),
    }
    values.update(overrides)
    return PrioritySignals.model_validate(values)


def assess(**signal_overrides: object) -> PriorityAssessment:
    item = loan()
    return PriorityEngine().rank(
        [item], as_of=AS_OF, signals={item.external_loan_id: signals(**signal_overrides)}
    )[0]


def test_competition_portfolio_selects_cr_0047() -> None:
    assessments = PriorityEngine().rank(
        load_competition_portfolio(), as_of=date(2026, 8, 5)
    )
    assert assessments[0].external_loan_id == "CR-0047"
    assert assessments[0].days_to_close == 6
    assert assessments[0].preventable_exposure_cents == 1_320_000


def test_missing_evidence_never_reduces_uncertainty() -> None:
    complete = assess(evidence_completeness_bps=10_000)
    missing = assess(evidence_completeness_bps=5_000)
    assert missing.uncertainty_score >= complete.uncertainty_score


def test_all_competition_loans_receive_assessments() -> None:
    assessments = PriorityEngine().rank(load_competition_portfolio(), as_of=AS_OF)

    assert len(assessments) == 47
    assert {item.external_loan_id for item in assessments} == {
        item.external_loan_id for item in load_competition_portfolio()
    }


def test_repeated_ranking_is_stable() -> None:
    loans = load_competition_portfolio()
    engine = PriorityEngine()

    first = [item.model_dump(mode="json") for item in engine.rank(loans, as_of=AS_OF)]
    second = [item.model_dump(mode="json") for item in engine.rank(loans, as_of=AS_OF)]

    assert first == second


def test_ties_are_broken_by_external_loan_id() -> None:
    tied = [loan("TEST-0002"), loan("TEST-0001")]
    explicit = {item.external_loan_id: signals() for item in tied}

    ranked = PriorityEngine().rank(tied, as_of=AS_OF, signals=explicit)

    assert [item.external_loan_id for item in ranked] == ["TEST-0001", "TEST-0002"]


def test_urgency_does_not_decrease_as_closing_approaches() -> None:
    far = loan("FAR", closing_date=date(2026, 8, 20))
    near = loan("NEAR", closing_date=date(2026, 8, 6))

    ranked = PriorityEngine().rank(
        [far, near],
        as_of=AS_OF,
        signals={"FAR": signals(), "NEAR": signals()},
    )
    by_id = {item.external_loan_id: item for item in ranked}

    assert by_id["NEAR"].urgency_score >= by_id["FAR"].urgency_score


def test_source_failure_cannot_improve_scoring_inputs_or_reduce_uncertainty() -> None:
    supplied = signals(
        delay_probability_bps=4_300,
        residual_probability_after_intervention_bps=1_200,
        evidence_completeness_bps=8_300,
        contradiction_score=77,
        uncertainty_score=13,
        source_failed=True,
        source_inputs=(
            {"name": "permit_status", "value": "timeout"},
            {"name": "attempt_count", "value": 3},
        ),
    )

    failed = PriorityEngine().rank(
        [loan()], as_of=AS_OF, signals={"TEST-0001": supplied}
    )[0]

    assert failed.input_signals == supplied
    assert failed.effective_signals == PrioritySignals(
        delay_probability_bps=4_300,
        residual_probability_after_intervention_bps=1_200,
        intervention_cost_cents=5_000,
        intervention_available=True,
        evidence_completeness_bps=0,
        contradiction_score=77,
        uncertainty_score=100,
        source_failed=True,
        source_inputs=(
            PrioritySourceInput(name="permit_status", value="timeout"),
            PrioritySourceInput(name="attempt_count", value=3),
        ),
    )
    assert (
        failed.effective_signals.residual_probability_after_intervention_bps
        == failed.input_signals.residual_probability_after_intervention_bps
    )
    assert (
        failed.effective_signals.evidence_completeness_bps
        <= failed.input_signals.evidence_completeness_bps
    )
    assert (
        failed.effective_signals.contradiction_score
        == failed.input_signals.contradiction_score
    )


def test_source_failure_is_monotone_in_ranking_space() -> None:
    item = loan("SAME")
    healthy = PriorityEngine().rank(
        [item], as_of=AS_OF, signals={"SAME": signals(source_failed=False)}
    )[0]
    failed = PriorityEngine().rank(
        [item], as_of=AS_OF, signals={"SAME": signals(source_failed=True)}
    )[0]

    healthy_key = (
        -healthy.preventable_exposure_cents,
        -healthy.urgency_score,
        -healthy.contradiction_score,
        healthy.external_loan_id,
    )
    failed_key = (
        -failed.preventable_exposure_cents,
        -failed.urgency_score,
        -failed.contradiction_score,
        failed.external_loan_id,
    )
    assert failed_key <= healthy_key
    assert failed.preventable_exposure_cents >= healthy.preventable_exposure_cents
    assert failed.urgency_score >= healthy.urgency_score
    assert failed.contradiction_score >= healthy.contradiction_score
    assert failed.evidence_completeness_bps == 0
    assert failed.uncertainty_score == 100
    assert (
        failed.effective_signals.uncertainty_score
        >= failed.input_signals.uncertainty_score
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("delay_probability_bps", -1),
        ("delay_probability_bps", 10_001),
        ("residual_probability_after_intervention_bps", 2.5),
        ("intervention_cost_cents", -1),
        ("intervention_available", 1),
        ("evidence_completeness_bps", "5000"),
        ("contradiction_score", 101),
        ("uncertainty_score", -1),
    ],
)
def test_invalid_probability_and_score_inputs_are_rejected(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        signals(**{field: value})


def test_invalid_dates_are_rejected() -> None:
    with pytest.raises(ValueError, match="closing_date cannot be before as_of"):
        PriorityEngine().rank(
            [loan(closing_date=date(2026, 8, 4))],
            as_of=AS_OF,
            signals={"TEST-0001": signals()},
        )

    with pytest.raises(TypeError, match="as_of must be a date"):
        PriorityEngine().rank([loan()], as_of="2026-08-05")  # type: ignore[arg-type]


def test_assessment_preserves_components_inputs_version_and_explanation() -> None:
    assessment = assess()

    assert assessment.delay_consequence_cents == 80_000
    assert assessment.delay_probability_bps == 4_000
    assert assessment.residual_probability_after_intervention_bps == 2_000
    assert assessment.intervention_cost_cents == 5_000
    assert assessment.intervention_available is True
    assert assessment.exposure_without_intervention_cents == 32_000
    assert assessment.exposure_after_intervention_cents == 21_000
    assert assessment.preventable_exposure_cents == (
        assessment.exposure_without_intervention_cents
        - assessment.exposure_after_intervention_cents
    )
    assert assessment.evidence_completeness_bps == 10_000
    assert assessment.contradiction_score == 10
    assert assessment.uncertainty_score == 5
    assert assessment.source_failed is False
    assert assessment.source_inputs == (
        PrioritySourceInput(name="permit_status", value="complete"),
        PrioritySourceInput(name="inspection_count", value=2),
    )
    assert assessment.formula_version == "priority-v1"
    assert "TEST-0001" in assessment.selection_explanation
    assert "preventable exposure" in assessment.selection_explanation.lower()


def test_fixture_profiles_record_intervention_availability() -> None:
    assessments = PriorityEngine().rank(load_competition_portfolio(), as_of=AS_OF)

    assert all(item.input_signals.intervention_available for item in assessments)
    assert all(item.effective_signals.intervention_available for item in assessments)
    assert all(
        item.scenario_profile_version == "closing-rescue-scenarios-v1"
        for item in assessments
    )
    assert assessments[0].formula_version == "priority-v1"


def test_unavailable_intervention_has_no_preventable_exposure_and_ranks_lower() -> None:
    available = loan("AVAILABLE")
    unavailable = loan("UNAVAILABLE")

    ranked = PriorityEngine().rank(
        [unavailable, available],
        as_of=AS_OF,
        signals={
            "AVAILABLE": signals(intervention_available=True),
            "UNAVAILABLE": signals(intervention_available=False),
        },
    )
    by_id = {item.external_loan_id: item for item in ranked}

    assert by_id["AVAILABLE"].preventable_exposure_cents > 0
    assert by_id["UNAVAILABLE"].preventable_exposure_cents == 0
    assert (
        by_id["UNAVAILABLE"].exposure_after_intervention_cents
        == by_id["UNAVAILABLE"].exposure_without_intervention_cents
    )
    assert ranked.index(by_id["AVAILABLE"]) < ranked.index(by_id["UNAVAILABLE"])


def test_intervention_availability_and_signal_audit_serialize() -> None:
    assessment = assess(intervention_available=False)

    payload = assessment.model_dump(mode="json")

    assert payload["intervention_available"] is False
    assert payload["input_signals"]["intervention_available"] is False
    assert payload["effective_signals"]["intervention_available"] is False
    assert PriorityAssessment.model_validate(payload) == assessment


def test_integer_exposure_arithmetic_floors_fractional_cents() -> None:
    item = PortfolioLoan(
        external_loan_id="FLOOR",
        address="1 Test Lane, Milton, DE 19968",
        loan_amount_cents=20_000_000,
        closing_date=date(2026, 8, 11),
        rate_lock_daily_cost_cents=0,
        expected_extension_days=0,
        rescheduling_cost_cents=0,
        staff_cost_cents=10_001,
        fixture_scenario="routine",
    )

    assessment = PriorityEngine().rank(
        [item],
        as_of=AS_OF,
        signals={
            "FLOOR": signals(
                delay_probability_bps=3_333,
                residual_probability_after_intervention_bps=0,
                intervention_cost_cents=0,
            )
        },
    )[0]

    assert assessment.exposure_without_intervention_cents == 3_333
    assert assessment.exposure_after_intervention_cents == 0
    assert assessment.preventable_exposure_cents == 3_333


def test_priority_uses_shared_exposure_calculator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int, int, int, bool]] = []

    def shared_calculator(
        consequence_cents: int,
        delay_probability_bps: int,
        residual_probability_bps: int,
        intervention_cost_cents: int,
        intervention_available: bool,
    ) -> tuple[int, int, int]:
        calls.append(
            (
                consequence_cents,
                delay_probability_bps,
                residual_probability_bps,
                intervention_cost_cents,
                intervention_available,
            )
        )
        return 11, 7, 4

    monkeypatch.setattr(priority_module, "calculate_exposure", shared_calculator)

    assessment = assess()

    assert calls == [(80_000, 4_000, 2_000, 5_000, True)]
    assert assessment.exposure_without_intervention_cents == 11
    assert assessment.exposure_after_intervention_cents == 7
    assert assessment.preventable_exposure_cents == 4


@pytest.mark.parametrize(
    ("dimension", "expected_first"),
    [
        ("exposure", "Z-HIGH-EXPOSURE"),
        ("urgency", "Z-MORE-URGENT"),
        ("contradiction", "Z-MORE-CONTRADICTORY"),
        ("external_id", "A-ID"),
    ],
)
def test_sort_key_precedence_isolated(dimension: str, expected_first: str) -> None:
    first = loan("A-ID")
    second = loan("Z-ID")
    first_signals = signals()
    second_signals = signals()
    if dimension == "exposure":
        first = loan(
            "A-LOW-EXPOSURE",
            closing_date=date(2026, 8, 6),
            staff_cost_cents=0,
        )
        second = loan(
            "Z-HIGH-EXPOSURE",
            closing_date=date(2026, 8, 12),
            staff_cost_cents=20_000,
        )
        first_signals = signals(contradiction_score=100)
        second_signals = signals(contradiction_score=0)
    elif dimension == "urgency":
        first = loan("A-LESS-URGENT", closing_date=date(2026, 8, 12))
        second = loan("Z-MORE-URGENT", closing_date=date(2026, 8, 11))
        first_signals = signals(contradiction_score=100)
        second_signals = signals(contradiction_score=0)
    elif dimension == "contradiction":
        first = loan("A-LESS-CONTRADICTORY")
        second = loan("Z-MORE-CONTRADICTORY")
        first_signals = signals(contradiction_score=10)
        second_signals = signals(contradiction_score=20)

    ranked = PriorityEngine().rank(
        [second, first],
        as_of=AS_OF,
        signals={
            first.external_loan_id: first_signals,
            second.external_loan_id: second_signals,
        },
    )

    assert ranked[0].external_loan_id == expected_first


def test_priority_snapshots_are_frozen_and_detached_from_caller_state() -> None:
    caller_inputs: list[dict[str, str | int | bool]] = [
        {"name": "permit_status", "value": "complete"}
    ]
    supplied = signals(source_inputs=caller_inputs)
    assessment = PriorityEngine().rank(
        [loan()], as_of=AS_OF, signals={"TEST-0001": supplied}
    )[0]
    before = assessment.model_dump_json()

    caller_inputs[0]["value"] = "changed"
    caller_inputs.append({"name": "attempt_count", "value": 9})

    assert assessment.model_dump_json() == before
    assert assessment.input_signals is not supplied
    with pytest.raises(ValidationError, match="Instance is frozen"):
        supplied.uncertainty_score = 99
    with pytest.raises(ValidationError, match="Instance is frozen"):
        assessment.preventable_exposure_cents = 0


def test_priority_contracts_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        signals(unexpected="value")

    valid = assess().model_dump()
    valid["unexpected"] = "value"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PriorityAssessment.model_validate(valid)


def test_ranking_does_not_call_a_model_or_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_call(*args: object, **kwargs: object) -> None:
        raise AssertionError("priority ranking must not instantiate an OpenAI client")

    monkeypatch.setattr(openai, "OpenAI", unexpected_call)

    assert PriorityEngine().rank(load_competition_portfolio(), as_of=AS_OF)
