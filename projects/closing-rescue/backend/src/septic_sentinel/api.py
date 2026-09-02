"""Versioned FastAPI surface for the Septic Sentinel workflow."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from septic_sentinel.actions import ApprovalConflictError, ApprovalTokenError
from septic_sentinel.closing_rescue import (
    ClosingRescueConflictError,
    ClosingRescueInvalidRequestError,
    ClosingRescueService,
)
from septic_sentinel.config import settings
from septic_sentinel.contradictions import ContradictionEngine
from septic_sentinel.exposure import ExposureEngine
from septic_sentinel.models import (
    ActionAttempt,
    CaseCreate,
    CaseRecord,
    CaseView,
    ClosingClaimView,
    ClosingPortfolioSummary,
    ClosingPriorityView,
    ClosingRescueApprovalRequest,
    ClosingRescueResult,
    ClosingRescueView,
    Evidence,
    StoryEvent,
    TruthClass,
)
from septic_sentinel.observability import configure_logging
from septic_sentinel.priority import PriorityEngine
from septic_sentinel.public_record_check import (
    PublicLookupRateLimiter,
    PublicRecordCheckRequest,
    PublicRecordCheckResult,
    PublicRecordUnavailableError,
    check_public_record,
)
from septic_sentinel.repository import (
    CaseNotFoundError,
    RepositoryConflictError,
    RepositoryNotFoundError,
)
from septic_sentinel.runtime import build_service, build_solari_execution_service
from septic_sentinel.service import ProcessedCase
from septic_sentinel.solari_models import SolariExecutionView
from septic_sentinel.vendors import VendorScout

service = build_service(settings)
solari_execution_service = build_solari_execution_service(settings, service.repository)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    await service.repository.initialize()
    yield


app = FastAPI(
    title="Septic Sentinel API",
    version="0.1.0",
    description="Cited property-condition due diligence with approval-gated actions.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-Idempotency-Key"],
)

logger = logging.getLogger("septic_sentinel.api")
public_lookup_limiter = PublicLookupRateLimiter()


@app.middleware("http")
async def request_observability(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or f"req_{uuid4().hex}"
    started = monotonic()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request.failed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "latency_ms": round((monotonic() - started) * 1000, 1),
                "outcome": "error",
            },
        )
        raise
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request.completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "latency_ms": round((monotonic() - started) * 1000, 1),
            "outcome": "success" if response.status_code < 400 else "client_error",
        },
    )
    return response


class ApprovalDecision(BaseModel):
    approver_identity: str
    approval_token: str
    approve: bool
    simulate_timeout: bool = False


class ApprovalResult(BaseModel):
    action: ActionAttempt | None
    view: CaseView


def _closing_rescue_service() -> ClosingRescueService:
    """Bind v2 to the same repository instance used by v1 and by API tests."""
    return ClosingRescueService(
        case_service=service,
        priority=PriorityEngine(),
        contradictions=ContradictionEngine(),
        vendors=VendorScout(),
        exposure=ExposureEngine(),
    )


async def _closing_rescue_view(
    rescue: ClosingRescueService,
    result: ClosingRescueResult,
    *,
    approval_token: str | None = None,
) -> ClosingRescueView:
    batches = await rescue.repository.list_priority_assessment_batches(result.portfolio.id)
    if not batches:
        raise RuntimeError("Closing Rescue priority snapshots are unavailable")
    current_batch_id = batches[0]
    initial_batch_id = batches[-1]
    current = tuple(
        await rescue.repository.list_priority_assessments(result.portfolio.id, current_batch_id)
    )
    initial = tuple(
        await rescue.repository.list_priority_assessments(result.portfolio.id, initial_batch_id)
    )
    seller_claim, permit_claim = _claim_views(result)
    return ClosingRescueView(
        portfolio_id=result.portfolio.id,
        status=result.status,
        reason=result.reason,
        portfolio_summary=ClosingPortfolioSummary(
            loan_count=len(result.portfolio.loans),
            pipeline_value_cents=sum(loan.loan_amount_cents for loan in result.portfolio.loans),
            attention_candidate_count=sum(
                loan.fixture_scenario != "routine" for loan in result.portfolio.loans
            ),
            total_estimated_exposure_cents=sum(
                item.exposure_without_intervention_cents for item in initial
            ),
        ),
        selected_case=result.selected_loan,
        priority=ClosingPriorityView(
            initial_batch_id=initial_batch_id,
            current_batch_id=current_batch_id,
            initial=initial,
            current=current,
        ),
        case_state=result.case.case.state,
        current_chapter=result.story_events[-1].chapter,
        evidence=result.case.evidence,
        seller_claim=seller_claim,
        permit_claim=permit_claim,
        contradiction=result.contradiction,
        exposure=result.exposure,
        proposed_rescue=result.vendor_selection,
        approval=result.case.approvals[-1] if result.case.approvals else None,
        actions=result.case.actions,
        story_events=result.story_events,
        approval_token=approval_token,
    )


def _claim_views(
    result: ClosingRescueResult,
) -> tuple[ClosingClaimView | None, ClosingClaimView | None]:
    if result.contradiction is None:
        return None, None
    seller_payload = json.loads(result.selected_loan.seller_claims_json)
    supported = next(
        (claim for claim in seller_payload if claim.get("field") == "septic_replacement_year"),
        None,
    )
    permit = next(
        (
            item
            for item in result.case.evidence
            if item.kind == "septic_permit" and item.status.value == "success"
        ),
        None,
    )
    if supported is None or permit is None:
        return None, None
    permits = json.loads(permit.payload_json).get("permits", [])
    received = permits[0].get("appreceiveddate") if permits else None
    try:
        permit_year = int(received[:4])
    except (TypeError, ValueError):
        return None, None
    claim_ids = result.contradiction.claim_ids
    if len(claim_ids) < 2:
        return None, None
    return (
        ClosingClaimView(
            id=claim_ids[0],
            field=supported["field"],
            value=supported.get("value"),
            truth_class=TruthClass.SYNTHETIC,
            source_name="Seller submission",
            observed_at=result.portfolio.created_at,
        ),
        ClosingClaimView(
            id=claim_ids[1],
            field="septic_replacement_year",
            value=permit_year,
            truth_class=TruthClass.EXTERNAL_CITED,
            source_name=permit.source,
            observed_at=permit.retrieved_at,
            citation_ids=result.contradiction.citation_ids,
        ),
    )


def _raise_closing_rescue_http_error(exc: Exception) -> None:
    if isinstance(exc, (RepositoryNotFoundError, CaseNotFoundError)):
        detail = (
            "Approval not found"
            if isinstance(exc, CaseNotFoundError)
            else "Closing Rescue portfolio not found"
        )
        raise HTTPException(status_code=404, detail=detail) from exc
    if isinstance(exc, ApprovalTokenError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(
        exc,
        (ApprovalConflictError, RepositoryConflictError, ClosingRescueConflictError),
    ):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ClosingRescueInvalidRequestError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, sqlite3.OperationalError):
        raise HTTPException(
            status_code=503, detail="Closing Rescue is temporarily unavailable"
        ) from exc
    raise HTTPException(
        status_code=500, detail="Closing Rescue encountered an unexpected error"
    ) from exc


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": settings.mode}


@app.get("/api/v1/ready")
async def readiness(response: Response) -> dict[str, str]:
    try:
        await service.repository.ping()
    except Exception:
        logger.exception("readiness.failed")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "mode": settings.mode, "database": "unavailable"}
    return {"status": "ready", "mode": settings.mode, "database": "ok"}


@app.post(
    "/api/v2/closing-rescue/public-record-check",
    response_model=PublicRecordCheckResult,
)
async def create_public_record_check(
    request: Request,
    payload: PublicRecordCheckRequest,
) -> PublicRecordCheckResult:
    """Run a fresh, owner-free lookup against Delaware's official public dataset."""
    client_identity = request.client.host if request.client else "unknown"
    if not public_lookup_limiter.allow(client_identity):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many public record checks; try again in one minute",
            headers={"Retry-After": "60"},
        )
    try:
        return await check_public_record(payload)
    except PublicRecordUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post(
    "/api/v2/closing-rescue/demo",
    response_model=ClosingRescueView,
    status_code=status.HTTP_201_CREATED,
)
async def create_closing_rescue_demo(
    response: Response,
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", max_length=200
    ),
) -> ClosingRescueView:
    key = idempotency_key.strip() if isinstance(idempotency_key, str) else ""
    if not key:
        raise HTTPException(status_code=422, detail="Idempotency-Key must not be blank")
    rescue = _closing_rescue_service()
    try:
        delivery = await rescue.create_competition_demo_delivery(key)
        if delivery.outcome != "created":
            response.status_code = status.HTTP_200_OK
        return await _closing_rescue_view(
            rescue,
            delivery.result,
            approval_token=(
                delivery.result.approval_token if delivery.token_generated else None
            ),
        )
    except Exception as exc:
        _raise_closing_rescue_http_error(exc)
        raise AssertionError("unreachable") from exc


@app.get("/api/v2/closing-rescue/artifacts/{artifact_name}", response_class=FileResponse)
async def get_solari_artifact(artifact_name: str) -> FileResponse:
    """Serve only hash-named public receipts from the configured artifact directory."""
    if not artifact_name or artifact_name != Path(artifact_name).name:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if re.fullmatch(
        r"(?:sandbox-manifest|permit-record-redacted|desktop-form-receipt)-"
        r"[a-f0-9]{16}\.(?:json|png|jpg)",
        artifact_name,
    ) is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    artifact = Path(settings.solari_artifact_dir) / artifact_name
    if not artifact.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(artifact)


@app.get(
    "/api/v2/closing-rescue/{portfolio_id}/solari",
    response_model=SolariExecutionView,
)
async def get_closing_rescue_solari(portfolio_id: str) -> SolariExecutionView:
    rescue = _closing_rescue_service()
    try:
        await rescue.get_competition_demo(portfolio_id)
        if solari_execution_service is None:
            raise HTTPException(status_code=503, detail="SOLARI_API_KEY is not configured")
        return await solari_execution_service.get(portfolio_id)
    except HTTPException:
        raise
    except Exception as exc:
        _raise_closing_rescue_http_error(exc)
        raise AssertionError("unreachable") from exc


@app.post(
    "/api/v2/closing-rescue/{portfolio_id}/solari",
    response_model=SolariExecutionView,
)
async def run_closing_rescue_solari(portfolio_id: str) -> SolariExecutionView:
    if solari_execution_service is None:
        raise HTTPException(status_code=503, detail="SOLARI_API_KEY is not configured")
    rescue = _closing_rescue_service()
    try:
        result = await rescue.get_competition_demo(portfolio_id)
        return await solari_execution_service.run_preapproval(result, tuple(result.assessments))
    except Exception as exc:
        _raise_closing_rescue_http_error(exc)
        raise AssertionError("unreachable") from exc


@app.get("/api/v2/closing-rescue/{portfolio_id}", response_model=ClosingRescueView)
async def get_closing_rescue(portfolio_id: str) -> ClosingRescueView:
    rescue = _closing_rescue_service()
    try:
        result = await rescue.get_competition_demo(portfolio_id)
        return await _closing_rescue_view(rescue, result)
    except Exception as exc:
        _raise_closing_rescue_http_error(exc)
        raise AssertionError("unreachable") from exc


@app.get(
    "/api/v2/closing-rescue/{portfolio_id}/events",
    response_model=tuple[StoryEvent, ...],
)
async def get_closing_rescue_events(
    portfolio_id: str,
    after: str | None = Query(default=None, min_length=1, max_length=200),
) -> tuple[StoryEvent, ...]:
    rescue = _closing_rescue_service()
    try:
        result = await rescue.get_competition_demo(portfolio_id)
        if after is None:
            return result.story_events
        for index, event in enumerate(result.story_events):
            if event.id == after:
                return result.story_events[index + 1 :]
        raise HTTPException(status_code=404, detail="Story event not found")
    except HTTPException:
        raise
    except Exception as exc:
        _raise_closing_rescue_http_error(exc)
        raise AssertionError("unreachable") from exc


@app.post(
    "/api/v2/closing-rescue/{portfolio_id}/approve",
    response_model=ClosingRescueView,
)
async def approve_closing_rescue(
    portfolio_id: str, request: ClosingRescueApprovalRequest
) -> ClosingRescueView:
    rescue = _closing_rescue_service()
    try:
        result = await rescue.complete_rescue(
            portfolio_id,
            approval_id=request.approval_id,
            approver_identity=request.approver_identity,
            token=request.approval_token,
            approve=request.approve,
            simulate_timeout=request.simulate_timeout,
        )
        if request.approve and solari_execution_service is not None:
            try:
                await solari_execution_service.run_desktop_after_approval(result)
            except Exception:
                logger.warning(
                    "solari.desktop.failed_after_approval",
                    extra={"portfolio_id": portfolio_id, "outcome": "partial_failure"},
                )
        return await _closing_rescue_view(rescue, result)
    except Exception as exc:
        _raise_closing_rescue_http_error(exc)
        raise AssertionError("unreachable") from exc


@app.post(
    "/api/v1/cases",
    response_model=ProcessedCase,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_case(request: CaseCreate, response: Response) -> ProcessedCase:
    result = await service.ingest(request)
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return result


@app.get("/api/v1/cases", response_model=list[CaseRecord])
async def list_cases() -> list[CaseRecord]:
    return await service.repository.list_cases()


@app.get("/api/v1/cases/{case_id}", response_model=CaseView)
async def get_case(case_id: str) -> CaseView:
    try:
        return await service.get_view(case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc


@app.get("/api/v1/cases/{case_id}/evidence", response_model=list[Evidence])
async def get_evidence(case_id: str) -> list[Evidence]:
    return (await get_case(case_id)).evidence


@app.get("/api/v1/cases/{case_id}/memo", response_class=Response)
async def get_memo(case_id: str) -> Response:
    view = await get_case(case_id)
    if view.memo is None:
        raise HTTPException(status_code=409, detail="Case does not have a decision memo")
    return Response(content=view.memo, media_type="text/markdown")


@app.post("/api/v1/cases/{case_id}/reevaluate", response_model=ProcessedCase)
async def reevaluate(case_id: str) -> ProcessedCase:
    try:
        return await service.reevaluate(case_id)
    except (CaseNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/cases/{case_id}/evidence", response_model=ProcessedCase)
async def add_evidence(case_id: str, item: Evidence) -> ProcessedCase:
    try:
        return await service.add_manual_evidence(case_id, item)
    except (CaseNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/approvals/{approval_id}", response_model=ApprovalResult)
async def decide_approval(approval_id: str, request: ApprovalDecision) -> ApprovalResult:
    try:
        approval = await service.repository.get_approval(approval_id)
        action = await service.actions.decide(
            approval_id,
            approver_identity=request.approver_identity,
            token=request.approval_token,
            approve=request.approve,
            simulate_timeout=request.simulate_timeout,
        )
        return ApprovalResult(action=action, view=await service.get_view(approval.case_id))
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc
    except ApprovalTokenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ApprovalConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
