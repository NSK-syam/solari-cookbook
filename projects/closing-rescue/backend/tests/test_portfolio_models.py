"""Tests for synthetic, property-only Closing Rescue portfolio contracts."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from septic_sentinel.models import (
    PortfolioCreateResult,
    PortfolioLoan,
    PortfolioSnapshot,
    SellerClaim,
    TruthClass,
)
from septic_sentinel.portfolio_fixtures import FIXTURE_PATH, load_competition_portfolio

ATTENTION_SCENARIOS = {
    "priority",
    "permit_gap",
    "site_constraint",
    "closing_deadline",
}
FORBIDDEN_KEYS = {"borrower_name", "borrower_income", "credit_score"}
BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_FIXTURE = BACKEND_ROOT.parent / "fixtures" / "portfolio" / "closing-rescue.json"
PACKAGE_FIXTURE = (
    BACKEND_ROOT / "src" / "septic_sentinel" / "data" / "closing-rescue.json"
)


def nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key
            for item in value.values()
            for key in nested_keys(item)
        }
    if isinstance(value, list):
        return {key for item in value for key in nested_keys(item)}
    return set()


def valid_loan_payload() -> dict[str, object]:
    return {
        "external_loan_id": "CR-0047",
        "address": "91 Marsh Road, Milton, DE 19968",
        "loan_amount_cents": 41_200_000,
        "closing_date": date(2026, 8, 11),
        "rate_lock_daily_cost_cents": 180_000,
        "expected_extension_days": 7,
        "rescheduling_cost_cents": 900_000,
        "staff_cost_cents": 240_000,
        "seller_claims": [
            {"field": "septic_replacement_year", "value": 2018},
        ],
        "approved_vendors": ["First State Environmental"],
        "fixture_scenario": "priority",
    }


def test_competition_fixture_has_expected_portfolio() -> None:
    loans = load_competition_portfolio()

    assert len(loans) == 47
    assert sum(item.loan_amount_cents for item in loans) == 1_420_000_000
    priority = next(item for item in loans if item.external_loan_id == "CR-0047")
    assert priority.loan_amount_cents == 41_200_000
    assert priority.address == "91 Marsh Road, Milton, DE 19968"
    assert priority.delay_consequence_cents == 2_400_000
    assert priority.fixture_scenario == "priority"
    assert priority.seller_claims == [
        SellerClaim(field="septic_replacement_year", value=2018)
    ]


def test_competition_fixture_is_unique_synthetic_and_marks_four_candidates() -> None:
    loans = load_competition_portfolio()

    assert len({item.external_loan_id for item in loans}) == len(loans)
    assert len({item.id for item in loans}) == len(loans)
    assert len({item.address for item in loans}) == len(loans)
    assert all(item.truth_class is TruthClass.SYNTHETIC for item in loans)
    attention_candidates = [
        item for item in loans if item.fixture_scenario in ATTENTION_SCENARIOS
    ]
    assert len(attention_candidates) == 4
    assert {item.fixture_scenario for item in attention_candidates} == ATTENTION_SCENARIOS


def test_competition_fixture_loads_deterministically() -> None:
    first_load = [item.model_dump(mode="json") for item in load_competition_portfolio()]
    second_load = [item.model_dump(mode="json") for item in load_competition_portfolio()]

    assert first_load == second_load


def test_repository_fixture_resolves_to_canonical_package_resource() -> None:
    assert REPOSITORY_FIXTURE.is_symlink()
    assert REPOSITORY_FIXTURE.resolve() == PACKAGE_FIXTURE.resolve()
    assert REPOSITORY_FIXTURE.read_bytes() == PACKAGE_FIXTURE.read_bytes()


def test_competition_fixture_raw_json_excludes_borrower_and_credit_keys() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert nested_keys(payload).isdisjoint(FORBIDDEN_KEYS)


def test_competition_fixture_loader_does_not_depend_on_current_directory(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert len(load_competition_portfolio()) == 47


def test_sdist_rebuilds_wheel_with_packaged_competition_fixture(tmp_path: Path) -> None:
    sdist_dir = tmp_path / "sdist"
    extracted_sdist_dir = tmp_path / "extracted-sdist"
    wheel_dir = tmp_path / "wheel"
    install_dir = tmp_path / "installed"
    isolated_cwd = tmp_path / "cwd"
    sdist_dir.mkdir()
    extracted_sdist_dir.mkdir()
    wheel_dir.mkdir()
    install_dir.mkdir()
    isolated_cwd.mkdir()
    subprocess.run(
        [
            "uv",
            "build",
            "--sdist",
            "--offline",
            "--out-dir",
            str(sdist_dir),
        ],
        cwd=BACKEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    sdist_path = next(sdist_dir.glob("*.tar.gz"))
    shutil.unpack_archive(sdist_path, extracted_sdist_dir, filter="data")
    extracted_project = next(extracted_sdist_dir.iterdir())
    subprocess.run(
        [
            "uv",
            "build",
            "--wheel",
            "--offline",
            "--out-dir",
            str(wheel_dir),
        ],
        cwd=extracted_project,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel_path = next(wheel_dir.glob("*.whl"))
    with zipfile.ZipFile(wheel_path) as wheel:
        packaged_resources = {name for name in wheel.namelist() if name.endswith(".json")}
        assert any(
            name.endswith("septic_sentinel/data/closing-rescue.json") for name in packaged_resources
        )
        assert any(
            name.endswith("septic_sentinel/data/delaware-inspectors.json")
            for name in packaged_resources
        )
        wheel.extractall(install_dir)

    checkout_source = BACKEND_ROOT / "src"
    code = f"""
import json
import pathlib
import sys

checkout_source = pathlib.Path({str(checkout_source)!r})
sys.path = [
    {str(install_dir)!r},
    *[
        path
        for path in sys.path
        if pathlib.Path(path or '.').resolve() != checkout_source
    ],
]
import septic_sentinel.portfolio_fixtures as portfolio_fixtures
import septic_sentinel.vendors as vendors

loans = portfolio_fixtures.load_competition_portfolio()
vendor_options = vendors.load_delaware_inspectors()
print(json.dumps({{
    "count": len(loans),
    "vendor_count": len(vendor_options),
    "module": portfolio_fixtures.__file__,
    "vendor_module": vendors.__file__,
}}))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=isolated_cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    result_payload = json.loads(result.stdout)

    assert result_payload["count"] == 47
    assert result_payload["vendor_count"] >= 3
    assert Path(result_payload["module"]).is_relative_to(install_dir)
    assert Path(result_payload["vendor_module"]).is_relative_to(install_dir)


def test_portfolio_loan_is_property_only_and_truth_labelled() -> None:
    loan = PortfolioLoan.model_validate(valid_loan_payload())

    assert loan.id.startswith("loan_")
    assert loan.truth_class is TruthClass.SYNTHETIC
    assert loan.delay_consequence_cents == 2_400_000
    assert loan.seller_claims == [
        SellerClaim(field="septic_replacement_year", value=2018)
    ]


@pytest.mark.parametrize("field", ["borrower_name", "borrower_income", "credit_score"])
def test_portfolio_loan_rejects_borrower_and_credit_fields(field: str) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        PortfolioLoan.model_validate({**valid_loan_payload(), field: "Do not store"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("loan_amount_cents", 0),
        ("rate_lock_daily_cost_cents", -1),
        ("expected_extension_days", -1),
        ("rescheduling_cost_cents", -1),
        ("staff_cost_cents", -1),
    ],
)
def test_portfolio_loan_validates_currency_and_duration_bounds(
    field: str, value: int
) -> None:
    with pytest.raises(ValidationError):
        PortfolioLoan.model_validate({**valid_loan_payload(), field: value})


@pytest.mark.parametrize(
    "field",
    [
        "loan_amount_cents",
        "rate_lock_daily_cost_cents",
        "expected_extension_days",
        "rescheduling_cost_cents",
        "staff_cost_cents",
    ],
)
@pytest.mark.parametrize("value", [True, "100", 100.0])
def test_portfolio_loan_requires_strict_integer_currency_and_duration_fields(
    field: str, value: bool | str | float
) -> None:
    with pytest.raises(ValidationError):
        PortfolioLoan.model_validate({**valid_loan_payload(), field: value})


def test_portfolio_loan_defaults_collection_fields_to_empty_lists() -> None:
    payload = valid_loan_payload()
    del payload["seller_claims"]
    del payload["approved_vendors"]

    loan = PortfolioLoan.model_validate(payload)

    assert loan.seller_claims == []
    assert loan.approved_vendors == []


def test_seller_claim_is_synthetic_and_forbids_extra_fields() -> None:
    claim = SellerClaim(field="septic_replacement_year", value=2018)

    assert claim.truth_class is TruthClass.SYNTHETIC
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SellerClaim.model_validate(
            {
                "field": "septic_replacement_year",
                "value": 2018,
                "seller_name": "Do not store",
            }
        )


@pytest.mark.parametrize("model_name", ["claim", "loan", "snapshot"])
def test_synthetic_models_reject_external_truth_class(model_name: str) -> None:
    claim_payload: dict[str, object] = {
        "field": "septic_replacement_year",
        "value": 2018,
        "truth_class": TruthClass.EXTERNAL_CITED,
    }
    loan_payload = {
        **valid_loan_payload(),
        "truth_class": TruthClass.EXTERNAL_CITED,
    }
    snapshot_payload = {
        "idempotency_key": "portfolio-2026-08-05",
        "loans": [valid_loan_payload()],
        "truth_class": TruthClass.EXTERNAL_CITED,
    }

    payloads = {
        "claim": (SellerClaim, claim_payload),
        "loan": (PortfolioLoan, loan_payload),
        "snapshot": (PortfolioSnapshot, snapshot_payload),
    }
    model, payload = payloads[model_name]

    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_portfolio_snapshot_and_create_result_are_validated_contracts() -> None:
    snapshot = PortfolioSnapshot(
        idempotency_key="portfolio-2026-08-05",
        loans=[PortfolioLoan.model_validate(valid_loan_payload())],
    )
    result = PortfolioCreateResult(portfolio=snapshot, created=True)

    assert snapshot.id.startswith("portfolio_")
    assert snapshot.truth_class is TruthClass.SYNTHETIC
    assert snapshot.created_at.tzinfo is not None
    assert result.portfolio is snapshot
    assert result.created is True


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            PortfolioSnapshot,
            {
                "idempotency_key": "portfolio-2026-08-05",
                "loans": [],
                "borrower_count": 1,
            },
        ),
        (
            PortfolioCreateResult,
            {
                "portfolio": {
                    "idempotency_key": "portfolio-2026-08-05",
                    "loans": [],
                },
                "created": True,
                "credit_summary": "Do not store",
            },
        ),
    ],
)
def test_portfolio_container_models_forbid_extra_fields(
    model: type[PortfolioSnapshot] | type[PortfolioCreateResult],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model.model_validate(payload)
