"""Run one real browser, sandbox, and approval-gated desktop smoke path."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from septic_sentinel.config import settings
from septic_sentinel.runtime import (
    build_closing_rescue_service,
    build_solari_execution_service,
)


async def main() -> None:
    rescue = build_closing_rescue_service(settings)
    await rescue.repository.initialize()
    proof = build_solari_execution_service(settings, rescue.repository)
    if proof is None:
        raise SystemExit("SOLARI_API_KEY is not configured; live smoke was not run")

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    result = await rescue.create_competition_demo(f"solari-live-smoke-{run_id}")
    execution = await proof.run_preapproval(result, result.assessments)
    if any(execution.step(product).status != "succeeded" for product in ("sandbox", "browser")):
        raise SystemExit(execution.model_dump_json(indent=2))

    approval = result.case.approvals[-1]
    approved = await rescue.complete_rescue(
        result.portfolio.id,
        approval_id=approval.id,
        approver_identity=approval.approver_identity,
        token=result.approval_token or "",
        approve=True,
    )
    final = await proof.run_desktop_after_approval(approved)
    if final is None or final.step("desktop").status != "succeeded":
        raise SystemExit("Desktop smoke did not return a successful receipt")
    print(final.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
