"""Solari-backed proof rail for Closing Rescue.

The orchestration layer depends on tiny protocols so ordinary CI uses fakes. The
live adapters keep every billable resource inside one timeout and one finally
block, and return only redacted public receipts.
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

import httpx

from septic_sentinel.models import ClosingRescueResult, PriorityAssessment
from septic_sentinel.repository import SQLiteRepository
from septic_sentinel.solari_models import (
    SolariArtifact,
    SolariExecutionStatus,
    SolariExecutionView,
    SolariStepReceipt,
    SolariStepStatus,
    pending_step,
)

DELAWARE_DATASET_API = "https://data.delaware.gov/resource/mv7j-tx3u.json"
ALLOWED_PERMIT_FIELDS = (
    "permitnumber",
    "county",
    "septicsystemtype",
    "permitstatus",
    "constructiontype",
    "appreceiveddate",
    "url_for_permit_details",
)


@dataclass(frozen=True)
class AdapterResult:
    session_id: str
    detail: str
    artifacts: tuple[SolariArtifact, ...]
    manifest_sha256: str | None = None


class SandboxAdapter(Protocol):
    async def run(self, payload: dict[str, Any]) -> AdapterResult: ...


class BrowserAdapter(Protocol):
    async def capture(self) -> AdapterResult: ...


class DesktopAdapter(Protocol):
    async def fill_simulated_form(self, form: dict[str, str]) -> AdapterResult: ...


class SolariNotConfiguredError(RuntimeError):
    pass


class SolariApprovalRequiredError(RuntimeError):
    pass


class SolariExecutionService:
    def __init__(
        self,
        repository: SQLiteRepository,
        sandbox: SandboxAdapter,
        browser: BrowserAdapter,
        desktop: DesktopAdapter,
        *,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.repository = repository
        self.sandbox = sandbox
        self.browser = browser
        self.desktop = desktop
        self.timeout_seconds = timeout_seconds

    async def get(self, portfolio_id: str) -> SolariExecutionView:
        stored = await self.repository.get_solari_execution(portfolio_id)
        if stored is not None:
            return stored
        now = datetime.now(UTC)
        return SolariExecutionView(
            portfolio_id=portfolio_id,
            status=SolariExecutionStatus.AWAITING_APPROVAL,
            steps=(
                pending_step("sandbox", now),
                pending_step("browser", now),
                pending_step("desktop", now),
            ),
            updated_at=now,
        )

    async def run_preapproval(
        self,
        result: ClosingRescueResult,
        assessments: tuple[PriorityAssessment, ...],
    ) -> SolariExecutionView:
        if len(result.portfolio.loans) != 47 or len(assessments) != 47:
            raise ValueError("Solari proof requires the complete 47-loan portfolio")
        now = datetime.now(UTC)
        running = SolariExecutionView(
            portfolio_id=result.portfolio.id,
            status=SolariExecutionStatus.RUNNING,
            steps=(
                SolariStepReceipt(
                    product="sandbox",
                    status=SolariStepStatus.RUNNING,
                    detail="Verifying 47 deterministic portfolio calculations",
                    started_at=now,
                ),
                pending_step("browser", now),
                pending_step("desktop", now),
            ),
            updated_at=now,
        )
        await self.repository.save_solari_execution(running)
        payload = _sandbox_payload(result, assessments)
        sandbox_receipt, sandbox_hash = await self._run_step("sandbox", self.sandbox.run(payload))
        browser_started = datetime.now(UTC)
        await self.repository.save_solari_execution(
            SolariExecutionView(
                portfolio_id=result.portfolio.id,
                status=SolariExecutionStatus.RUNNING,
                steps=(
                    sandbox_receipt,
                    SolariStepReceipt(
                        product="browser",
                        status=SolariStepStatus.RUNNING,
                        detail="Opening the official permit in a recorded browser",
                        started_at=browser_started,
                    ),
                    pending_step("desktop", browser_started),
                ),
                manifest_sha256=sandbox_hash,
                updated_at=browser_started,
            )
        )
        browser_receipt, _ = await self._run_step("browser", self.browser.capture())
        failures = sum(
            item.status is SolariStepStatus.FAILED for item in (sandbox_receipt, browser_receipt)
        )
        status = (
            SolariExecutionStatus.FAILED
            if failures == 2
            else SolariExecutionStatus.PARTIAL_FAILURE
            if failures
            else SolariExecutionStatus.AWAITING_APPROVAL
        )
        finished = SolariExecutionView(
            portfolio_id=result.portfolio.id,
            status=status,
            steps=(sandbox_receipt, browser_receipt, pending_step("desktop", now)),
            manifest_sha256=sandbox_hash,
            updated_at=datetime.now(UTC),
        )
        await self.repository.save_solari_execution(finished)
        return finished

    async def run_desktop_after_approval(
        self, result: ClosingRescueResult
    ) -> SolariExecutionView | None:
        current = await self.repository.get_solari_execution(result.portfolio.id)
        if current is None:
            return None
        approval = result.case.approvals[-1] if result.case.approvals else None
        action = result.case.actions[-1] if result.case.actions else None
        if approval is None or approval.state.value not in {"approved", "consumed"}:
            raise SolariApprovalRequiredError("Desktop interaction requires human approval")
        if action is None:
            raise SolariApprovalRequiredError("Desktop interaction requires an approved action")
        existing = current.step("desktop")
        if existing.status is SolariStepStatus.SUCCEEDED:
            return current
        vendor = result.vendor_selection.selected if result.vendor_selection else None
        if vendor is None:
            return current
        form = {
            "case_reference": result.selected_loan.external_loan_id,
            "service": vendor.service_type,
            "requested_window": vendor.appointment_at.isoformat(),
            "vendor": vendor.vendor_name,
            "mode": "SIMULATION ONLY - DO NOT SUBMIT",
        }
        desktop_receipt, _ = await self._run_step("desktop", self.desktop.fill_simulated_form(form))
        failures = [item for item in current.steps[:2] if item.status is SolariStepStatus.FAILED]
        status = (
            SolariExecutionStatus.SUCCEEDED
            if desktop_receipt.status is SolariStepStatus.SUCCEEDED and not failures
            else SolariExecutionStatus.PARTIAL_FAILURE
        )
        finished = SolariExecutionView(
            portfolio_id=current.portfolio_id,
            status=status,
            steps=(current.steps[0], current.steps[1], desktop_receipt),
            manifest_sha256=current.manifest_sha256,
            updated_at=datetime.now(UTC),
        )
        await self.repository.save_solari_execution(finished)
        return finished

    async def _run_step(self, product: str, operation: Any) -> tuple[SolariStepReceipt, str | None]:
        started = datetime.now(UTC)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                result: AdapterResult = await operation
            return (
                SolariStepReceipt(
                    product=product,
                    status=SolariStepStatus.SUCCEEDED,
                    session_id=result.session_id,
                    detail=result.detail,
                    started_at=started,
                    completed_at=datetime.now(UTC),
                    artifacts=result.artifacts,
                ),
                result.manifest_sha256,
            )
        except TimeoutError:
            reason = f"{product.title()} exceeded the {self.timeout_seconds:g}s timeout"
        except Exception as exc:  # keep one failed product from erasing other receipts
            reason = _safe_failure(exc)
        return (
            SolariStepReceipt(
                product=product,
                status=SolariStepStatus.FAILED,
                detail=f"{product.title()} proof failed safely",
                started_at=started,
                completed_at=datetime.now(UTC),
                failure_reason=reason,
            ),
            None,
        )


class LiveSandboxAdapter:
    def __init__(self, api_key: str, base_url: str, artifact_dir: Path, timeout_ms: int) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.artifact_dir = artifact_dir
        self.timeout_ms = timeout_ms

    async def run(self, payload: dict[str, Any]) -> AdapterResult:
        from solari_sandbox import SandboxClient

        sandbox = None
        async with SandboxClient(
            api_key=self.api_key, base_url=self.base_url, call_timeout_ms=self.timeout_ms
        ) as client:
            try:
                sandbox = await client.create(
                    template="base",
                    timeout_ms=self.timeout_ms,
                    metadata={"project": "closing-rescue", "purpose": "portfolio-verification"},
                )
                await sandbox.connect()
                context = await sandbox.create_code_context("python")
                code = _sandbox_code(payload)
                result = await sandbox.run_code(code, language="python", context_id=context)
                if result.error:
                    raise RuntimeError("sandbox calculation returned an error")
                values = [item.json for item in result.results if item.json is not None]
                if not values:
                    for item in reversed(result.results):
                        if item.text:
                            try:
                                values.append(ast.literal_eval(item.text))
                            except (SyntaxError, ValueError):
                                continue
                            break
                if not values or not isinstance(values[-1], dict):
                    raise RuntimeError("sandbox calculation returned no manifest")
                manifest = values[-1]
                if (
                    manifest.get("input_sha256") != payload["input_sha256"]
                    or manifest.get("loan_count") != len(payload["loans"])
                    or manifest.get("exit_status") != 0
                    or manifest.get("flagged_count") != len(manifest.get("flagged_cases", []))
                ):
                    raise RuntimeError("sandbox calculation returned an invalid manifest")
                canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
                digest, url = _write_artifact(
                    self.artifact_dir, "sandbox-manifest", canonical, "json"
                )
                return AdapterResult(
                    session_id=sandbox.sandboxId,
                    detail=(
                        f"Verified {manifest['loan_count']} loans; "
                        f"{manifest['flagged_count']} flagged"
                    ),
                    artifacts=(
                        SolariArtifact(
                            kind="manifest",
                            label="Calculation manifest",
                            url=url,
                            sha256=digest,
                            media_type="application/json",
                        ),
                    ),
                    manifest_sha256=digest,
                )
            finally:
                if sandbox is not None:
                    try:
                        await sandbox.close()
                    finally:
                        await sandbox.kill()


class LiveBrowserAdapter:
    def __init__(self, api_key: str, base_url: str, artifact_dir: Path, timeout_ms: int) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.artifact_dir = artifact_dir
        self.timeout_ms = timeout_ms

    async def capture(self) -> AdapterResult:
        from playwright.async_api import async_playwright
        from solari_browser import Solari

        record = await _discover_permit_record(self.timeout_ms / 1000)
        detail_url = record["url_for_permit_details"]
        session_id = None
        async with Solari(
            self.api_key, base_url=self.base_url, timeout_ms=self.timeout_ms
        ) as client:
            try:
                session = await client.sessions.create(recording=True)
                session_id = session.id
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.connect_over_cdp(session.cdp_endpoint)
                    try:
                        context = (
                            browser.contexts[0] if browser.contexts else await browser.new_context()
                        )
                        page = await context.new_page()

                        async def redact_owner_row(route: Any) -> None:
                            response = await route.fetch()
                            body = await response.text()
                            redacted = _redact_permit_html(body)
                            await route.fulfill(response=response, body=redacted)

                        # Intercept before rendering so the replay is redacted too.
                        await page.route(detail_url, redact_owner_row)
                        await page.goto(
                            detail_url,
                            wait_until="domcontentloaded",
                            timeout=self.timeout_ms,
                        )
                        # Defense in depth for labels added later by client rendering.
                        await page.evaluate(
                            """() => {
                            const privateLabels =
                              /owner|street address|permittee|issued to|project officer/i;
                            const labels =
                              document.querySelectorAll('.dataLabel,strong,tr,label,dt,th');
                            for (const el of labels) {
                              if (!privateLabels.test(el.textContent || '')) continue;
                              const field = el.closest('.dataField');
                              const value =
                                field?.querySelector('.dataValue') || el.nextElementSibling;
                              if (value) value.textContent = '[redacted]';
                            }
                            for (const id of ['FacilityNameLabel', 'FacilityAddressLabel']) {
                              const value = document.getElementById(id);
                              if (value) value.textContent = '[redacted]';
                            }
                            }"""
                        )
                        screenshot = await page.screenshot(full_page=True)
                        digest, screenshot_url = _write_artifact(
                            self.artifact_dir,
                            "permit-record-redacted",
                            screenshot,
                            "png",
                        )
                    finally:
                        await browser.close()
            finally:
                if session_id is not None:
                    await client.sessions.release_and_wait(session_id)
            if session_id is None:
                raise RuntimeError("browser session was not created")
            replay = await _wait_for_replay(client.sessions, session_id)
        return AdapterResult(
            session_id=session_id,
            detail=(
                f"Captured official Delaware permit {record['permitnumber']} "
                "with owner rows redacted"
            ),
            artifacts=(
                SolariArtifact(kind="citation", label="Official permit detail", url=detail_url),
                SolariArtifact(
                    kind="screenshot",
                    label="Redacted rendered permit",
                    url=screenshot_url,
                    sha256=digest,
                    media_type="image/png",
                ),
                SolariArtifact(kind="replay", label="Recorded browser replay", url=replay.url),
            ),
        )


async def _wait_for_replay(sessions: Any, session_id: str) -> Any:
    """Wait for Solari's asynchronous recording finalization after release."""
    for attempt in range(10):
        try:
            return await sessions.get_replay_url(session_id)
        except Exception:
            if attempt == 9:
                raise
            await asyncio.sleep(1)
    raise RuntimeError("browser replay did not finalize")  # pragma: no cover


def _redact_permit_html(body: str) -> str:
    redacted = re.sub(
        r'(?is)(<span\s+id="(?:FacilityNameLabel|FacilityAddressLabel)"[^>]*>).*?(</span>)',
        r"\1[redacted]\2",
        body,
    )
    private_labels = (
        r"owner|street address|permittee(?: name as issued| contact)?|"
        r"issued to|DNREC project officer"
    )
    return re.sub(
        rf'(?is)(<span\s+class="dataLabel">(?:{private_labels}):?</span>\s*'
        r'<span\s+class="dataValue">).*?(</span>)',
        r"\1[redacted]\2",
        redacted,
    )


class LiveDesktopAdapter:
    def __init__(self, api_key: str, base_url: str, artifact_dir: Path, timeout_ms: int) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.artifact_dir = artifact_dir
        self.timeout_ms = timeout_ms

    async def fill_simulated_form(self, form: dict[str, str]) -> AdapterResult:
        from solari_desktop import DesktopClient

        desktop = None
        async with DesktopClient(
            api_key=self.api_key, base_url=self.base_url, call_timeout_ms=self.timeout_ms
        ) as client:
            try:
                desktop = await client.create(
                    template="default",
                    resolution="1280x720",
                    timeout_ms=self.timeout_ms,
                    metadata={"project": "closing-rescue", "purpose": "approved-form-simulation"},
                )
                await desktop.connect()
                for _ in range(30):
                    health = await desktop.health()
                    if getattr(health, "ready", False):
                        break
                    await asyncio.sleep(1)
                else:
                    raise RuntimeError("desktop GUI did not become ready")
                receipt_text = _desktop_form_text(form)
                await desktop.open("mousepad")
                await asyncio.sleep(4)
                before = await desktop.screenshot(format="png")

                # Mousepad opens in the top-left quadrant. Drive every line through
                # GUI input. The current default desktop image
                # does not expose clipboard or file-read RPCs, so the resulting
                # full-screen receipt is reviewed from the captured PNG.
                await desktop.mouse.click(320, 300, humanize=True)
                lines = receipt_text.splitlines()
                for index, line in enumerate(lines):
                    for offset in range(0, len(line), 8):
                        await desktop.keyboard.type(line[offset : offset + 8])
                        await asyncio.sleep(0.08)
                    if index < len(lines) - 1:
                        await desktop.keyboard.press("Return")
                        await asyncio.sleep(0.2)
                await asyncio.sleep(1)

                screenshot = await desktop.screenshot(format="png")
                _validate_desktop_screenshot(before, screenshot)
                digest, url = _write_artifact(
                    self.artifact_dir, "desktop-form-receipt", screenshot, "png"
                )
                return AdapterResult(
                    session_id=desktop.sessionId,
                    detail=(
                        "Filled the simulated inspection request after human approval; "
                        "nothing submitted"
                    ),
                    artifacts=(
                        SolariArtifact(
                            kind="receipt",
                            label="Desktop form receipt",
                            url=url,
                            sha256=digest,
                            media_type="image/png",
                        ),
                    ),
                )
            finally:
                if desktop is not None:
                    try:
                        await desktop.close()
                    finally:
                        await desktop.kill()


async def _discover_permit_record(request_timeout: float) -> dict[str, str]:
    params = {
        "$limit": "1",
        "$select": ",".join(ALLOWED_PERMIT_FIELDS),
        "$where": "url_for_permit_details is not null AND permitnumber is not null",
        "$order": "appreceiveddate DESC, permitnumber DESC",
    }
    async with httpx.AsyncClient(timeout=request_timeout, follow_redirects=True) as client:
        response = await client.get(DELAWARE_DATASET_API, params=params)
        response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Delaware Open Data returned no permit detail URL")
    return {key: str(rows[0][key]) for key in ALLOWED_PERMIT_FIELDS if key in rows[0]}


def _sandbox_payload(
    result: ClosingRescueResult, assessments: tuple[PriorityAssessment, ...]
) -> dict[str, Any]:
    ranked = {item.external_loan_id: item for item in assessments}
    loans = []
    for loan in result.portfolio.loans:
        item = ranked[loan.external_loan_id]
        loans.append(
            {
                "loan_id": loan.external_loan_id,
                "delay_consequence_cents": item.delay_consequence_cents,
                "delay_probability_bps": item.delay_probability_bps,
                "residual_probability_bps": item.residual_probability_after_intervention_bps,
                "intervention_cost_cents": item.intervention_cost_cents,
                "intervention_available": item.intervention_available,
                "expected_without_cents": item.exposure_without_intervention_cents,
                "expected_after_cents": item.exposure_after_intervention_cents,
                "expected_preventable_cents": item.preventable_exposure_cents,
                "contradiction_score": item.contradiction_score,
                "source_failed": item.source_failed,
            }
        )
    canonical = json.dumps(loans, sort_keys=True, separators=(",", ":"))
    return {"input_sha256": sha256(canonical.encode()).hexdigest(), "loans": loans}


def _sandbox_code(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True)
    lines = [
        "import json",
        f"payload = json.loads({json.dumps(encoded)})",
        "flagged = []",
        "for loan in payload['loans']:",
        "    consequence = loan['delay_consequence_cents']",
        "    without = consequence * loan['delay_probability_bps'] // 10000",
        "    residual = consequence * loan['residual_probability_bps'] // 10000",
        "    after = without",
        "    if loan['intervention_available']:",
        "        after = residual + loan['intervention_cost_cents']",
        "    preventable = max(0, without - after)",
        "    expected = [loan['expected_without_cents']]",
        "    expected += [loan['expected_after_cents']]",
        "    expected += [loan['expected_preventable_cents']]",
        "    assert [without, after, preventable] == expected",
        "    classification = 'matched'",
        "    if loan['source_failed']:",
        "        classification = 'no_match'",
        "    elif loan['contradiction_score'] > 0:",
        "        classification = 'contradiction'",
        "    if classification != 'matched':",
        "        item = {'loan_id': loan['loan_id']}",
        "        item['classification'] = classification",
        "        item['preventable_exposure_cents'] = preventable",
        "        flagged.append(item)",
        "manifest = {'schema': 'closing-rescue-solari-manifest-v1'}",
        "manifest['input_sha256'] = payload['input_sha256']",
        "manifest['loan_count'] = len(payload['loans'])",
        "manifest['flagged_count'] = len(flagged)",
        "manifest['flagged_cases'] = flagged",
        "manifest['formula'] = 'floor(consequence*bps/10000)'",
        "manifest['exit_status'] = 0",
        "manifest",
    ]
    return "\n".join(lines)


def _desktop_form_text(form: dict[str, str]) -> str:
    fields = "\n".join(f"{key.replace('_', ' ').title()}: {value}" for key, value in form.items())
    return (
        "[GUI VERIFIED] CLOSING RESCUE - INSPECTION REQUEST PREVIEW\n"
        "SIMULATION ONLY - NOTHING WILL BE SUBMITTED\n\n"
        f"{fields}\n\n"
        "Approval Note: Approved simulation - no submission\n"
        "SUBMISSION DISABLED"
    )


def _validate_desktop_text(expected: str, observed: str) -> None:
    """Require the GUI editor to return the exact non-submittable form text."""

    def normalize(value: str) -> str:
        return value.replace("\r\n", "\n").strip()

    if normalize(observed) != normalize(expected):
        raise RuntimeError("desktop GUI did not contain the complete simulated form")


def _validate_desktop_screenshot(before: bytes, after: bytes) -> None:
    """Reject unchanged, malformed, or implausibly small desktop receipts."""
    if before == after:
        raise RuntimeError("desktop receipt did not change after GUI input")
    if len(after) < 10_000 or not after.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("desktop receipt is not a valid full-screen PNG")
    if len(after) < 24 or after[12:16] != b"IHDR":
        raise RuntimeError("desktop receipt is missing PNG dimensions")
    width, height = struct.unpack(">II", after[16:24])
    if width < 1_000 or height < 600:
        raise RuntimeError("desktop receipt dimensions are too small to review")


def _write_artifact(directory: Path, stem: str, data: bytes, extension: str) -> tuple[str, str]:
    digest = sha256(data).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{stem}-{digest[:16]}.{extension}"
    (directory / name).write_bytes(data)
    return digest, f"/api/v2/closing-rescue/artifacts/{name}"


def _safe_failure(exc: Exception) -> str:
    name = type(exc).__name__.replace("Error", " error").strip()
    return f"{name or 'External service error'}; no credentials or private response retained"[:300]
