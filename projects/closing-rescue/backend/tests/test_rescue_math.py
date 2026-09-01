"""Transparent exposure arithmetic and synthetic vendor scouting contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from septic_sentinel.exposure import ExposureEngine, calculate_exposure
from septic_sentinel.models import (
    ExposureEstimate,
    TruthClass,
    VendorOption,
    VendorSelection,
)
from septic_sentinel.vendors import FIXTURE_PATH, VendorScout, load_delaware_inspectors

AS_OF = datetime(2026, 8, 5, 18, tzinfo=UTC)
CUTOFF = datetime(2026, 8, 11, 16, tzinfo=UTC)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_FIXTURE = BACKEND_ROOT / "src" / "septic_sentinel" / "data" / "delaware-inspectors.json"
REPOSITORY_FIXTURE = BACKEND_ROOT.parent / "fixtures" / "vendors" / "delaware-inspectors.json"


def option(**overrides: object) -> VendorOption:
    values: dict[str, object] = {
        "id": "vendor_option_test",
        "vendor_name": "Synthetic Test Inspector",
        "appointment_at": datetime(2026, 8, 6, 12, tzinfo=UTC),
        "price_cents": 48_000,
        "service_type": "Synthetic septic inspection",
        "approved": True,
        "qualified": True,
        "available_as_of": AS_OF,
        "truth_class": "synthetic",
    }
    values.update(overrides)
    return VendorOption.model_validate(values)


def test_hero_exposure_matches_documented_formula() -> None:
    estimate = ExposureEngine().estimate(
        delay_consequence_cents=2_400_000,
        delay_probability_bps=7_500,
        residual_probability_bps=1_800,
        intervention_cost_cents=48_000,
    )
    assert estimate.without_action_cents == 1_800_000
    assert estimate.after_action_cents == 480_000
    assert estimate.preventable_cents == 1_320_000


def test_exposure_preserves_exact_transparent_components() -> None:
    estimate = ExposureEngine().estimate(
        delay_consequence_cents=10_001,
        delay_probability_bps=3_333,
        residual_probability_bps=1,
        intervention_cost_cents=2,
    )

    assert estimate.delay_consequence_cents == 10_001
    assert estimate.delay_probability_bps == 3_333
    assert estimate.residual_probability_bps == 1
    assert estimate.intervention_cost_cents == 2
    assert estimate.without_action_cents == 3_333
    assert estimate.after_action_cents == 3
    assert estimate.preventable_cents == 3_330
    assert estimate.formula_version == "closing-exposure-2026-08-05"
    assert estimate.limitations
    assert estimate.created_at.tzinfo is UTC
    assert estimate.id.startswith("exposure_")


def test_exposure_never_reports_negative_preventable_amount() -> None:
    assert calculate_exposure(10_000, 1_000, 900, 20_000) == (1_000, 20_900, 0)
    assert calculate_exposure(10_000, 1_000, 900, 20_000, False) == (1_000, 1_000, 0)


@pytest.mark.parametrize(
    ("arguments", "_invalid_value"),
    [
        ((True, 1_000, 900, 100, True), True),
        (("10000", 1_000, 900, 100, True), "10000"),
        ((10_000.0, 1_000, 900, 100, True), 10_000.0),
        ((-1, 1_000, 900, 100, True), -1),
        ((10_000, True, 900, 100, True), True),
        ((10_000, "1000", 900, 100, True), "1000"),
        ((10_000, 1_000.0, 900, 100, True), 1_000.0),
        ((10_000, -1, 900, 100, True), -1),
        ((10_000, 10_001, 900, 100, True), 10_001),
        ((10_000, 1_000, True, 100, True), True),
        ((10_000, 1_000, "900", 100, True), "900"),
        ((10_000, 1_000, 900.0, 100, True), 900.0),
        ((10_000, 1_000, -1, 100, True), -1),
        ((10_000, 1_000, 10_001, 100, True), 10_001),
        ((10_000, 1_000, 900, True, True), True),
        ((10_000, 1_000, 900, "100", True), "100"),
        ((10_000, 1_000, 900, 100.0, True), 100.0),
        ((10_000, 1_000, 900, -1, True), -1),
        ((10_000, 1_000, 900, 100, 1), 1),
        ((10_000, 1_000, 900, 100, "true"), "true"),
        ((10_000, 1_000, 900, 100, 1.0), 1.0),
    ],
)
def test_public_exposure_calculator_rejects_invalid_direct_inputs(
    arguments: tuple[object, object, object, object, object],
    _invalid_value: object,
) -> None:
    with pytest.raises(ValidationError):
        calculate_exposure(*arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("delay_consequence_cents", -1),
        ("intervention_cost_cents", -1),
        ("delay_probability_bps", -1),
        ("delay_probability_bps", 10_001),
        ("residual_probability_bps", 10_001),
        ("delay_consequence_cents", True),
        ("delay_probability_bps", "7500"),
        ("intervention_cost_cents", 48_000.0),
    ],
)
def test_exposure_rejects_invalid_strict_inputs(field: str, value: object) -> None:
    inputs: dict[str, object] = {
        "delay_consequence_cents": 2_400_000,
        "delay_probability_bps": 7_500,
        "residual_probability_bps": 1_800,
        "intervention_cost_cents": 48_000,
    }
    inputs[field] = value
    with pytest.raises(ValidationError):
        ExposureEngine().estimate(**inputs)  # type: ignore[arg-type]


def test_exposure_snapshot_is_frozen_timezone_aware_and_roundtrips() -> None:
    estimate = ExposureEngine().estimate(
        delay_consequence_cents=100,
        delay_probability_bps=5_000,
        residual_probability_bps=1_000,
        intervention_cost_cents=5,
    )
    assert ExposureEstimate.model_validate_json(estimate.model_dump_json()) == estimate
    with pytest.raises(ValidationError, match="Instance is frozen"):
        estimate.preventable_cents = 0
    with pytest.raises(ValidationError):
        ExposureEstimate.model_validate(
            {**estimate.model_dump(), "created_at": datetime(2026, 8, 5)}
        )
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ExposureEstimate.model_validate({**estimate.model_dump(), "extra": True})


def test_hero_vendor_selection_is_exact_and_auditable() -> None:
    options = load_delaware_inspectors()
    selection = VendorScout().select(
        options,
        approved_names={"First State Environmental"},
        cutoff=CUTOFF,
        as_of=AS_OF,
    )

    assert selection.selected is not None
    assert selection.selected.vendor_name == "First State Environmental"
    assert selection.selected.appointment_at == datetime(2026, 8, 6, 12, tzinfo=UTC)
    assert selection.selected.price_cents == 48_000
    assert len(selection.considered) == len(options)
    assert selection.truth_class is TruthClass.SYNTHETIC
    rejected_codes = {code for item in selection.considered for code in item.rejection_reason_codes}
    assert {
        "not_approved",
        "not_qualified",
        "appointment_after_cutoff",
    } <= rejected_codes
    assert selection.approved_names == ("First State Environmental",)
    assert selection.evaluated_at == AS_OF


def test_scout_requires_every_viability_condition_and_reports_no_availability() -> None:
    options = [
        option(id="not-name", vendor_name="Other Synthetic Inspector"),
        option(id="not-approved", approved=False),
        option(id="not-qualified", qualified=False),
        option(id="at-cutoff", appointment_at=CUTOFF),
        option(id="future-observation", available_as_of=AS_OF.replace(day=6)),
    ]
    selection = VendorScout().select(
        options,
        approved_names={"Synthetic Test Inspector"},
        cutoff=CUTOFF,
        as_of=AS_OF,
    )

    assert selection.selected is None
    by_id = {item.option.id: item.rejection_reason_codes for item in selection.considered}
    assert by_id["not-name"] == ("name_not_approved",)
    assert by_id["not-approved"] == ("not_approved",)
    assert by_id["not-qualified"] == ("not_qualified",)
    assert by_id["at-cutoff"] == ("appointment_after_cutoff",)
    assert by_id["future-observation"] == ("availability_observation_after_as_of",)


@pytest.mark.parametrize(
    ("appointment_at", "expected_reason"),
    [
        (datetime(2026, 8, 5, 17, 59, tzinfo=UTC), "appointment_expired"),
        (AS_OF, "appointment_expired"),
        (datetime(2026, 8, 6, 12, tzinfo=UTC), None),
        (CUTOFF, "appointment_after_cutoff"),
        (datetime(2026, 8, 11, 17, tzinfo=UTC), "appointment_after_cutoff"),
    ],
)
def test_scout_enforces_open_appointment_interval(
    appointment_at: datetime,
    expected_reason: str | None,
) -> None:
    selection = VendorScout().select(
        [option(appointment_at=appointment_at)],
        approved_names={"Synthetic Test Inspector"},
        cutoff=CUTOFF,
        as_of=AS_OF,
    )

    reasons = selection.considered[0].rejection_reason_codes
    assert reasons == (() if expected_reason is None else (expected_reason,))
    assert (selection.selected is not None) is (expected_reason is None)


def test_appointment_expiry_precedes_cutoff_when_boundaries_overlap() -> None:
    boundary = datetime(2026, 8, 6, 12, tzinfo=UTC)
    selection = VendorScout().select(
        [option(appointment_at=boundary)],
        approved_names={"Synthetic Test Inspector"},
        cutoff=boundary,
        as_of=boundary,
    )

    assert selection.considered[0].rejection_reason_codes == ("appointment_expired",)


def test_scout_selection_order_is_stable_across_input_order_and_ties() -> None:
    later = option(id="later", appointment_at=datetime(2026, 8, 7, tzinfo=UTC))
    expensive = option(id="expensive", price_cents=49_000)
    alphabetic = option(id="alphabetic", vendor_name="A Synthetic Inspector")
    tied_later_id = option(id="z-id", vendor_name="A Synthetic Inspector")
    options = [later, tied_later_id, expensive, alphabetic]
    approved = {item.vendor_name for item in options}

    first = VendorScout().select(options, approved_names=approved, cutoff=CUTOFF, as_of=AS_OF)
    second = VendorScout().select(
        reversed(options), approved_names=approved, cutoff=CUTOFF, as_of=AS_OF
    )

    assert first.selected is not None
    assert first.selected.id == "alphabetic"
    assert second.selected == first.selected
    assert [item.option.id for item in first.considered] == [
        item.option.id for item in second.considered
    ]


@pytest.mark.parametrize("field", ["id", "vendor_name", "service_type"])
def test_vendor_rejects_semantic_blanks(field: str) -> None:
    with pytest.raises(ValidationError):
        option(**{field: "  "})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("price_cents", -1),
        ("price_cents", True),
        ("price_cents", "48000"),
        ("price_cents", 48_000.0),
        ("approved", 1),
        ("qualified", "true"),
        ("appointment_at", datetime(2026, 8, 6, 12)),
        ("available_as_of", datetime(2026, 8, 5, 18)),
        ("truth_class", "external_cited"),
    ],
)
def test_vendor_option_is_strict_synthetic_and_timezone_aware(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        option(**{field: value})


def test_vendor_snapshots_are_frozen_normalized_and_roundtrip() -> None:
    eastern = datetime.fromisoformat("2026-08-06T08:00:00-04:00")
    selection = VendorScout().select(
        [option(appointment_at=eastern)],
        approved_names={"Synthetic Test Inspector"},
        cutoff=CUTOFF,
        as_of=AS_OF,
    )

    assert selection.selected is not None
    assert selection.selected.appointment_at.tzinfo is UTC
    assert VendorSelection.model_validate_json(selection.model_dump_json()) == selection
    with pytest.raises(ValidationError, match="Instance is frozen"):
        selection.selected = None
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        VendorSelection.model_validate({**selection.model_dump(), "extra": True})


@pytest.mark.parametrize(
    ("field", "forged_value"),
    [
        ("without_action_cents", 1_799_999),
        ("after_action_cents", 479_999),
        ("preventable_cents", 1_319_999),
    ],
)
def test_exposure_rejects_forged_python_and_json_derived_outputs(
    field: str,
    forged_value: int,
) -> None:
    estimate = ExposureEngine().estimate(
        delay_consequence_cents=2_400_000,
        delay_probability_bps=7_500,
        residual_probability_bps=1_800,
        intervention_cost_cents=48_000,
    )
    forged = {**estimate.model_dump(), field: forged_value}

    with pytest.raises(ValidationError, match="derived exposure outputs"):
        ExposureEstimate.model_validate(forged)
    with pytest.raises(ValidationError, match="derived exposure outputs"):
        ExposureEstimate.model_validate_json(json.dumps(forged, default=str))


def test_exposure_integrity_includes_intervention_availability() -> None:
    estimate = ExposureEngine().estimate(
        delay_consequence_cents=10_000,
        delay_probability_bps=5_000,
        residual_probability_bps=1_000,
        intervention_cost_cents=500,
        intervention_available=False,
    )

    assert estimate.intervention_available is False
    assert estimate.without_action_cents == 5_000
    assert estimate.after_action_cents == 5_000
    assert estimate.preventable_cents == 0
    assert ExposureEstimate.model_validate_json(estimate.model_dump_json()) == estimate


def test_vendor_selection_rejects_forged_audit_snapshots() -> None:
    viable = option(id="viable")
    rejected = option(id="rejected", qualified=False)
    selection = VendorScout().select(
        [rejected, viable],
        approved_names={"Synthetic Test Inspector"},
        cutoff=CUTOFF,
        as_of=AS_OF,
    )
    valid = selection.model_dump(mode="python")

    adversarial_payloads = [
        {**valid, "selected": option(id="absent").model_dump(mode="python")},
        {
            **valid,
            "selected": option(id="viable", price_cents=47_999).model_dump(mode="python"),
        },
        {**valid, "selected": rejected.model_dump(mode="python")},
        {**valid, "approved_names": ("Other Synthetic Inspector",)},
        {
            **valid,
            "considered": (
                {
                    **valid["considered"][0],
                    "rejection_reason_codes": (),
                },
                valid["considered"][1],
            ),
        },
        {**valid, "selected": None},
        {
            **valid,
            "selected": viable.model_dump(mode="python"),
            "considered": (
                {
                    "option": rejected.model_dump(mode="python"),
                    "rejection_reason_codes": ("not_qualified",),
                },
            ),
        },
        {
            **valid,
            "considered": (*valid["considered"], valid["considered"][0]),
        },
    ]

    for payload in adversarial_payloads:
        with pytest.raises(ValidationError):
            VendorSelection.model_validate(payload)
        with pytest.raises(ValidationError):
            VendorSelection.model_validate_json(json.dumps(payload, default=str))


def test_vendor_selection_requires_first_canonical_viable_option() -> None:
    first = option(
        id="first",
        appointment_at=datetime(2026, 8, 6, 11, tzinfo=UTC),
        price_cents=49_000,
    )
    later = option(id="later", appointment_at=datetime(2026, 8, 6, 12, tzinfo=UTC))
    selection = VendorScout().select(
        [later, first],
        approved_names={"Synthetic Test Inspector"},
        cutoff=CUTOFF,
        as_of=AS_OF,
    )
    forged = {**selection.model_dump(mode="python"), "selected": later.model_dump()}

    assert selection.selected == first
    with pytest.raises(ValidationError):
        VendorSelection.model_validate(forged)


def test_vendor_selection_persists_normalized_approved_name_provenance() -> None:
    selection = VendorScout().select(
        [option()],
        approved_names=[" Synthetic Test Inspector ", "Synthetic Test Inspector"],
        cutoff=CUTOFF,
        as_of=AS_OF,
    )

    assert selection.approved_names == ("Synthetic Test Inspector",)
    assert selection.evaluated_at == AS_OF


def test_vendor_fixture_is_cwd_independent_synthetic_and_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    options = load_delaware_inspectors()

    assert len(options) >= 3
    assert all(item.truth_class is TruthClass.SYNTHETIC for item in options)
    assert all("synthetic" in item.service_type.lower() for item in options)
    assert FIXTURE_PATH == PACKAGE_FIXTURE
    assert REPOSITORY_FIXTURE.is_symlink()
    assert REPOSITORY_FIXTURE.resolve() == PACKAGE_FIXTURE.resolve()
    assert REPOSITORY_FIXTURE.read_bytes() == PACKAGE_FIXTURE.read_bytes()
