"""Deterministic, auditable closing-exposure priority scoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from septic_sentinel.exposure import calculate_exposure
from septic_sentinel.models import (
    PortfolioLoan,
    PriorityAssessment,
    PrioritySignals,
    PrioritySourceInput,
)

FORMULA_VERSION = "priority-v1"
SCENARIO_PROFILE_VERSION = "closing-rescue-scenarios-v1"


@dataclass(frozen=True)
class _ScenarioProfile:
    delay_probability_bps: int
    residual_probability_after_intervention_bps: int
    intervention_cost_cents: int
    intervention_available: bool
    evidence_completeness_bps: int
    contradiction_score: int
    uncertainty_score: int


_SCENARIO_PROFILES: dict[str, _ScenarioProfile] = {
    "routine": _ScenarioProfile(1_000, 800, 5_000, True, 9_500, 2, 5),
    "permit_gap": _ScenarioProfile(4_500, 2_800, 15_000, True, 7_000, 35, 30),
    "site_constraint": _ScenarioProfile(
        5_000, 3_000, 18_000, True, 6_500, 30, 35
    ),
    "closing_deadline": _ScenarioProfile(
        5_500, 3_000, 20_000, True, 8_000, 20, 20
    ),
    "priority": _ScenarioProfile(7_500, 1_800, 48_000, True, 5_000, 70, 50),
}


class PriorityEngine:
    """Rank loans from explicit signals or versioned fixture scenario profiles."""

    def rank(
        self,
        loans: Sequence[PortfolioLoan],
        *,
        as_of: date,
        signals: Mapping[str, PrioritySignals] | None = None,
    ) -> list[PriorityAssessment]:
        if type(as_of) is not date:
            raise TypeError("as_of must be a date")

        assessments: list[PriorityAssessment] = []
        for loan in loans:
            loan_signals, scenario_profile_version = self._signals_for(loan, signals)
            assessments.append(
                self._assess(
                    loan,
                    as_of=as_of,
                    signals=loan_signals,
                    scenario_profile_version=scenario_profile_version,
                )
            )
        return sorted(
            assessments,
            key=lambda assessment: (
                -assessment.preventable_exposure_cents,
                -assessment.urgency_score,
                -assessment.contradiction_score,
                assessment.external_loan_id,
            ),
        )

    def _signals_for(
        self,
        loan: PortfolioLoan,
        signals: Mapping[str, PrioritySignals] | None,
    ) -> tuple[PrioritySignals, str | None]:
        if signals is not None:
            try:
                return signals[loan.external_loan_id], None
            except KeyError as exc:
                raise ValueError(
                    f"missing priority signals for {loan.external_loan_id}"
                ) from exc

        try:
            profile = _SCENARIO_PROFILES[loan.fixture_scenario]
        except KeyError as exc:
            raise ValueError(
                f"no priority profile for fixture scenario {loan.fixture_scenario!r}"
            ) from exc
        return (
            PrioritySignals(
                delay_probability_bps=profile.delay_probability_bps,
                residual_probability_after_intervention_bps=(
                    profile.residual_probability_after_intervention_bps
                ),
                intervention_cost_cents=profile.intervention_cost_cents,
                intervention_available=profile.intervention_available,
                evidence_completeness_bps=profile.evidence_completeness_bps,
                contradiction_score=profile.contradiction_score,
                uncertainty_score=profile.uncertainty_score,
                source_failed=False,
                source_inputs=(
                    PrioritySourceInput(
                        name="fixture_scenario", value=loan.fixture_scenario
                    ),
                    PrioritySourceInput(
                        name="scenario_profile_version",
                        value=SCENARIO_PROFILE_VERSION,
                    ),
                ),
            ),
            SCENARIO_PROFILE_VERSION,
        )

    @staticmethod
    def _assess(
        loan: PortfolioLoan,
        *,
        as_of: date,
        signals: PrioritySignals,
        scenario_profile_version: str | None,
    ) -> PriorityAssessment:
        days_to_close = (loan.closing_date - as_of).days
        if days_to_close < 0:
            raise ValueError("closing_date cannot be before as_of")

        input_signals = PrioritySignals.model_validate(
            signals.model_dump(mode="python")
        )
        effective_signals = PriorityEngine._effective_signals(input_signals)

        without, after, preventable = calculate_exposure(
            loan.delay_consequence_cents,
            effective_signals.delay_probability_bps,
            effective_signals.residual_probability_after_intervention_bps,
            effective_signals.intervention_cost_cents,
            effective_signals.intervention_available,
        )
        urgency_score = max(0, 100 - days_to_close)
        preventable_dollars = preventable // 100
        preventable_cents = preventable % 100
        explanation = (
            f"{loan.external_loan_id} has "
            f"${preventable_dollars:,}.{preventable_cents:02d} in preventable "
            f"exposure, closes in {days_to_close} days, and has urgency score "
            f"{urgency_score}."
        )
        return PriorityAssessment(
            external_loan_id=loan.external_loan_id,
            days_to_close=days_to_close,
            urgency_score=urgency_score,
            delay_consequence_cents=loan.delay_consequence_cents,
            delay_probability_bps=effective_signals.delay_probability_bps,
            residual_probability_after_intervention_bps=(
                effective_signals.residual_probability_after_intervention_bps
            ),
            intervention_cost_cents=effective_signals.intervention_cost_cents,
            intervention_available=effective_signals.intervention_available,
            exposure_without_intervention_cents=without,
            exposure_after_intervention_cents=after,
            preventable_exposure_cents=preventable,
            evidence_completeness_bps=effective_signals.evidence_completeness_bps,
            contradiction_score=effective_signals.contradiction_score,
            uncertainty_score=effective_signals.uncertainty_score,
            source_failed=effective_signals.source_failed,
            source_inputs=effective_signals.source_inputs,
            input_signals=input_signals,
            effective_signals=effective_signals,
            formula_version=FORMULA_VERSION,
            scenario_profile_version=scenario_profile_version,
            selection_explanation=explanation,
        )

    @staticmethod
    def _effective_signals(signals: PrioritySignals) -> PrioritySignals:
        uncertainty_score = max(
            signals.uncertainty_score,
            (10_000 - signals.evidence_completeness_bps) // 100,
        )
        updates: dict[str, int] = {"uncertainty_score": uncertainty_score}
        if signals.source_failed:
            updates.update(
                evidence_completeness_bps=0,
                uncertainty_score=100,
            )
        return signals.model_copy(update=updates, deep=True)
