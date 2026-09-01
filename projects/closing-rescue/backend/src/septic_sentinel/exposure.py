"""Single-source integer arithmetic for transparent closing exposure."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from septic_sentinel.exposure_math import calculate_exposure_values
from septic_sentinel.models import ExposureEstimate


class _ExposureInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    delay_consequence_cents: StrictInt = Field(ge=0)
    delay_probability_bps: StrictInt = Field(ge=0, le=10_000)
    residual_probability_bps: StrictInt = Field(ge=0, le=10_000)
    intervention_cost_cents: StrictInt = Field(ge=0)
    intervention_available: StrictBool = True


def _validate_and_calculate(
    *,
    delay_consequence_cents: int,
    delay_probability_bps: int,
    residual_probability_bps: int,
    intervention_cost_cents: int,
    intervention_available: bool,
) -> tuple[_ExposureInputs, tuple[int, int, int]]:
    inputs = _ExposureInputs(
        delay_consequence_cents=delay_consequence_cents,
        delay_probability_bps=delay_probability_bps,
        residual_probability_bps=residual_probability_bps,
        intervention_cost_cents=intervention_cost_cents,
        intervention_available=intervention_available,
    )
    result = calculate_exposure_values(
        inputs.delay_consequence_cents,
        inputs.delay_probability_bps,
        inputs.residual_probability_bps,
        inputs.intervention_cost_cents,
        inputs.intervention_available,
    )
    return inputs, result


def calculate_exposure(
    delay_consequence_cents: int,
    delay_probability_bps: int,
    residual_probability_bps: int,
    intervention_cost_cents: int,
    intervention_available: bool = True,
) -> tuple[int, int, int]:
    """Validate inputs and return without, after, and preventable exposure cents."""
    _, result = _validate_and_calculate(
        delay_consequence_cents=delay_consequence_cents,
        delay_probability_bps=delay_probability_bps,
        residual_probability_bps=residual_probability_bps,
        intervention_cost_cents=intervention_cost_cents,
        intervention_available=intervention_available,
    )
    return result


class ExposureEngine:
    """Validate explicit inputs and produce an immutable exposure snapshot."""

    def estimate(
        self,
        *,
        delay_consequence_cents: int,
        delay_probability_bps: int,
        residual_probability_bps: int,
        intervention_cost_cents: int,
        intervention_available: bool = True,
    ) -> ExposureEstimate:
        inputs, result = _validate_and_calculate(
            delay_consequence_cents=delay_consequence_cents,
            delay_probability_bps=delay_probability_bps,
            residual_probability_bps=residual_probability_bps,
            intervention_cost_cents=intervention_cost_cents,
            intervention_available=intervention_available,
        )
        without, after, preventable = result
        return ExposureEstimate(
            delay_consequence_cents=inputs.delay_consequence_cents,
            delay_probability_bps=inputs.delay_probability_bps,
            residual_probability_bps=inputs.residual_probability_bps,
            intervention_cost_cents=inputs.intervention_cost_cents,
            intervention_available=inputs.intervention_available,
            without_action_cents=without,
            after_action_cents=after,
            preventable_cents=preventable,
        )
