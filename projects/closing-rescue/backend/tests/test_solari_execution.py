"""Fake-adapter coverage for the persisted Solari proof rail."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from septic_sentinel.config import Settings
from septic_sentinel.runtime import build_closing_rescue_service
from septic_sentinel.solari_execution import (
    AdapterResult,
    SolariExecutionService,
    _desktop_form_text,
    _redact_permit_html,
    _validate_desktop_screenshot,
    _validate_desktop_text,
)
from septic_sentinel.solari_models import SolariArtifact, SolariStepReceipt

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "cases"
AS_OF = datetime(2026, 8, 5, 18, tzinfo=UTC)


class FakeAdapter:
    def __init__(self, product: str, *, failure: Exception | None = None) -> None:
        self.product = product
        self.failure = failure
        self.calls = 0
        self.cleanup_calls = 0
        self.payload = None

    async def run(self, payload):
        self.payload = payload
        return await self._execute()

    async def capture(self):
        return await self._execute()

    async def fill_simulated_form(self, form):
        self.payload = form
        return await self._execute()

    async def _execute(self):
        self.calls += 1
        try:
            if self.failure:
                raise self.failure
            return AdapterResult(
                session_id=f"{self.product}-session",
                detail=f"{self.product} completed safely",
                artifacts=(
                    SolariArtifact(
                        kind="receipt",
                        label=f"{self.product} receipt",
                        url="https://example.test/public-artifact",
                    ),
                ),
                manifest_sha256="a" * 64 if self.product == "sandbox" else None,
            )
        finally:
            self.cleanup_calls += 1


class SlowAdapter(FakeAdapter):
    async def _execute(self):
        self.calls += 1
        try:
            await asyncio.sleep(0.1)
            raise AssertionError("timeout should cancel this operation")
        finally:
            self.cleanup_calls += 1


async def _rescue(tmp_path: Path):
    rescue = build_closing_rescue_service(
        Settings(
            mode="fixture",
            db_path=tmp_path / "solari.sqlite3",
            fixture_root=FIXTURE_ROOT,
        )
    )
    await rescue.repository.initialize()
    result = await rescue.create_competition_demo("solari-proof-demo", as_of=AS_OF)
    return rescue, result


async def test_fake_products_process_all_47_loans_and_persist_receipts(
    tmp_path: Path,
) -> None:
    rescue, result = await _rescue(tmp_path)
    sandbox = FakeAdapter("sandbox")
    browser = FakeAdapter("browser")
    desktop = FakeAdapter("desktop")
    proof = SolariExecutionService(rescue.repository, sandbox, browser, desktop)

    execution = await proof.run_preapproval(result, result.assessments)

    assert execution.status == "awaiting_approval"
    assert execution.manifest_sha256 == "a" * 64
    assert len(sandbox.payload["loans"]) == 47
    assert {item["loan_id"] for item in sandbox.payload["loans"]} == {
        loan.external_loan_id for loan in result.portfolio.loans
    }
    assert execution.step("desktop").status == "blocked"
    assert [sandbox.cleanup_calls, browser.cleanup_calls, desktop.cleanup_calls] == [1, 1, 0]
    assert await rescue.repository.get_solari_execution(result.portfolio.id) == execution


async def test_desktop_is_blocked_until_real_approval_then_runs_exactly_once(
    tmp_path: Path,
) -> None:
    rescue, result = await _rescue(tmp_path)
    sandbox = FakeAdapter("sandbox")
    browser = FakeAdapter("browser")
    desktop = FakeAdapter("desktop")
    proof = SolariExecutionService(rescue.repository, sandbox, browser, desktop)
    await proof.run_preapproval(result, result.assessments)

    with pytest.raises(RuntimeError, match="human approval"):
        await proof.run_desktop_after_approval(result)
    assert desktop.calls == 0

    approval = result.case.approvals[-1]
    approved = await rescue.complete_rescue(
        result.portfolio.id,
        approval_id=approval.id,
        approver_identity=approval.approver_identity,
        token=result.approval_token or "",
        approve=True,
    )
    execution = await proof.run_desktop_after_approval(approved)
    replay = await proof.run_desktop_after_approval(approved)

    assert execution is not None and execution.status == "succeeded"
    assert replay == execution
    assert desktop.calls == desktop.cleanup_calls == 1
    assert desktop.payload["mode"] == "SIMULATION ONLY - DO NOT SUBMIT"


async def test_timeout_and_partial_failure_keep_other_product_receipt(
    tmp_path: Path,
) -> None:
    rescue, result = await _rescue(tmp_path)
    sandbox = SlowAdapter("sandbox")
    browser = FakeAdapter("browser")
    proof = SolariExecutionService(
        rescue.repository, sandbox, browser, FakeAdapter("desktop"), timeout_seconds=0.01
    )

    execution = await proof.run_preapproval(result, result.assessments)

    assert execution.status == "partial_failure"
    assert execution.step("sandbox").status == "failed"
    assert "timeout" in (execution.step("sandbox").failure_reason or "")
    assert execution.step("browser").status == "succeeded"
    assert sandbox.cleanup_calls == browser.cleanup_calls == 1


def test_receipts_reject_credentials_cookies_and_owner_fields() -> None:
    for leaked in ("slr_" + "live_secret", "api_key=value", "cookie=session", "ownerName"):
        with pytest.raises(ValidationError):
            SolariStepReceipt(
                product="browser",
                status="failed",
                detail=leaked,
                failure_reason="redacted",
            )


def test_permit_html_redacts_ownership_fields_before_browser_recording() -> None:
    source = """
    <span id="FacilityNameLabel" class="h1">Parcel 123</span>
    <span id="FacilityAddressLabel">1 Private Lane</span>
    <div class="dataField"><span class="dataLabel">Permittee name as issued:</span>
    <span class="dataValue">Private Owner</span></div>
    <div class="dataField"><span class="dataLabel">Issued to:</span>
    <span class="dataValue">Private Owner</span></div>
    """

    redacted = _redact_permit_html(source)

    assert redacted.count("[redacted]") == 4
    assert "Parcel 123" not in redacted
    assert "1 Private Lane" not in redacted
    assert "Private Owner" not in redacted


def test_solari_key_uses_standard_environment_name_without_serializing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_key = "slr_" + "live_test-only"
    monkeypatch.setenv("SOLARI_API_KEY", fake_key)
    configured = Settings()
    assert configured.solari_api_key is not None
    assert configured.solari_api_key.get_secret_value() == fake_key
    assert fake_key not in configured.model_dump_json()


def test_desktop_form_is_explicitly_verified_and_non_submittable() -> None:
    form = {
        "mode": "SIMULATION ONLY - DO NOT SUBMIT",
        "vendor": "First State Environmental",
        "appointment": "Aug 6, 2026, 8:00 AM EDT",
        "price": "$480",
    }

    receipt = _desktop_form_text(form)

    assert receipt.startswith("[GUI VERIFIED] CLOSING RESCUE")
    assert "SIMULATION ONLY - NOTHING WILL BE SUBMITTED" in receipt
    assert "Vendor: First State Environmental" in receipt
    assert receipt.endswith("SUBMISSION DISABLED")
    _validate_desktop_text(receipt, receipt.replace("\n", "\r\n") + "\n")


def test_desktop_text_validation_rejects_partial_or_wrong_gui_content() -> None:
    expected = _desktop_form_text({"mode": "SIMULATION ONLY - DO NOT SUBMIT"})

    with pytest.raises(RuntimeError, match="complete simulated form"):
        _validate_desktop_text(expected, expected[:40])


def _png(width: int = 1280, height: int = 720, marker: bytes = b"after") -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + marker * 2_500
    )


def test_desktop_screenshot_validation_requires_changed_full_screen_png() -> None:
    before = _png(marker=b"before")
    after = _png(marker=b"after")

    _validate_desktop_screenshot(before, after)

    with pytest.raises(RuntimeError, match="did not change"):
        _validate_desktop_screenshot(after, after)
    with pytest.raises(RuntimeError, match="valid full-screen PNG"):
        _validate_desktop_screenshot(before, b"not-a-png")
    with pytest.raises(RuntimeError, match="dimensions are too small"):
        _validate_desktop_screenshot(before, _png(width=640, height=480))
