"""Shared domain vocabulary and case-state transition policy."""

from __future__ import annotations

from enum import StrEnum


class CaseState(StrEnum):
    RECEIVED = "received"
    RESOLVING = "resolving"
    COLLECTING = "collecting"
    REASONING = "reasoning"
    WAITING_FOR_CLARIFICATION = "waiting_for_clarification"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    ACTION_IN_PROGRESS = "action_in_progress"
    MONITORING = "monitoring"
    RESOLVED = "resolved"
    MANUAL_REVIEW = "manual_review"


class Disposition(StrEnum):
    CLEAR = "clear"
    INVESTIGATE = "investigate"
    INSPECT = "inspect"


class EvidenceStatus(StrEnum):
    SUCCESS = "success"
    RECORD_NOT_FOUND = "record_not_found"
    AMBIGUOUS = "ambiguous"
    EVIDENCE_UNAVAILABLE = "evidence_unavailable"
    STALE = "stale"
    MALFORMED = "malformed"


class ApprovalState(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONSUMED = "consumed"


class ActionState(StrEnum):
    DRAFTED = "drafted"
    AUTHORIZED = "authorized"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ActionKind(StrEnum):
    COUNTY_RECORD_REQUEST = "county_record_request"
    INSPECTION_ORDER = "inspection_order"


ALLOWED_TRANSITIONS: dict[CaseState, frozenset[CaseState]] = {
    CaseState.RECEIVED: frozenset({CaseState.RESOLVING}),
    CaseState.RESOLVING: frozenset(
        {
            CaseState.COLLECTING,
            CaseState.WAITING_FOR_CLARIFICATION,
            CaseState.MANUAL_REVIEW,
        }
    ),
    CaseState.COLLECTING: frozenset({CaseState.REASONING, CaseState.MANUAL_REVIEW}),
    CaseState.REASONING: frozenset(
        {
            CaseState.WAITING_FOR_APPROVAL,
            CaseState.WAITING_FOR_CLARIFICATION,
            CaseState.RESOLVED,
            CaseState.MANUAL_REVIEW,
        }
    ),
    CaseState.WAITING_FOR_CLARIFICATION: frozenset({CaseState.RESOLVING, CaseState.MANUAL_REVIEW}),
    CaseState.WAITING_FOR_APPROVAL: frozenset(
        {CaseState.ACTION_IN_PROGRESS, CaseState.MONITORING, CaseState.MANUAL_REVIEW}
    ),
    CaseState.ACTION_IN_PROGRESS: frozenset({CaseState.MONITORING, CaseState.MANUAL_REVIEW}),
    CaseState.MONITORING: frozenset(
        {CaseState.COLLECTING, CaseState.REASONING, CaseState.RESOLVED, CaseState.MANUAL_REVIEW}
    ),
    CaseState.RESOLVED: frozenset({CaseState.COLLECTING}),
    CaseState.MANUAL_REVIEW: frozenset(
        {CaseState.RESOLVING, CaseState.COLLECTING, CaseState.REASONING}
    ),
}


class InvalidTransitionError(ValueError):
    """Raised when a case state transition violates the workflow."""


def require_transition(current: CaseState, target: CaseState) -> None:
    """Validate a transition or raise a domain-specific error."""
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransitionError(f"Case cannot transition from {current} to {target}")
