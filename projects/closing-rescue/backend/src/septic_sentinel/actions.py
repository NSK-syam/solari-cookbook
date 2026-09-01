"""Human approval and idempotent simulated external actions."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
)

from septic_sentinel.domain import (
    ActionKind,
    ActionState,
    ApprovalState,
    CaseState,
    Disposition,
)
from septic_sentinel.models import (
    ActionAttempt,
    ApprovalRequest,
    AuditEvent,
    CaseRecord,
    DecisionSnapshot,
    TruthClass,
)
from septic_sentinel.repository import RepositoryConflictError, SQLiteRepository


class ApprovalTokenError(PermissionError):
    pass


class ApprovalConflictError(RuntimeError):
    pass


class ApprovalDraft(BaseModel):
    approval: ApprovalRequest
    approval_token: str | None


class RescueActionPayload(BaseModel):
    """Validated synthetic booking details authorized by one rescue approval."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    portfolio_id: StrictStr = Field(min_length=1)
    external_loan_id: StrictStr = Field(min_length=1)
    vendor_option_id: StrictStr = Field(min_length=1)
    vendor_name: StrictStr = Field(min_length=1)
    appointment_at: AwareDatetime
    price_cents: StrictInt = Field(ge=0)
    service_type: StrictStr = Field(min_length=1)
    property_address: StrictStr = Field(min_length=1)
    truth_class: Literal[TruthClass.SYNTHETIC] = TruthClass.SYNTHETIC

    @field_validator(
        "portfolio_id",
        "external_loan_id",
        "vendor_option_id",
        "vendor_name",
        "service_type",
        "property_address",
    )
    @classmethod
    def semantic_strings_must_be_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Rescue action strings must not be blank")
        return value

    @field_validator("appointment_at")
    @classmethod
    def appointment_is_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class ActionService:
    def __init__(self, repository: SQLiteRepository, approval_recovery_key: str) -> None:
        self.repository = repository
        self._approval_recovery_hash = _hash_token(approval_recovery_key)

    async def draft(self, case: CaseRecord, decision: DecisionSnapshot) -> ApprovalDraft | None:
        if decision.result.disposition == Disposition.CLEAR:
            return None
        kind = (
            ActionKind.COUNTY_RECORD_REQUEST
            if decision.result.disposition == Disposition.INVESTIGATE
            else ActionKind.INSPECTION_ORDER
        )
        token = secrets.token_urlsafe(32)
        token_hash = _hash_token(token)
        draft = self._draft_payload(case, kind)
        approval = ApprovalRequest(
            case_id=case.id,
            decision_id=decision.id,
            action_kind=kind,
            draft=draft,
            approver_identity=case.approver_identity,
            token_hash=token_hash,
            idempotency_key=f"{decision.id}:{kind}",
        )
        stored, created = await self.repository.add_approval(approval)
        if created:
            await self.repository.add_event(
                AuditEvent(
                    case_id=case.id,
                    event_type="approval.requested",
                    message=f"Human approval is required for {kind.value}",
                    data={"approval_id": stored.id, "action_kind": kind},
                )
            )
        return ApprovalDraft(approval=stored, approval_token=token if created else None)

    async def rotate_pending_token(
        self,
        approval_id: str,
        approver_identity: str,
        recovery_credential: str,
    ) -> str:
        """Replace a pending approval credential and return it exactly once."""
        if not secrets.compare_digest(
            self._approval_recovery_hash, _hash_token(recovery_credential)
        ):
            raise ApprovalTokenError("Approval recovery credential is invalid")
        approval = await self.repository.get_approval(approval_id)
        if approval.approver_identity != approver_identity:
            raise ApprovalTokenError("Approver identity does not match the case")
        if approval.state is not ApprovalState.PENDING:
            raise ApprovalConflictError(
                f"Approval token cannot be rotated from {approval.state}"
            )
        token = secrets.token_urlsafe(32)
        rotated = approval.model_copy(update={"token_hash": _hash_token(token)})
        try:
            await self.repository.compare_and_swap_approval(
                approval,
                rotated,
                AuditEvent(
                    case_id=approval.case_id,
                    event_type="approval.token_rotated",
                    message="Pending approval credential was rotated",
                    data={"approval_id": approval.id},
                ),
            )
        except RepositoryConflictError as exc:
            raise ApprovalConflictError("Approval changed during token rotation") from exc
        return token

    async def decide(
        self,
        approval_id: str,
        *,
        approver_identity: str,
        token: str,
        approve: bool,
        simulate_timeout: bool = False,
    ) -> ActionAttempt | None:
        approval = await self.repository.get_approval(approval_id)
        if approval.approver_identity != approver_identity:
            raise ApprovalTokenError("Approver identity does not match the case")
        if not secrets.compare_digest(approval.token_hash, _hash_token(token)):
            raise ApprovalTokenError("Approval token is invalid")

        existing_action = await self.repository.get_action_by_approval(approval.id)
        if approval.state is ApprovalState.REJECTED:
            if approve:
                raise ApprovalConflictError(
                    "Decision conflicts with the previously rejected approval"
                )
            await self._ensure_monitoring(approval.case_id)
            return None
        if approval.state is ApprovalState.CONSUMED:
            if not approve:
                raise ApprovalConflictError(
                    "Decision conflicts with the previously consumed approval"
                )
            await self._ensure_monitoring(approval.case_id)
            return existing_action
        if approval.state not in {ApprovalState.PENDING, ApprovalState.APPROVED}:
            raise ApprovalConflictError(f"Approval is already {approval.state}")
        if approval.state is ApprovalState.APPROVED and not approve:
            raise ApprovalConflictError(
                "Decision conflicts with the previously approved decision"
            )

        now = datetime.now(UTC)
        if not approve:
            rejected = approval.model_copy(
                update={"state": ApprovalState.REJECTED, "decided_at": now}
            )
            try:
                await self.repository.compare_and_swap_approval(
                    approval,
                    rejected,
                    AuditEvent(
                        case_id=approval.case_id,
                        event_type="approval.rejected",
                        message="The proposed external action was rejected",
                        data={"approval_id": approval.id},
                    ),
                )
            except RepositoryConflictError as exc:
                raise ApprovalConflictError("Approval changed during rejection") from exc
            await self._ensure_monitoring(approval.case_id)
            return None

        approved = approval
        if approval.state is ApprovalState.PENDING:
            approved = approval.model_copy(
                update={"state": ApprovalState.APPROVED, "decided_at": now}
            )
            try:
                await self.repository.compare_and_swap_approval(
                    approval,
                    approved,
                    AuditEvent(
                        case_id=approval.case_id,
                        event_type="approval.approved",
                        message="The proposed external action was approved",
                        data={"approval_id": approval.id},
                    ),
                )
            except RepositoryConflictError as exc:
                raise ApprovalConflictError("Approval changed during approval") from exc
        await self._ensure_action_in_progress(approval.case_id)
        action = existing_action
        if action is None:
            action, _ = await self.repository.add_action(
                ActionAttempt(
                    case_id=approval.case_id,
                    approval_id=approval.id,
                    kind=approval.action_kind,
                    state=ActionState.AUTHORIZED,
                    idempotency_key=f"action:{approval.id}",
                    payload=approval.draft,
                )
            )

        if action.state is ActionState.AUTHORIZED:
            result = (
                {"delivery": "unknown", "requires_reconciliation": True}
                if simulate_timeout
                else {
                    "delivery": "simulated",
                    "message": "No external message was sent and no charge was incurred.",
                }
            )
            final_state = ActionState.UNKNOWN if simulate_timeout else ActionState.SUCCEEDED
            action = action.model_copy(
                update={
                    "state": final_state,
                    "result": result,
                    "updated_at": datetime.now(UTC),
                }
            )
            await self.repository.update_action(action)

        stored_approval = await self.repository.get_approval(approval.id)
        if stored_approval.state is ApprovalState.APPROVED:
            consumed = stored_approval.model_copy(update={"state": ApprovalState.CONSUMED})
            try:
                await self.repository.compare_and_swap_approval(
                    stored_approval,
                    consumed,
                    AuditEvent(
                        case_id=approval.case_id,
                        event_type=(
                            "action.unknown"
                            if action.state is ActionState.UNKNOWN
                            else "action.completed"
                        ),
                        message=(
                            "Action result is unknown and must be reconciled before retry"
                            if action.state is ActionState.UNKNOWN
                            else "Simulated action completed"
                        ),
                        data={"action_id": action.id, "state": action.state},
                    ),
                )
            except RepositoryConflictError as exc:
                raise ApprovalConflictError("Approval changed during consumption") from exc
        await self._ensure_monitoring(approval.case_id)
        return action

    async def replace_pending_draft(
        self, approval_id: str, payload: BaseModel
    ) -> ApprovalRequest:
        """Atomically attach a validated domain payload to a pending approval."""
        approval = await self.repository.get_approval(approval_id)
        draft = payload.model_dump(mode="json")
        if approval.draft == draft:
            return approval
        if approval.state is not ApprovalState.PENDING:
            raise ApprovalConflictError(
                f"Approval draft cannot change from {approval.state}"
            )
        updated = approval.model_copy(update={"draft": draft})
        try:
            return await self.repository.compare_and_swap_approval(
                approval,
                updated,
                AuditEvent(
                    case_id=approval.case_id,
                    event_type="approval.draft_updated",
                    message="Approval draft was bound to validated rescue details",
                    data={"approval_id": approval.id},
                ),
            )
        except RepositoryConflictError as exc:
            raise ApprovalConflictError("Approval changed during draft update") from exc

    async def _ensure_action_in_progress(self, case_id: str) -> None:
        case = await self.repository.get_case(case_id)
        if case.state is CaseState.WAITING_FOR_APPROVAL:
            await self.repository.transition_case(case_id, CaseState.ACTION_IN_PROGRESS)
        elif case.state not in {CaseState.ACTION_IN_PROGRESS, CaseState.MONITORING}:
            raise ApprovalConflictError(f"Case cannot execute action from {case.state}")

    async def _ensure_monitoring(self, case_id: str) -> None:
        case = await self.repository.get_case(case_id)
        if case.state in {CaseState.WAITING_FOR_APPROVAL, CaseState.ACTION_IN_PROGRESS}:
            await self.repository.transition_case(case_id, CaseState.MONITORING)
        elif case.state is not CaseState.MONITORING:
            raise ApprovalConflictError(f"Case cannot reconcile approval from {case.state}")

    @staticmethod
    def _draft_payload(case: CaseRecord, kind: ActionKind) -> dict[str, str]:
        if kind == ActionKind.COUNTY_RECORD_REQUEST:
            return {
                "recipient": "Delaware permitting authority (simulated)",
                "subject": f"Septic permit record request — {case.external_case_id}",
                "body": (
                    "Please provide available onsite wastewater permit records for "
                    f"{case.address}. "
                    "This draft will not be sent without approval."
                ),
            }
        vendor = case.approved_vendors[0] if case.approved_vendors else "Approved vendor"
        return {
            "recipient": f"{vendor} (simulated)",
            "subject": f"Inspection request — {case.external_case_id}",
            "body": (
                "Please propose an onsite septic inspection before "
                f"{case.closing_date.isoformat()} "
                f"for {case.address}. This draft will not be sent without approval."
            ),
        }


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
