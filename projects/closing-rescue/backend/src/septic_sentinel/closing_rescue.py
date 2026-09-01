"""Persisted, resumable orchestration for the Closing Rescue competition story."""

from __future__ import annotations

import asyncio
import fcntl
import json
from collections.abc import Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import IO, Any, Literal

from septic_sentinel.actions import ApprovalConflictError, RescueActionPayload
from septic_sentinel.contradictions import ContradictionEngine
from septic_sentinel.domain import ActionState, CaseState, EvidenceStatus
from septic_sentinel.exposure import ExposureEngine
from septic_sentinel.models import (
    ActionAttempt,
    AuditEvent,
    CaseCreate,
    CaseView,
    ClosingActionProjection,
    ClosingApprovalProjection,
    ClosingAuditProjection,
    ClosingCaseProjection,
    ClosingCaseRecordProjection,
    ClosingCitationProjection,
    ClosingDecisionProjection,
    ClosingEvidenceProjection,
    ClosingLoanProjection,
    ClosingPortfolioProjection,
    ClosingRescueResult,
    ContradictionFinding,
    ContradictionKind,
    FrozenDataItem,
    NormalizedClaim,
    PortfolioInvestigation,
    PortfolioLoan,
    PortfolioSnapshot,
    PrioritySignals,
    PrioritySourceInput,
    StoryEvent,
    TruthClass,
    VendorOption,
)
from septic_sentinel.portfolio_fixtures import load_competition_portfolio
from septic_sentinel.priority import PriorityEngine
from septic_sentinel.repository import SQLiteRepository
from septic_sentinel.service import SepticSentinelService
from septic_sentinel.vendors import VendorScout, load_delaware_inspectors

DEFAULT_AS_OF = datetime(2026, 8, 5, 18, tzinfo=UTC)
VENDOR_CUTOFF = datetime(2026, 8, 11, 16, tzinfo=UTC)
RECOVERY_EVENT = "closing_rescue.recovery"

CHAPTER_BY_EVENT = {
    "portfolio.scanned": 1,
    "portfolio.case_selected": 2,
    "evidence.completed": 3,
    "contradiction.detected": 4,
    "exposure.calculated": 5,
    "rescue.proposed": 6,
    "rescue.completed": 6,
}


class RecoveryNotSupportedError(RuntimeError):
    """The persisted manual outcome has no implemented automated repair path."""


class ClosingRescueInvalidRequestError(ValueError):
    """A caller-supplied orchestration value violates the public contract."""


class ClosingRescueConflictError(RuntimeError):
    """Persisted rescue state cannot accept the requested domain operation."""


@dataclass(frozen=True)
class ClosingRescueDelivery:
    """Atomic result metadata produced while holding the workflow lock."""

    result: ClosingRescueResult
    outcome: Literal["created", "resumed", "replayed"]
    token_generated: bool


class ClosingRescueService:
    """Run an idempotent SQLite-backed saga without approving external actions."""

    def __init__(
        self,
        case_service: SepticSentinelService,
        priority: PriorityEngine,
        contradictions: ContradictionEngine,
        vendors: VendorScout,
        exposure: ExposureEngine,
        *,
        portfolio_loader: Callable[[], list[PortfolioLoan]] = load_competition_portfolio,
        vendor_loader: Callable[[], list[VendorOption]] = load_delaware_inspectors,
    ) -> None:
        self.case_service = case_service
        self.repository: SQLiteRepository = case_service.repository
        self.priority = priority
        self.contradictions = contradictions
        self.vendors = vendors
        self.exposure = exposure
        self.portfolio_loader = portfolio_loader
        self.vendor_loader = vendor_loader

    async def create_competition_demo(
        self, idempotency_key: str, *, as_of: datetime = DEFAULT_AS_OF
    ) -> ClosingRescueResult:
        return (
            await self.create_competition_demo_delivery(
                idempotency_key, as_of=as_of
            )
        ).result

    async def create_competition_demo_delivery(
        self, idempotency_key: str, *, as_of: datetime = DEFAULT_AS_OF
    ) -> ClosingRescueDelivery:
        """Create or resume once and report delivery metadata from inside the lock."""
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ClosingRescueInvalidRequestError("idempotency_key must not be blank")
        if len(idempotency_key) > 200:
            raise ClosingRescueInvalidRequestError(
                "idempotency_key must not exceed 200 characters"
            )
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ClosingRescueInvalidRequestError("as_of must be timezone-aware")
        key = idempotency_key.strip()
        as_of = as_of.astimezone(UTC)
        async with self._workflow_lock(key):
            portfolio = await self.repository.get_portfolio_by_idempotency(key)
            created = portfolio is None
            was_terminal = (
                False
                if portfolio is None
                else await self._portfolio_has_terminal_outcome(portfolio)
            )
            if portfolio is None:
                portfolio_id = self._stable_id("portfolio", key)
                portfolio, _ = await self.repository.create_portfolio(
                    PortfolioSnapshot(
                        id=portfolio_id,
                        idempotency_key=key,
                        loans=[
                            loan.model_copy(
                                update={
                                    "id": self._stable_id(
                                        "loan", portfolio_id, loan.external_loan_id
                                    )
                                }
                            )
                            for loan in self.portfolio_loader()
                        ],
                        created_at=as_of,
                    )
                )
            result = await self._resume(portfolio, as_of)
            token_generated = result.approval_token is not None
            outcome: Literal["created", "resumed", "replayed"] = (
                "created" if created else "replayed" if was_terminal else "resumed"
            )
            return ClosingRescueDelivery(
                result=result,
                outcome=outcome,
                token_generated=token_generated,
            )

    async def get_competition_demo(self, portfolio_id: str) -> ClosingRescueResult:
        """Reconstruct a read-only snapshot without resuming or mutating the saga."""
        portfolio = await self.repository.get_portfolio(portfolio_id)
        return await self._reconstruct(portfolio)

    async def _portfolio_has_terminal_outcome(
        self, portfolio: PortfolioSnapshot
    ) -> bool:
        investigation = await self.repository.get_investigation(portfolio.id)
        if investigation is None:
            return False
        loan = self._selected_loan(portfolio, investigation)
        case = await self.repository.get_case_by_idempotency(
            self._case_key(portfolio, loan)
        )
        if case is None:
            return False
        return self._terminal_event(await self.repository.get_view(case.id)) is not None

    async def rotate_pending_rescue_token(
        self,
        portfolio_id: str,
        approver_identity: str,
        recovery_credential: str,
    ) -> str:
        portfolio = await self.repository.get_portfolio(portfolio_id)
        investigation = await self.repository.get_investigation(portfolio.id)
        if investigation is None:
            raise ValueError("Portfolio does not have an investigation")
        loan = self._selected_loan(portfolio, investigation)
        case = await self.repository.get_case_by_idempotency(
            self._case_key(portfolio, loan)
        )
        if case is None:
            raise ValueError("Portfolio does not have a rescue case")
        view = await self.repository.get_view(case.id)
        if not view.approvals:
            raise ValueError("Portfolio does not have a pending rescue approval")
        return await self.case_service.actions.rotate_pending_token(
            view.approvals[-1].id, approver_identity, recovery_credential
        )

    async def complete_rescue(
        self,
        portfolio_id: str,
        *,
        approval_id: str,
        approver_identity: str,
        token: str,
        approve: bool,
        simulate_timeout: bool = False,
    ) -> ClosingRescueResult:
        """Decide one rescue approval and reconcile its durable simulated outcome."""
        portfolio = await self.repository.get_portfolio(portfolio_id)
        async with self._workflow_lock(portfolio.idempotency_key):
            portfolio = await self.repository.get_portfolio(portfolio_id)
            investigation = await self.repository.get_investigation(portfolio.id)
            if investigation is None:
                raise ClosingRescueConflictError(
                    "Portfolio does not have an investigation"
                )
            loan = self._selected_loan(portfolio, investigation)
            case = await self.repository.get_case_by_idempotency(
                self._case_key(portfolio, loan)
            )
            if case is None:
                raise ClosingRescueConflictError(
                    "Portfolio does not have a rescue case"
                )
            approval = await self.repository.get_approval(approval_id)
            if approval.case_id != case.id:
                raise ApprovalConflictError("Approval does not belong to this rescue")
            action = await self.case_service.actions.decide(
                approval_id,
                approver_identity=approver_identity,
                token=token,
                approve=approve,
                simulate_timeout=simulate_timeout,
            )
            if action is not None and action.state is ActionState.SUCCEEDED:
                await self._reconcile_completed_action(portfolio, loan, action)
            return await self._reconstruct(portfolio)

    async def clear_recovery(
        self, portfolio_id: str, actor_identity: str, reason: str
    ) -> AuditEvent:
        actor = actor_identity.strip() if isinstance(actor_identity, str) else ""
        safe_reason = reason.strip() if isinstance(reason, str) else ""
        if not actor or not safe_reason:
            raise ValueError("actor_identity and reason must not be blank")
        portfolio = await self.repository.get_portfolio(portfolio_id)
        async with self._workflow_lock(portfolio.idempotency_key):
            return await self._clear_recovery_locked(
                portfolio_id, actor, safe_reason
            )

    async def _clear_recovery_locked(
        self, portfolio_id: str, actor: str, safe_reason: str
    ) -> AuditEvent:
        portfolio = await self.repository.get_portfolio(portfolio_id)
        investigation = await self.repository.get_investigation(portfolio.id)
        if investigation is None:
            raise ValueError("Portfolio does not have an investigation")
        loan = self._selected_loan(portfolio, investigation)
        case = await self.repository.get_case_by_idempotency(
            self._case_key(portfolio, loan)
        )
        if case is None:
            raise ValueError("Portfolio does not have a rescue case")
        if actor != case.approver_identity:
            raise PermissionError("Actor is not authorized to clear this recovery")
        view = await self.repository.get_view(case.id)
        recovery = next(
            (event for event in reversed(view.events) if event.event_type == RECOVERY_EVENT),
            None,
        )
        if recovery is None:
            raise ValueError("Portfolio does not have a recovery to clear")
        if recovery.data.get("reason_code") != "no_qualifying_vendor":
            raise RecoveryNotSupportedError(
                "Only no_qualifying_vendor recovery can currently be cleared"
            )
        existing = next(
            (
                event
                for event in view.events
                if event.event_type == "closing_rescue.recovery_cleared"
                and event.data.get("recovery_event_id") == recovery.id
            ),
            None,
        )
        if existing is not None:
            if existing.data.get("actor_identity") == actor and existing.data.get(
                "reason"
            ) == safe_reason:
                return existing
            raise ValueError("Recovery was already cleared with different audit data")
        cleared = AuditEvent(
            id=self._stable_id("evt_recovery_cleared", recovery.id),
            case_id=case.id,
            event_type="closing_rescue.recovery_cleared",
            message="Closing Rescue manual recovery was cleared",
            data={
                "recovery_event_id": recovery.id,
                "actor_identity": actor,
                "reason": safe_reason,
                "portfolio_id": portfolio.id,
            },
        )
        await self.repository.add_event(cleared)
        if case.state is CaseState.MANUAL_REVIEW:
            await self.repository.transition_case(case.id, CaseState.REASONING)
        return cleared

    async def _resume(
        self, portfolio: PortfolioSnapshot, as_of: datetime
    ) -> ClosingRescueResult:
        batch_id = self._stable_id("priority_batch", portfolio.id)
        assessments = await self.repository.list_priority_assessments(
            portfolio.id, batch_id=batch_id
        )
        if not assessments:
            ranked = self.priority.rank(portfolio.loans, as_of=as_of.date())
            await self.repository.add_priority_assessments(
                portfolio.id, ranked, batch_id=batch_id
            )
            assessments = await self.repository.list_priority_assessments(
                portfolio.id, batch_id=batch_id
            )

        investigation = await self.repository.get_investigation(portfolio.id)
        if investigation is None:
            investigation, _ = await self.repository.select_investigation(
                portfolio.id, assessments[0].external_loan_id
            )
        selected_loan = self._selected_loan(portfolio, investigation)
        case_key = self._case_key(portfolio, selected_loan)
        case = await self.repository.get_case_by_idempotency(case_key)
        approval_token: str | None = None
        if case is None:
            collected = await self.case_service.create_and_collect(
                self._case_create(portfolio, selected_loan)
            )
            case = collected.view.case
        elif case.state is CaseState.RECEIVED:
            collected = await self.case_service.collect_existing(case.id)
            case = collected.view.case

        view = await self.case_service.get_view(case.id)
        cleared_recovery = self._latest_cleared_recovery(view)
        await self._persist_base_story(
            view.case.id,
            portfolio=portfolio,
            batch_id=batch_id,
            investigation_id=investigation.id,
            selected_loan=selected_loan,
            source_events=view.events,
            as_of=as_of,
        )
        view = await self.case_service.get_view(case.id)
        if self._terminal_event(view) is not None:
            return await self._reconstruct(portfolio)

        if view.case.state is CaseState.WAITING_FOR_CLARIFICATION:
            await self._persist_recovery(
                view,
                portfolio,
                selected_loan,
                investigation,
                code="ambiguous_location",
                reason="Property location is ambiguous; evidence joins were stopped.",
                as_of=as_of,
            )
            return await self._reconstruct(portfolio)
        if view.case.state in {CaseState.RESOLVING, CaseState.COLLECTING}:
            await self.repository.transition_case(view.case.id, CaseState.MANUAL_REVIEW)
            view = await self.case_service.get_view(view.case.id)
            await self._persist_recovery(
                view,
                portfolio,
                selected_loan,
                investigation,
                code="collection_interrupted",
                reason="Evidence collection was interrupted; manual recovery is required.",
                as_of=as_of,
            )
            return await self._reconstruct(portfolio)
        if view.case.state is CaseState.MANUAL_REVIEW:
            await self._persist_recovery(
                view,
                portfolio,
                selected_loan,
                investigation,
                code="case_manual_review",
                reason="The case requires manual review before a rescue can be proposed.",
                as_of=as_of,
            )
            return await self._reconstruct(portfolio)

        findings = await self.repository.list_contradictions(
            portfolio.id, selected_loan.external_loan_id
        )
        recovery: tuple[str, str] | None = None
        if findings:
            contradiction = findings[-1]
            if contradiction.kind is not ContradictionKind.DIRECT:
                recovery = self._finding_recovery(contradiction)
        else:
            contradiction, recovery = self._derive_contradiction(
                portfolio, selected_loan, view, as_of
            )
            if contradiction is not None:
                await self.repository.add_contradiction(
                    portfolio.id, selected_loan.external_loan_id, contradiction
                )
        if contradiction is not None:
            await self._story_event(
                view.case.id,
                "contradiction.detected",
                "Seller and cited permit dates were compared",
                {
                    "portfolio_id": portfolio.id,
                    "loan_id": selected_loan.id,
                    "investigation_id": investigation.id,
                    "contradiction_id": contradiction.id,
                    "claim_ids": list(contradiction.claim_ids),
                    "citation_ids": list(contradiction.citation_ids),
                    "story_order": 5,
                },
                as_of,
            )
        if recovery is not None:
            await self._move_to_manual_if_allowed(view.case.id)
            await self._persist_recovery(
                await self.case_service.get_view(view.case.id),
                portfolio,
                selected_loan,
                investigation,
                code=recovery[0],
                reason=recovery[1],
                as_of=as_of,
                contradiction=contradiction,
            )
            return await self._reconstruct(portfolio)
        if contradiction is None or contradiction.kind is not ContradictionKind.DIRECT:
            raise AssertionError("Direct contradiction gate was not satisfied")

        retry_vendor = (
            cleared_recovery is not None
            and cleared_recovery.data.get("reason_code") == "no_qualifying_vendor"
        )
        selection = None
        if not retry_vendor:
            selection = await self.repository.get_latest_vendor_selection(
                portfolio.id, selected_loan.external_loan_id
            )
        if selection is None:
            vendor_as_of = as_of + (timedelta(microseconds=1) if retry_vendor else timedelta())
            selection = self.vendors.select(
                self.vendor_loader(),
                selected_loan.approved_vendors,
                cutoff=VENDOR_CUTOFF,
                as_of=vendor_as_of,
            )
            await self.repository.add_vendor_selection(
                portfolio.id, selected_loan.external_loan_id, selection
            )
        if selection.selected is None:
            await self._move_to_manual_if_allowed(view.case.id)
            await self._persist_recovery(
                await self.case_service.get_view(view.case.id),
                portfolio,
                selected_loan,
                investigation,
                code="no_qualifying_vendor",
                reason="No qualifying approved vendor option is available.",
                as_of=as_of,
                contradiction=contradiction,
            )
            return await self._reconstruct(portfolio)

        estimate = await self.repository.get_exposure_estimate(
            portfolio.id, selected_loan.external_loan_id, "before_rescue"
        )
        if estimate is None:
            estimate = self.exposure.estimate(
                delay_consequence_cents=selected_loan.delay_consequence_cents,
                delay_probability_bps=7_500,
                residual_probability_bps=1_800,
                intervention_cost_cents=selection.selected.price_cents,
            ).model_copy(
                update={
                    "id": self._stable_id(
                        "exposure", portfolio.id, selected_loan.external_loan_id
                    ),
                    "created_at": as_of,
                }
            )
            await self.repository.add_exposure_estimate(
                portfolio.id, selected_loan.external_loan_id, "before_rescue", estimate
            )
        await self._story_event(
            view.case.id,
            "exposure.calculated",
            "Preventable closing exposure was calculated",
            {
                "portfolio_id": portfolio.id,
                "loan_id": selected_loan.id,
                "exposure_id": estimate.id,
                "vendor_option_id": selection.selected.id,
                "story_order": 6,
            },
            as_of,
        )

        current = await self.repository.get_case(view.case.id)
        if current.state is CaseState.REASONING:
            decided = await self.case_service.decide_existing(current.id, created=True)
            approval_token = decided.approval_token
            view = decided.view
        else:
            view = await self.case_service.get_view(current.id)
        if not view.approvals or view.case.state is not CaseState.WAITING_FOR_APPROVAL:
            await self._persist_recovery(
                view,
                portfolio,
                selected_loan,
                investigation,
                code="approval_not_drafted",
                reason="The eligible rescue did not produce a pending approval draft.",
                as_of=as_of,
                contradiction=contradiction,
            )
            return await self._reconstruct(portfolio)
        approval = await self.case_service.actions.replace_pending_draft(
            view.approvals[-1].id,
            RescueActionPayload(
                portfolio_id=portfolio.id,
                external_loan_id=selected_loan.external_loan_id,
                vendor_option_id=selection.selected.id,
                vendor_name=selection.selected.vendor_name,
                appointment_at=selection.selected.appointment_at,
                price_cents=selection.selected.price_cents,
                service_type=selection.selected.service_type,
                property_address=selected_loan.address,
            ),
        )
        view = await self.case_service.get_view(view.case.id)
        await self._story_event(
            view.case.id,
            "rescue.proposed",
            "A vendor-backed rescue was proposed for human approval",
            {
                "portfolio_id": portfolio.id,
                "loan_id": selected_loan.id,
                "investigation_id": investigation.id,
                "exposure_id": estimate.id,
                "vendor_option_id": selection.selected.id,
                "approval_id": approval.id,
                "story_order": 7,
            },
            as_of,
        )
        return await self._reconstruct(portfolio, approval_token=approval_token)

    async def _reconcile_completed_action(
        self,
        portfolio: PortfolioSnapshot,
        loan: PortfolioLoan,
        action: ActionAttempt,
    ) -> None:
        """Persist the post-booking estimate and completion event exactly once."""
        payload = RescueActionPayload.model_validate_json(
            self._canonical_json(action.payload)
        )
        selection = await self.repository.get_latest_vendor_selection(
            portfolio.id, loan.external_loan_id
        )
        if selection is None or selection.selected is None:
            raise RuntimeError("Succeeded rescue is missing its selected vendor")
        selected = selection.selected
        expected = (
            portfolio.id,
            loan.external_loan_id,
            selected.id,
            selected.vendor_name,
            selected.appointment_at,
            selected.price_cents,
            selected.service_type,
            loan.address,
        )
        actual = (
            payload.portfolio_id,
            payload.external_loan_id,
            payload.vendor_option_id,
            payload.vendor_name,
            payload.appointment_at,
            payload.price_cents,
            payload.service_type,
            payload.property_address,
        )
        if actual != expected:
            raise RuntimeError("Succeeded rescue payload does not match the selected vendor")
        before = await self.repository.get_exposure_estimate(
            portfolio.id, loan.external_loan_id, "before_rescue"
        )
        if before is None:
            raise RuntimeError("Succeeded rescue is missing its exposure estimate")
        after = await self.repository.get_exposure_estimate(
            portfolio.id, loan.external_loan_id, "after_rescue"
        )
        if after is None:
            after = self.exposure.estimate(
                delay_consequence_cents=before.delay_consequence_cents,
                delay_probability_bps=before.residual_probability_bps,
                residual_probability_bps=before.residual_probability_bps,
                intervention_cost_cents=before.intervention_cost_cents,
                intervention_available=True,
            ).model_copy(
                update={
                    "id": self._stable_id(
                        "exposure_after", portfolio.id, loan.external_loan_id
                    ),
                    "created_at": action.updated_at,
                }
            )
            await self.repository.add_exposure_estimate(
                portfolio.id, loan.external_loan_id, "after_rescue", after
            )
        await self._persist_post_rescue_priorities(portfolio, loan, action)
        await self._story_event(
            action.case_id,
            "rescue.completed",
            "The approved inspection booking was recorded in simulation",
            {
                "portfolio_id": portfolio.id,
                "loan_id": loan.id,
                "external_loan_id": loan.external_loan_id,
                "vendor_option_id": selected.id,
                "booking": "simulated",
                "action_id": action.id,
                "exposure_id": after.id,
                "residual_exposure_cents": after.after_action_cents,
                "preventable_exposure_cents": after.preventable_cents,
                "story_order": 8,
            },
            action.updated_at,
        )

    async def _persist_post_rescue_priorities(
        self,
        portfolio: PortfolioSnapshot,
        loan: PortfolioLoan,
        action: ActionAttempt,
    ) -> None:
        initial_batch_id = self._stable_id("priority_batch", portfolio.id)
        initial = await self.repository.list_priority_assessments(
            portfolio.id, batch_id=initial_batch_id
        )
        if len(initial) != len(portfolio.loans):
            raise RuntimeError("Post-rescue ranking is missing its initial priority batch")
        signals: dict[str, PrioritySignals] = {}
        for assessment in initial:
            source_inputs = assessment.input_signals.source_inputs + (
                PrioritySourceInput(
                    name="reevaluation_version", value="post-rescue-v1"
                ),
            )
            updates: dict[str, object] = {"source_inputs": source_inputs}
            if assessment.external_loan_id == loan.external_loan_id:
                source_inputs += (
                    PrioritySourceInput(name="intervention_completed", value=True),
                    PrioritySourceInput(name="completed_action_id", value=action.id),
                )
                updates.update(
                    delay_probability_bps=(
                        assessment.residual_probability_after_intervention_bps
                    ),
                    residual_probability_after_intervention_bps=(
                        assessment.residual_probability_after_intervention_bps
                    ),
                    intervention_cost_cents=0,
                    intervention_available=False,
                    source_inputs=source_inputs,
                )
            signals[assessment.external_loan_id] = assessment.input_signals.model_copy(
                update=updates,
                deep=True,
            )
        ranked = self.priority.rank(
            portfolio.loans,
            as_of=portfolio.created_at.date(),
            signals=signals,
        )
        await self.repository.add_priority_assessments(
            portfolio.id,
            ranked,
            batch_id=self._stable_id(
                "priority_batch_after_rescue_v1", portfolio.id, action.id
            ),
        )

    def _derive_contradiction(
        self,
        portfolio: PortfolioSnapshot,
        loan: PortfolioLoan,
        view: CaseView,
        as_of: datetime,
    ) -> tuple[ContradictionFinding | None, tuple[str, str] | None]:
        seller = next(
            (
                claim
                for claim in loan.seller_claims
                if claim.field == "septic_replacement_year"
                and type(claim.value) is int
            ),
            None,
        )
        if seller is None:
            return None, (
                "unsupported_seller_claim",
                "The selected loan has no supported seller replacement-year claim.",
            )
        seller_claim = NormalizedClaim(
            id=self._stable_id("claim", portfolio.id, loan.id, "seller"),
            field=seller.field,
            value=seller.value,
            truth_class=TruthClass.SYNTHETIC,
            source_name="Seller submission",
            observed_at=as_of,
        )
        permit = next((item for item in view.evidence if item.kind == "septic_permit"), None)
        if permit is None or permit.status is EvidenceStatus.EVIDENCE_UNAVAILABLE:
            finding = self.contradictions.from_source_unavailable(
                seller_claim, "Delaware Open Data"
            ).model_copy(
                update={
                    "id": self._stable_id("contradiction", portfolio.id, loan.id),
                    "created_at": as_of,
                }
            )
            return finding, (
                "source_unavailable",
                "Delaware permit evidence is unavailable; manual review is required.",
            )
        if permit.status is EvidenceStatus.RECORD_NOT_FOUND:
            finding = self.contradictions.from_not_found(seller_claim).model_copy(
                update={
                    "id": self._stable_id("contradiction", portfolio.id, loan.id),
                    "created_at": as_of,
                }
            )
            return finding, (
                "permit_not_found",
                "No Delaware permit record corroborates the seller claim.",
            )
        permit_year = self._permit_year(permit.payload)
        citation_ids = tuple(citation.id for citation in permit.citations)
        if permit_year is None or not citation_ids:
            return None, (
                "permit_value_missing",
                "Delaware permit evidence lacks a cited replacement-year value.",
            )
        external_claim = NormalizedClaim(
            id=self._stable_id("claim", portfolio.id, loan.id, "delaware"),
            field="septic_replacement_year",
            value=permit_year,
            truth_class=TruthClass.EXTERNAL_CITED,
            source_name=permit.source,
            citation_ids=citation_ids,
            observed_at=permit.retrieved_at,
        )
        finding = self.contradictions.compare(seller_claim, external_claim)
        if finding is None:
            return None, (
                "no_direct_contradiction",
                "The cited permit date does not contradict the seller claim.",
            )
        return (
            finding.model_copy(
                update={
                    "id": self._stable_id("contradiction", portfolio.id, loan.id),
                    "created_at": as_of,
                }
            ),
            None,
        )

    async def _persist_base_story(
        self,
        case_id: str,
        *,
        portfolio: PortfolioSnapshot,
        batch_id: str,
        investigation_id: str,
        selected_loan: PortfolioLoan,
        source_events: Iterable[AuditEvent],
        as_of: datetime,
    ) -> None:
        await self._story_event(
            case_id,
            "portfolio.scanned",
            f"{len(portfolio.loans)} closing "
            f"{'loan was' if len(portfolio.loans) == 1 else 'loans were'} ranked",
            {
                "portfolio_id": portfolio.id,
                "priority_batch_id": batch_id,
                "loan_ids": [loan.id for loan in portfolio.loans],
                "loan_count": len(portfolio.loans),
                "story_order": 0,
            },
            as_of,
        )
        await self._story_event(
            case_id,
            "portfolio.case_selected",
            "The priority engine selected the highest-ranked loan",
            {
                "portfolio_id": portfolio.id,
                "loan_id": selected_loan.id,
                "external_loan_id": selected_loan.external_loan_id,
                "investigation_id": investigation_id,
                "story_order": 1,
            },
            as_of,
        )
        evidence_order = 2
        for event in source_events:
            if event.event_type != "source.completed":
                continue
            await self._story_event(
                case_id,
                "evidence.completed",
                event.message,
                {
                    "portfolio_id": portfolio.id,
                    "loan_id": selected_loan.id,
                    "source_event_id": event.id,
                    "source": event.data.get("source"),
                    "evidence_ids": event.data.get("evidence_ids", []),
                    "story_order": evidence_order,
                },
                as_of,
            )
            evidence_order += 1

    async def _story_event(
        self,
        case_id: str,
        event_type: str,
        message: str,
        data: dict[str, Any],
        created_at: datetime,
    ) -> None:
        event_id = self._stable_id(
            "evt_story", case_id, event_type, str(data.get("source", ""))
        )
        view = await self.repository.get_view(case_id)
        if any(event.id == event_id for event in view.events):
            return
        await self.repository.add_event(
            AuditEvent(
                id=event_id,
                case_id=case_id,
                event_type=event_type,
                message=message,
                data={**data, "chapter": CHAPTER_BY_EVENT[event_type]},
                created_at=created_at,
            )
        )

    async def _persist_recovery(
        self,
        view: CaseView,
        portfolio: PortfolioSnapshot,
        loan: PortfolioLoan,
        investigation: PortfolioInvestigation,
        *,
        code: str,
        reason: str,
        as_of: datetime,
        contradiction: ContradictionFinding | None = None,
    ) -> None:
        if self._active_recovery(view) is not None:
            return
        recovery_count = sum(
            event.event_type == RECOVERY_EVENT for event in view.events
        )
        await self.repository.add_event(
            AuditEvent(
                id=self._stable_id(
                    "evt_recovery", view.case.id, code, str(recovery_count)
                ),
                case_id=view.case.id,
                event_type=RECOVERY_EVENT,
                message="Closing Rescue stopped safely",
                data={
                    "reason_code": code,
                    "reason": reason,
                    "portfolio_id": portfolio.id,
                    "loan_id": loan.id,
                    "investigation_id": investigation.id,
                    "contradiction_id": contradiction.id if contradiction else None,
                },
                created_at=as_of,
            )
        )

    async def _reconstruct(
        self, portfolio: PortfolioSnapshot, *, approval_token: str | None = None
    ) -> ClosingRescueResult:
        assessments = tuple(await self.repository.list_priority_assessments(portfolio.id))
        investigation = await self.repository.get_investigation(portfolio.id)
        if investigation is None:
            raise RuntimeError("terminal workflow is missing its investigation")
        selected_loan = self._selected_loan(portfolio, investigation)
        case = await self.repository.get_case_by_idempotency(
            self._case_key(portfolio, selected_loan)
        )
        if case is None:
            raise RuntimeError("terminal workflow is missing its case")
        view = await self.case_service.get_view(case.id)
        recovery_event = self._active_recovery(view)
        proposed = next(
            (event for event in view.events if event.event_type == "rescue.proposed"), None
        )
        if recovery_event is None and proposed is None:
            raise RuntimeError("workflow does not have a persisted terminal outcome")
        findings = await self.repository.list_contradictions(
            portfolio.id, selected_loan.external_loan_id
        )
        selection = await self.repository.get_latest_vendor_selection(
            portfolio.id, selected_loan.external_loan_id
        )
        estimate = await self.repository.get_exposure_estimate(
            portfolio.id, selected_loan.external_loan_id, "after_rescue"
        ) or await self.repository.get_exposure_estimate(
            portfolio.id, selected_loan.external_loan_id, "before_rescue"
        )
        story = tuple(
            sorted(
                (
                    StoryEvent(
                        id=event.id,
                        case_id=event.case_id,
                        event_type=event.event_type,
                        chapter=event.data["chapter"],
                        message=event.message,
                        data=self._frozen_data(event.data),
                        created_at=event.created_at,
                    )
                    for event in view.events
                    if event.event_type in CHAPTER_BY_EVENT
                    and "chapter" in event.data
                ),
                key=lambda event: int(
                    next(
                        item.value_json
                        for item in event.data
                        if item.key == "story_order"
                    )
                ),
            )
        )
        reason = recovery_event.data["reason"] if recovery_event else None
        return ClosingRescueResult(
            status="manual_review" if recovery_event else "complete",
            reason=reason,
            portfolio=self._project_portfolio(portfolio),
            assessments=assessments,
            selected_loan=self._project_loan(selected_loan),
            investigation=investigation,
            case=self._project_case(view),
            contradiction=findings[-1] if findings else None,
            vendor_selection=selection,
            exposure=estimate,
            approval_token=None if recovery_event else approval_token,
            story_events=story,
        )

    @classmethod
    def _project_portfolio(
        cls, portfolio: PortfolioSnapshot
    ) -> ClosingPortfolioProjection:
        return ClosingPortfolioProjection(
            id=portfolio.id,
            idempotency_key=portfolio.idempotency_key,
            loans=tuple(cls._project_loan(loan) for loan in portfolio.loans),
            created_at=portfolio.created_at,
            truth_class=portfolio.truth_class,
        )

    @classmethod
    def _project_loan(cls, loan: PortfolioLoan) -> ClosingLoanProjection:
        return ClosingLoanProjection(
            id=loan.id,
            external_loan_id=loan.external_loan_id,
            address=loan.address,
            loan_amount_cents=loan.loan_amount_cents,
            closing_date=loan.closing_date,
            rate_lock_daily_cost_cents=loan.rate_lock_daily_cost_cents,
            expected_extension_days=loan.expected_extension_days,
            rescheduling_cost_cents=loan.rescheduling_cost_cents,
            staff_cost_cents=loan.staff_cost_cents,
            seller_claims_json=cls._canonical_json(loan.seller_claims),
            approved_vendors=tuple(loan.approved_vendors),
            fixture_scenario=loan.fixture_scenario,
            truth_class=loan.truth_class,
            delay_consequence_cents=loan.delay_consequence_cents,
        )

    @classmethod
    def _project_case(cls, view: CaseView) -> ClosingCaseProjection:
        case = view.case
        return ClosingCaseProjection(
            case=ClosingCaseRecordProjection(
                id=case.id,
                external_case_id=case.external_case_id,
                address=case.address,
                closing_date=case.closing_date,
                approved_vendors=tuple(case.approved_vendors),
                approver_identity=case.approver_identity,
                fixture_scenario=case.fixture_scenario,
                state=case.state,
                disposition=case.disposition,
                created_at=case.created_at,
                updated_at=case.updated_at,
            ),
            evidence=tuple(
                ClosingEvidenceProjection(
                    id=item.id,
                    case_id=item.case_id,
                    source=item.source,
                    kind=item.kind,
                    status=item.status,
                    retrieved_at=item.retrieved_at,
                    confidence=item.confidence,
                    payload_json=cls._canonical_json(item.payload),
                    citations=tuple(
                        ClosingCitationProjection(
                            id=citation.id,
                            source_name=citation.source_name,
                            source_url=(
                                str(citation.source_url)
                                if citation.source_url is not None
                                else None
                            ),
                            retrieved_at=citation.retrieved_at,
                            published_at=citation.published_at,
                            confidence=citation.confidence,
                            label=citation.label,
                        )
                        for citation in item.citations
                    ),
                    request_id=item.request_id,
                    error_code=item.error_code,
                    error_message=item.error_message,
                    raw_json=cls._canonical_json(item.raw),
                )
                for item in view.evidence
            ),
            decisions=tuple(
                ClosingDecisionProjection(
                    id=item.id,
                    case_id=item.case_id,
                    created_at=item.created_at,
                    evidence_ids=tuple(item.evidence_ids),
                    disposition=item.result.disposition,
                    reasoner=item.reasoner,
                    result_json=cls._canonical_json(item.result),
                )
                for item in view.decisions
            ),
            approvals=tuple(
                ClosingApprovalProjection(
                    id=item.id,
                    case_id=item.case_id,
                    decision_id=item.decision_id,
                    action_kind=item.action_kind,
                    draft_json=cls._canonical_json(item.draft),
                    approver_identity=item.approver_identity,
                    state=item.state,
                    created_at=item.created_at,
                    decided_at=item.decided_at,
                )
                for item in view.approvals
            ),
            actions=tuple(
                ClosingActionProjection(
                    id=item.id,
                    case_id=item.case_id,
                    approval_id=item.approval_id,
                    kind=item.kind,
                    state=item.state,
                    payload_json=cls._canonical_json(item.payload),
                    result_json=cls._canonical_json(item.result),
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                )
                for item in view.actions
            ),
            events=tuple(
                ClosingAuditProjection(
                    id=item.id,
                    case_id=item.case_id,
                    event_type=item.event_type,
                    message=item.message,
                    data_json=cls._canonical_json(item.data),
                    created_at=item.created_at,
                )
                for item in view.events
            ),
            memo=view.memo,
        )

    @classmethod
    def _frozen_data(cls, data: dict[str, Any]) -> tuple[FrozenDataItem, ...]:
        return tuple(
            FrozenDataItem(key=key, value_json=cls._canonical_json(value))
            for key, value in sorted(data.items())
        )

    @staticmethod
    def _canonical_json(value: Any) -> str:
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        elif isinstance(value, list):
            value = [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in value
            ]
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @asynccontextmanager
    async def _workflow_lock(self, idempotency_key: str):
        """Serialize one DB/key saga across processes using an advisory file lock."""
        lock_path = self._lock_path(idempotency_key)
        handle = await asyncio.to_thread(self._open_lock_file, lock_path)
        acquired = False
        try:
            while not acquired:
                try:
                    fcntl.flock(
                        handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
                    )
                    acquired = True
                except BlockingIOError:
                    await asyncio.sleep(0.02)
            yield
        finally:
            if acquired:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            await asyncio.to_thread(handle.close)

    def _lock_path(self, idempotency_key: str) -> Path:
        db_path = self.repository.db_path.resolve()
        digest = sha256(f"{db_path}\x1f{idempotency_key}".encode()).hexdigest()
        return db_path.parent / f".closing-rescue-{digest}.lock"

    @staticmethod
    def _open_lock_file(path: Path) -> IO[str]:
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.open("a+", encoding="utf-8")

    async def _move_to_manual_if_allowed(self, case_id: str) -> None:
        case = await self.repository.get_case(case_id)
        if case.state in {
            CaseState.REASONING,
            CaseState.RESOLVING,
            CaseState.COLLECTING,
            CaseState.WAITING_FOR_APPROVAL,
        }:
            await self.repository.transition_case(case_id, CaseState.MANUAL_REVIEW)

    @staticmethod
    def _terminal_event(view: CaseView) -> AuditEvent | None:
        recovery = ClosingRescueService._active_recovery(view)
        if recovery is not None:
            return recovery
        return next(
            (event for event in view.events if event.event_type == "rescue.proposed"),
            None,
        )

    @staticmethod
    def _active_recovery(view: CaseView) -> AuditEvent | None:
        cleared_ids = {
            event.data.get("recovery_event_id")
            for event in view.events
            if event.event_type == "closing_rescue.recovery_cleared"
        }
        return next(
            (
                event
                for event in reversed(view.events)
                if event.event_type == RECOVERY_EVENT and event.id not in cleared_ids
            ),
            None,
        )

    @staticmethod
    def _latest_cleared_recovery(view: CaseView) -> AuditEvent | None:
        recoveries = {
            event.id: event for event in view.events if event.event_type == RECOVERY_EVENT
        }
        return next(
            (
                recoveries.get(event.data.get("recovery_event_id"))
                for event in reversed(view.events)
                if event.event_type == "closing_rescue.recovery_cleared"
            ),
            None,
        )

    @staticmethod
    def _finding_recovery(finding: ContradictionFinding) -> tuple[str, str]:
        if finding.kind is ContradictionKind.SOURCE_UNAVAILABLE:
            return (
                "source_unavailable",
                "Delaware permit evidence is unavailable; manual review is required.",
            )
        if finding.kind is ContradictionKind.MISSING_CORROBORATION:
            return (
                "permit_not_found",
                "No Delaware permit record corroborates the seller claim.",
            )
        return ("unsupported_contradiction", finding.summary)

    @staticmethod
    def _selected_loan(
        portfolio: PortfolioSnapshot, investigation: PortfolioInvestigation
    ) -> PortfolioLoan:
        return next(
            loan
            for loan in portfolio.loans
            if loan.external_loan_id == investigation.external_loan_id
        )

    @staticmethod
    def _case_key(portfolio: PortfolioSnapshot, loan: PortfolioLoan) -> str:
        return f"closing-rescue:{portfolio.id}:{loan.external_loan_id}"

    def _case_create(
        self, portfolio: PortfolioSnapshot, loan: PortfolioLoan
    ) -> CaseCreate:
        return CaseCreate(
            external_case_id=loan.external_loan_id,
            address=loan.address,
            closing_date=loan.closing_date,
            approved_vendors=loan.approved_vendors,
            approver_identity="closing-rescue-demo-approver@example.test",
            idempotency_key=self._case_key(portfolio, loan),
            fixture_scenario="inspect",
        )

    @staticmethod
    def _permit_year(payload: dict[str, Any]) -> int | None:
        permits = payload.get("permits")
        if not isinstance(permits, list) or not permits:
            return None
        received = permits[0].get("appreceiveddate")
        if not isinstance(received, str):
            return None
        try:
            return int(received[:4])
        except ValueError:
            return None

    @staticmethod
    def _stable_id(prefix: str, *parts: str) -> str:
        return f"{prefix}_{sha256(chr(31).join(parts).encode()).hexdigest()}"
