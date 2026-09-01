"""Dependency-free integer arithmetic shared by exposure contracts and engines."""

from __future__ import annotations


def calculate_exposure_values(
    delay_consequence_cents: int,
    delay_probability_bps: int,
    residual_probability_bps: int,
    intervention_cost_cents: int,
    intervention_available: bool,
) -> tuple[int, int, int]:
    """Calculate exact integer outputs for already-validated inputs."""
    without = delay_consequence_cents * delay_probability_bps // 10_000
    if not intervention_available:
        return without, without, 0
    after = (
        delay_consequence_cents * residual_probability_bps // 10_000
        + intervention_cost_cents
    )
    return without, after, max(0, without - after)
