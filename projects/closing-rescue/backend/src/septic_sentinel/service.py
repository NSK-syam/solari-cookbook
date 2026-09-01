"""Application service composing collection, reasoning, approvals, and memos."""

from __future__ import annotations

from pydantic import BaseModel

from septic_sentinel.actions import ActionService, ApprovalDraft
from septic_sentinel.domain import CaseState, Disposition
from septic_sentinel.memo import render_memo
from septic_sentinel.models import AuditEvent, CaseCreate, CaseView, DecisionSnapshot, Evidence
from septic_sentinel.orchestrator import EvidenceCollector
from septic_sentinel.reasoner import ReasoningEngine, ReasoningFailure
from septic_sentinel.repository import SQLiteRepository


class ProcessedCase(BaseModel):
    view: CaseView
    created: bool
    approval_token: str | None = None


class SepticSentinelService:
    def __init__(
        self,
        repository: SQLiteRepository,
        collector: EvidenceCollector,
        reasoner: ReasoningEngine,
        actions: ActionService,
    ) -> None:
        self.repository = repository
        self.collector = collector
        self.reasoner = reasoner
        self.actions = actions

    async def ingest(self, request: CaseCreate) -> ProcessedCase:
        collected = await self.create_and_collect(request)
        if not collected.created or collected.view.case.state != CaseState.REASONING:
            return collected
        return await self.decide_existing(collected.view.case.id, created=True)

    async def create_and_collect(self, request: CaseCreate) -> ProcessedCase:
        """Create and collect a case without reasoning or drafting an approval."""
        case, created = await self.repository.create_case(request)
        if not created:
            return ProcessedCase(view=await self.get_view(case.id), created=False)
        return await self.collect_existing(case.id, created=True)

    async def collect_existing(
        self, case_id: str, *, created: bool = False
    ) -> ProcessedCase:
        """Collect a persisted RECEIVED case, supporting safe saga resumption."""
        case = await self.repository.get_case(case_id)
        if case.state != CaseState.RECEIVED:
            raise ValueError(f"Case cannot collect from {case.state}")
        view = await self.repository.get_view(case_id)
        if not any(event.event_type == "case.created" for event in view.events):
            await self.repository.add_event(
                AuditEvent(
                    case_id=case.id,
                    event_type="case.created",
                    message="Lender case received",
                    data={"external_case_id": case.external_case_id},
                )
            )
        await self.collector.collect(case)
        return ProcessedCase(view=await self.get_view(case.id), created=created)

    async def decide_existing(
        self, case_id: str, *, created: bool = False
    ) -> ProcessedCase:
        """Reason over a collected case and draft approval when policy requires it."""
        current = await self.repository.get_case(case_id)
        if current.state != CaseState.REASONING:
            raise ValueError(f"Case cannot decide from {current.state}")
        approval = await self._decide(case_id)
        return ProcessedCase(
            view=await self.get_view(case_id),
            created=created,
            approval_token=approval.approval_token if approval else None,
        )

    async def reevaluate(self, case_id: str) -> ProcessedCase:
        case = await self.repository.get_case(case_id)
        if case.state == CaseState.MONITORING:
            await self.repository.transition_case(case.id, CaseState.REASONING)
        elif case.state == CaseState.RESOLVED:
            await self.repository.transition_case(case.id, CaseState.COLLECTING)
            await self.repository.transition_case(case.id, CaseState.REASONING)
        elif case.state != CaseState.REASONING:
            raise ValueError(f"Case cannot be re-evaluated from {case.state}")
        return await self.decide_existing(case.id)

    async def add_manual_evidence(self, case_id: str, item: Evidence) -> ProcessedCase:
        if item.case_id != case_id:
            raise ValueError("Evidence case_id does not match the route")
        await self.repository.add_evidence(item)
        await self.repository.add_event(
            AuditEvent(
                case_id=case_id,
                event_type="evidence.added",
                message=f"New {item.kind} evidence was added",
                data={"evidence_id": item.id, "source": item.source},
            )
        )
        return await self.reevaluate(case_id)

    async def _decide(self, case_id: str) -> ApprovalDraft | None:
        case = await self.repository.get_case(case_id)
        view = await self.repository.get_view(case_id)
        try:
            decision = await self.reasoner.reason(case_id, case.closing_date, view.evidence)
        except ReasoningFailure as exc:
            await self.repository.transition_case(case_id, CaseState.MANUAL_REVIEW)
            await self.repository.add_event(
                AuditEvent(
                    case_id=case_id,
                    event_type="reasoning.failed",
                    message="Structured reasoning failed; case moved to manual review",
                    data={"error": type(exc).__name__},
                )
            )
            return None
        await self.repository.add_decision(decision)
        await self.repository.add_event(
            AuditEvent(
                case_id=case_id,
                event_type="decision.created",
                message=f"Agent disposition: {decision.result.disposition.value}",
                data={"decision_id": decision.id, "disposition": decision.result.disposition},
            )
        )
        if decision.result.disposition == Disposition.CLEAR:
            await self.repository.transition_case(
                case_id, CaseState.RESOLVED, decision.result.disposition
            )
            return None
        await self.repository.transition_case(
            case_id, CaseState.WAITING_FOR_APPROVAL, decision.result.disposition
        )
        return await self.actions.draft(case, decision)

    async def get_view(self, case_id: str) -> CaseView:
        view = await self.repository.get_view(case_id)
        if view.decisions:
            decision: DecisionSnapshot = view.decisions[-1]
            view.memo = render_memo(view.case, decision, view.evidence)
        return view
