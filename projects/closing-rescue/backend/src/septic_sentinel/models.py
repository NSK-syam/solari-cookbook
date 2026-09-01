"""Validated contracts shared by persistence, orchestration, API, and UI."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StrictBool,
    StrictInt,
    StrictStr,
    computed_field,
    field_validator,
    model_validator,
)

from septic_sentinel.domain import (
    ActionKind,
    ActionState,
    ApprovalState,
    CaseState,
    Disposition,
    EvidenceStatus,
)
from septic_sentinel.exposure_math import calculate_exposure_values
from septic_sentinel.vendor_rules import (
    VendorReasonCode,
    normalize_approved_names,
    vendor_option_order_key,
    vendor_rejection_reasons,
)


def utc_now() -> datetime:
    return datetime.now(UTC)


class TruthClass(StrEnum):
    EXTERNAL_CITED = "external_cited"
    SYNTHETIC = "synthetic"


class ExposureEstimate(BaseModel):
    """Immutable snapshot of the transparent closing-exposure formula."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str = Field(default_factory=lambda: f"exposure_{uuid4().hex}", min_length=1)
    truth_class: Literal[TruthClass.SYNTHETIC] = TruthClass.SYNTHETIC
    delay_consequence_cents: StrictInt = Field(ge=0)
    delay_probability_bps: StrictInt = Field(ge=0, le=10_000)
    residual_probability_bps: StrictInt = Field(ge=0, le=10_000)
    intervention_cost_cents: StrictInt = Field(ge=0)
    intervention_available: StrictBool = True
    without_action_cents: StrictInt = Field(ge=0)
    after_action_cents: StrictInt = Field(ge=0)
    preventable_cents: StrictInt = Field(ge=0)
    formula_version: Literal["closing-exposure-2026-08-05"] = "closing-exposure-2026-08-05"
    limitations: tuple[str, ...] = (
        "Estimate uses supplied probabilities and costs; it is not a guarantee.",
    )
    created_at: AwareDatetime = Field(default_factory=utc_now)

    @field_validator("id", "formula_version", mode="before")
    @classmethod
    def exposure_semantic_strings_must_be_nonblank(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("Semantic strings must not be blank")
        return value

    @field_validator("limitations")
    @classmethod
    def exposure_limitations_must_be_nonblank(
        cls, limitations: tuple[str, ...]
    ) -> tuple[str, ...]:
        limitations = tuple(item.strip() for item in limitations)
        if not limitations or any(not item for item in limitations):
            raise ValueError("Limitations must not be empty or blank")
        return limitations

    @field_validator("created_at")
    @classmethod
    def exposure_created_at_is_utc(cls, created_at: datetime) -> datetime:
        return created_at.astimezone(UTC)

    @model_validator(mode="after")
    def derived_exposure_outputs_must_match_formula(self) -> ExposureEstimate:
        expected = calculate_exposure_values(
            self.delay_consequence_cents,
            self.delay_probability_bps,
            self.residual_probability_bps,
            self.intervention_cost_cents,
            self.intervention_available,
        )
        actual = (
            self.without_action_cents,
            self.after_action_cents,
            self.preventable_cents,
        )
        if actual != expected:
            raise ValueError("derived exposure outputs do not match formula inputs")
        return self


class VendorOption(BaseModel):
    """A synthetic vendor availability observation; never a booking."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str = Field(default_factory=lambda: f"vendor_option_{uuid4().hex}", min_length=1)
    vendor_name: str = Field(min_length=1)
    appointment_at: AwareDatetime
    price_cents: StrictInt = Field(ge=0)
    service_type: str = Field(min_length=1)
    approved: StrictBool
    qualified: StrictBool
    available_as_of: AwareDatetime
    truth_class: Literal[TruthClass.SYNTHETIC] = TruthClass.SYNTHETIC

    @field_validator("id", "vendor_name", "service_type", mode="before")
    @classmethod
    def vendor_semantic_strings_must_be_nonblank(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("Semantic strings must not be blank")
        return value

    @field_validator("appointment_at", "available_as_of")
    @classmethod
    def vendor_datetimes_are_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class VendorConsideration(BaseModel):
    """One immutable option and every deterministic reason it was rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    option: VendorOption
    rejection_reason_codes: tuple[VendorReasonCode, ...] = ()


class VendorSelection(BaseModel):
    """Auditable scouting result that does not reserve or mutate an option."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    selected: VendorOption | None
    considered: tuple[VendorConsideration, ...]
    approved_names: tuple[str, ...]
    cutoff: AwareDatetime
    evaluated_at: AwareDatetime
    selected_at: AwareDatetime
    truth_class: Literal[TruthClass.SYNTHETIC] = TruthClass.SYNTHETIC

    @field_validator("approved_names", mode="before")
    @classmethod
    def approved_names_are_normalized(cls, value: object) -> object:
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise ValueError("approved_names must be a collection of names")
        return normalize_approved_names(value)

    @field_validator("cutoff", "evaluated_at", "selected_at")
    @classmethod
    def selection_datetimes_are_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def selection_audit_must_be_internally_consistent(self) -> VendorSelection:
        option_ids = [item.option.id for item in self.considered]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("considered vendor option IDs must be unique")

        canonical = tuple(
            sorted(
                self.considered,
                key=lambda item: vendor_option_order_key(
                    appointment_at=item.option.appointment_at,
                    price_cents=item.option.price_cents,
                    vendor_name=item.option.vendor_name,
                    option_id=item.option.id,
                ),
            )
        )
        if self.considered != canonical:
            raise ValueError("considered vendor options must use canonical ordering")

        viable: list[VendorOption] = []
        for item in self.considered:
            expected_reasons = vendor_rejection_reasons(
                vendor_name=item.option.vendor_name,
                approved=item.option.approved,
                qualified=item.option.qualified,
                appointment_at=item.option.appointment_at,
                available_as_of=item.option.available_as_of,
                approved_names=self.approved_names,
                cutoff=self.cutoff,
                as_of=self.evaluated_at,
            )
            if item.rejection_reason_codes != expected_reasons:
                raise ValueError("vendor rejection reason codes do not match policy")
            if not expected_reasons:
                viable.append(item.option)

        expected_selected = viable[0] if viable else None
        if self.selected != expected_selected:
            raise ValueError("selected vendor must be the first canonical viable option")
        return self


class ContradictionKind(StrEnum):
    DIRECT = "direct"
    MISSING_CORROBORATION = "missing_corroboration"
    SOURCE_UNAVAILABLE = "source_unavailable"
    UNSUPPORTED = "unsupported"


class NormalizedClaim(BaseModel):
    """A scalar claim with explicit provenance for deterministic comparison."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str = Field(default_factory=lambda: f"claim_{uuid4().hex}", min_length=1)
    field: str = Field(min_length=1)
    value: StrictStr | StrictInt | StrictBool
    truth_class: TruthClass
    source_name: str = Field(min_length=1)
    citation_ids: tuple[str, ...] = ()
    observed_at: AwareDatetime = Field(default_factory=utc_now)

    @field_validator("id", "field", "source_name", mode="before")
    @classmethod
    def semantic_strings_must_be_nonblank(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("Semantic strings must not be blank")
        return value

    @field_validator("citation_ids")
    @classmethod
    def citation_ids_must_be_nonblank(cls, citation_ids: tuple[str, ...]) -> tuple[str, ...]:
        citation_ids = tuple(citation_id.strip() for citation_id in citation_ids)
        if any(not citation_id for citation_id in citation_ids):
            raise ValueError("Citation IDs must not be blank")
        return citation_ids

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_normalized_to_utc(cls, observed_at: datetime) -> datetime:
        return observed_at.astimezone(UTC)

    @model_validator(mode="after")
    def external_claim_requires_citation(self) -> NormalizedClaim:
        if self.truth_class is TruthClass.EXTERNAL_CITED and not self.citation_ids:
            raise ValueError("External cited claims require at least one citation ID")
        return self


class ContradictionFinding(BaseModel):
    """An immutable output from a versioned deterministic comparison rule."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str = Field(default_factory=lambda: f"contradiction_{uuid4().hex}", min_length=1)
    kind: ContradictionKind
    claim_ids: tuple[str, ...] = Field(min_length=1)
    citation_ids: tuple[str, ...] = ()
    source_names: tuple[str, ...] = Field(min_length=1)
    summary: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    rule_version: Literal["contradiction-rules-v1"] = "contradiction-rules-v1"
    created_at: AwareDatetime = Field(default_factory=utc_now)

    @field_validator("id", "summary", "rule_id", "rule_version", mode="before")
    @classmethod
    def semantic_strings_must_be_nonblank(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("Semantic strings must not be blank")
        return value

    @field_validator("claim_ids", "citation_ids", "source_names")
    @classmethod
    def audit_tuple_items_must_be_valid(
        cls, values: tuple[str, ...], info: Any
    ) -> tuple[str, ...]:
        values = tuple(value.strip() for value in values)
        if any(not value for value in values):
            raise ValueError("Audit tuple values must not be blank")
        if info.field_name in {"claim_ids", "source_names"} and len(set(values)) != len(values):
            raise ValueError(f"{info.field_name} values must be unique")
        return values

    @field_validator("created_at")
    @classmethod
    def created_at_is_normalized_to_utc(cls, created_at: datetime) -> datetime:
        return created_at.astimezone(UTC)


class SellerClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1)
    value: str | int | float | bool | None
    truth_class: Literal[TruthClass.SYNTHETIC] = TruthClass.SYNTHETIC


class PortfolioLoan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: f"loan_{uuid4().hex}")
    external_loan_id: str = Field(min_length=1)
    address: str = Field(min_length=1)
    loan_amount_cents: int = Field(strict=True, gt=0)
    closing_date: date
    rate_lock_daily_cost_cents: int = Field(strict=True, ge=0)
    expected_extension_days: int = Field(strict=True, ge=0)
    rescheduling_cost_cents: int = Field(strict=True, ge=0)
    staff_cost_cents: int = Field(strict=True, ge=0)
    seller_claims: list[SellerClaim] = Field(default_factory=list)
    approved_vendors: list[str] = Field(default_factory=list)
    fixture_scenario: str
    truth_class: Literal[TruthClass.SYNTHETIC] = TruthClass.SYNTHETIC

    @computed_field
    @property
    def delay_consequence_cents(self) -> int:
        return (
            self.rate_lock_daily_cost_cents * self.expected_extension_days
            + self.rescheduling_cost_cents
            + self.staff_cost_cents
        )


class PrioritySourceInput(BaseModel):
    """One immutable source value retained in the priority audit snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    value: str | int | bool


class PrioritySignals(BaseModel):
    """Explicit integer inputs used by deterministic priority scoring."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    delay_probability_bps: int = Field(strict=True, ge=0, le=10_000)
    residual_probability_after_intervention_bps: int = Field(
        strict=True, ge=0, le=10_000
    )
    intervention_cost_cents: int = Field(strict=True, ge=0)
    intervention_available: bool = Field(strict=True)
    evidence_completeness_bps: int = Field(strict=True, ge=0, le=10_000)
    contradiction_score: int = Field(strict=True, ge=0, le=100)
    uncertainty_score: int = Field(strict=True, ge=0, le=100)
    source_failed: bool = Field(strict=True)
    source_inputs: tuple[PrioritySourceInput, ...] = ()


class PriorityAssessment(BaseModel):
    """Auditable output containing every priority formula component."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    external_loan_id: str = Field(min_length=1)
    days_to_close: int = Field(strict=True, ge=0)
    urgency_score: int = Field(strict=True, ge=0, le=100)
    delay_consequence_cents: int = Field(strict=True, ge=0)
    delay_probability_bps: int = Field(strict=True, ge=0, le=10_000)
    residual_probability_after_intervention_bps: int = Field(
        strict=True, ge=0, le=10_000
    )
    intervention_cost_cents: int = Field(strict=True, ge=0)
    intervention_available: bool = Field(strict=True)
    exposure_without_intervention_cents: int = Field(strict=True, ge=0)
    exposure_after_intervention_cents: int = Field(strict=True, ge=0)
    preventable_exposure_cents: int = Field(strict=True, ge=0)
    evidence_completeness_bps: int = Field(strict=True, ge=0, le=10_000)
    contradiction_score: int = Field(strict=True, ge=0, le=100)
    uncertainty_score: int = Field(strict=True, ge=0, le=100)
    source_failed: bool = Field(strict=True)
    source_inputs: tuple[PrioritySourceInput, ...]
    input_signals: PrioritySignals
    effective_signals: PrioritySignals
    formula_version: Literal["priority-v1"] = "priority-v1"
    scenario_profile_version: Literal["closing-rescue-scenarios-v1"] | None = None
    selection_explanation: str = Field(min_length=1)


class PortfolioSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: f"portfolio_{uuid4().hex}")
    idempotency_key: str
    loans: list[PortfolioLoan]
    created_at: datetime = Field(default_factory=utc_now)
    truth_class: Literal[TruthClass.SYNTHETIC] = TruthClass.SYNTHETIC


class PortfolioCreateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio: PortfolioSnapshot
    created: bool


class PortfolioInvestigation(BaseModel):
    """Immutable record of the one loan selected for portfolio investigation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: StrictStr = Field(min_length=1)
    portfolio_id: StrictStr = Field(min_length=1)
    external_loan_id: StrictStr = Field(min_length=1)
    created_at: AwareDatetime = Field(default_factory=utc_now)

    @field_validator("id", "portfolio_id", "external_loan_id", mode="before")
    @classmethod
    def investigation_strings_must_be_nonblank(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("Semantic strings must not be blank")
        return value

    @field_validator("created_at")
    @classmethod
    def investigation_created_at_is_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class Citation(BaseModel):
    id: str = Field(default_factory=lambda: f"cit_{uuid4().hex}")
    source_name: str = Field(min_length=1)
    source_url: HttpUrl | None = None
    retrieved_at: datetime = Field(default_factory=utc_now)
    published_at: datetime | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    label: str | None = None


class Evidence(BaseModel):
    id: str = Field(default_factory=lambda: f"ev_{uuid4().hex}")
    case_id: str
    source: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    status: EvidenceStatus
    retrieved_at: datetime = Field(default_factory=utc_now)
    confidence: float | None = Field(default=None, ge=0, le=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    citations: list[Citation] = Field(default_factory=list, validate_default=True)
    request_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    raw: dict[str, Any] | list[Any] | str | None = None

    @field_validator("citations")
    @classmethod
    def successful_evidence_requires_citation(
        cls, citations: list[Citation], info: Any
    ) -> list[Citation]:
        status = info.data.get("status")
        if status == EvidenceStatus.SUCCESS and not citations:
            raise ValueError("Successful evidence must include at least one citation")
        return citations


class ObservedFact(BaseModel):
    statement: str = Field(min_length=1)
    citation_ids: list[str] = Field(min_length=1)


class Inference(BaseModel):
    statement: str = Field(min_length=1)
    based_on_fact_indexes: list[int] = Field(default_factory=list)


class DecisionResult(BaseModel):
    disposition: Disposition
    observed_facts: list[ObservedFact]
    inferences: list[Inference]
    missing_evidence: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    recommended_action: str
    confidence: float = Field(ge=0, le=1)


class DecisionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: f"dec_{uuid4().hex}")
    case_id: str
    created_at: datetime = Field(default_factory=utc_now)
    evidence_ids: tuple[str, ...]
    result: DecisionResult
    reasoner: str
    policy_version: str = "2026-08-05"


class CaseCreate(BaseModel):
    external_case_id: str = Field(min_length=1, max_length=100)
    address: str = Field(min_length=8, max_length=256)
    closing_date: date
    approved_vendors: list[str] = Field(default_factory=list)
    approver_identity: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=8, max_length=200)
    fixture_scenario: str | None = None


class CaseRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"case_{uuid4().hex}")
    external_case_id: str
    address: str
    closing_date: date
    approved_vendors: list[str]
    approver_identity: str
    idempotency_key: str
    fixture_scenario: str | None = None
    state: CaseState = CaseState.RECEIVED
    disposition: Disposition | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ApprovalRequest(BaseModel):
    id: str = Field(default_factory=lambda: f"apr_{uuid4().hex}")
    case_id: str
    decision_id: str
    action_kind: ActionKind
    draft: dict[str, Any]
    approver_identity: str
    token_hash: str
    idempotency_key: str
    state: ApprovalState = ApprovalState.PENDING
    created_at: datetime = Field(default_factory=utc_now)
    decided_at: datetime | None = None


class ActionAttempt(BaseModel):
    id: str = Field(default_factory=lambda: f"act_{uuid4().hex}")
    case_id: str
    approval_id: str
    kind: ActionKind
    state: ActionState = ActionState.DRAFTED
    idempotency_key: str
    payload: dict[str, Any]
    result: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AuditEvent(BaseModel):
    id: str = Field(default_factory=lambda: f"evt_{uuid4().hex}")
    case_id: str
    event_type: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class CaseView(BaseModel):
    case: CaseRecord
    evidence: list[Evidence]
    decisions: list[DecisionSnapshot]
    approvals: list[ApprovalRequest]
    actions: list[ActionAttempt]
    events: list[AuditEvent]
    memo: str | None = None


class FrozenDataItem(BaseModel):
    """One immutable structured key/value represented by canonical JSON."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    key: StrictStr = Field(min_length=1)
    value_json: StrictStr = Field(min_length=1)


class ClosingLoanProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: StrictStr
    external_loan_id: StrictStr
    address: StrictStr
    loan_amount_cents: StrictInt
    closing_date: date
    rate_lock_daily_cost_cents: StrictInt
    expected_extension_days: StrictInt
    rescheduling_cost_cents: StrictInt
    staff_cost_cents: StrictInt
    seller_claims_json: StrictStr
    approved_vendors: tuple[StrictStr, ...]
    fixture_scenario: StrictStr
    truth_class: TruthClass
    delay_consequence_cents: StrictInt


class ClosingPortfolioProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: StrictStr
    idempotency_key: StrictStr
    loans: tuple[ClosingLoanProjection, ...]
    created_at: AwareDatetime
    truth_class: TruthClass


class ClosingCitationProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: StrictStr
    source_name: StrictStr
    source_url: StrictStr | None
    retrieved_at: AwareDatetime
    published_at: AwareDatetime | None
    confidence: float | None
    label: StrictStr | None


class ClosingEvidenceProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: StrictStr
    case_id: StrictStr
    source: StrictStr
    kind: StrictStr
    status: EvidenceStatus
    retrieved_at: AwareDatetime
    confidence: float | None
    payload_json: StrictStr
    citations: tuple[ClosingCitationProjection, ...]
    request_id: StrictStr | None
    error_code: StrictStr | None
    error_message: StrictStr | None
    raw_json: StrictStr
    truth_class: Literal[TruthClass.EXTERNAL_CITED] = TruthClass.EXTERNAL_CITED


class ClosingDecisionProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: StrictStr
    case_id: StrictStr
    created_at: AwareDatetime
    evidence_ids: tuple[StrictStr, ...]
    disposition: Disposition
    reasoner: StrictStr
    result_json: StrictStr


class ClosingApprovalProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: StrictStr
    case_id: StrictStr
    decision_id: StrictStr
    action_kind: ActionKind
    draft_json: StrictStr
    approver_identity: StrictStr = Field(
        description=(
            "Demo-only self-asserted display metadata; this is not an authenticated identity."
        )
    )
    state: ApprovalState
    created_at: AwareDatetime
    decided_at: AwareDatetime | None


class ClosingActionProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: StrictStr
    case_id: StrictStr
    approval_id: StrictStr
    kind: ActionKind
    state: ActionState
    payload_json: StrictStr
    result_json: StrictStr
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ClosingAuditProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: StrictStr
    case_id: StrictStr
    event_type: StrictStr
    message: StrictStr
    data_json: StrictStr
    created_at: AwareDatetime


class ClosingCaseRecordProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: StrictStr
    external_case_id: StrictStr
    address: StrictStr
    closing_date: date
    approved_vendors: tuple[StrictStr, ...]
    approver_identity: StrictStr
    fixture_scenario: StrictStr | None
    state: CaseState
    disposition: Disposition | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ClosingCaseProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    case: ClosingCaseRecordProjection
    evidence: tuple[ClosingEvidenceProjection, ...]
    decisions: tuple[ClosingDecisionProjection, ...]
    approvals: tuple[ClosingApprovalProjection, ...]
    actions: tuple[ClosingActionProjection, ...]
    events: tuple[ClosingAuditProjection, ...]
    memo: StrictStr | None


class StoryEvent(BaseModel):
    """One deeply immutable, persisted chapter event projection."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: StrictStr = Field(min_length=1)
    case_id: StrictStr = Field(min_length=1)
    event_type: StrictStr = Field(min_length=1)
    chapter: StrictInt = Field(ge=1, le=6)
    message: StrictStr = Field(min_length=1)
    data: tuple[FrozenDataItem, ...]
    created_at: AwareDatetime

    @field_validator("id", "case_id", "event_type", "message", mode="before")
    @classmethod
    def story_strings_must_be_nonblank(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("Story event strings must not be blank")
        return value

    @field_validator("created_at")
    @classmethod
    def story_created_at_is_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def chapter_matches_persisted_data(self) -> StoryEvent:
        chapter = next(
            (item.value_json for item in self.data if item.key == "chapter"), None
        )
        if chapter != str(self.chapter):
            raise ValueError("Story chapter must match persisted event data")
        return self


class ClosingRescueResult(BaseModel):
    """Strict immutable read snapshot for one persisted competition demo."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    status: Literal["complete", "recoverable", "manual_review"]
    reason: StrictStr | None = None
    portfolio: ClosingPortfolioProjection
    assessments: tuple[PriorityAssessment, ...]
    selected_loan: ClosingLoanProjection
    investigation: PortfolioInvestigation
    case: ClosingCaseProjection
    contradiction: ContradictionFinding | None = None
    vendor_selection: VendorSelection | None = None
    exposure: ExposureEstimate | None = None
    approval_token: StrictStr | None = None
    story_events: tuple[StoryEvent, ...]

    @model_validator(mode="after")
    def completion_requires_all_rescue_artifacts(self) -> ClosingRescueResult:
        if self.status == "complete":
            if self.reason is not None:
                raise ValueError("Complete results cannot carry a recovery reason")
            if any(
                item is None
                for item in (self.contradiction, self.vendor_selection, self.exposure)
            ):
                raise ValueError("Complete results require all rescue artifacts")
            if self.vendor_selection.selected is None:
                raise ValueError("Complete results require a selected vendor")
        elif not self.reason or not self.reason.strip():
            raise ValueError("Non-complete results require a reason")
        return self


class ClosingPortfolioSummary(BaseModel):
    """Small, truth-labelled portfolio totals for the opening story chapter."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    loan_count: StrictInt = Field(ge=1)
    pipeline_value_cents: StrictInt = Field(ge=0)
    attention_candidate_count: StrictInt = Field(ge=0)
    total_estimated_exposure_cents: StrictInt = Field(ge=0)
    truth_class: Literal[TruthClass.SYNTHETIC] = TruthClass.SYNTHETIC


class ClosingPriorityView(BaseModel):
    """Names both immutable ranking batches so post-action state is unambiguous."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    initial_batch_id: StrictStr = Field(min_length=1)
    current_batch_id: StrictStr = Field(min_length=1)
    initial: tuple[PriorityAssessment, ...] = Field(min_length=1)
    current: tuple[PriorityAssessment, ...] = Field(min_length=1)
    truth_class: Literal[TruthClass.SYNTHETIC] = TruthClass.SYNTHETIC


class ClosingClaimView(BaseModel):
    """Normalized API claim; cited external values retain their source links."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: StrictStr = Field(min_length=1)
    field: StrictStr = Field(min_length=1)
    value: StrictStr | StrictInt | float | StrictBool | None
    truth_class: TruthClass
    source_name: StrictStr = Field(min_length=1)
    observed_at: AwareDatetime
    citation_ids: tuple[StrictStr, ...] = ()

    @model_validator(mode="after")
    def external_claims_are_cited(self) -> ClosingClaimView:
        if self.truth_class is TruthClass.EXTERNAL_CITED and not self.citation_ids:
            raise ValueError("External cited claims require citation IDs")
        return self


class ClosingRescueView(BaseModel):
    """One coherent, deeply immutable frontend snapshot of the investigation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    portfolio_id: StrictStr = Field(min_length=1)
    status: Literal["complete", "recoverable", "manual_review"]
    reason: StrictStr | None = None
    portfolio_summary: ClosingPortfolioSummary
    selected_case: ClosingLoanProjection
    priority: ClosingPriorityView
    case_state: CaseState
    current_chapter: StrictInt = Field(ge=1, le=6)
    evidence: tuple[ClosingEvidenceProjection, ...]
    seller_claim: ClosingClaimView | None = None
    permit_claim: ClosingClaimView | None = None
    contradiction: ContradictionFinding | None = None
    exposure: ExposureEstimate | None = None
    proposed_rescue: VendorSelection | None = None
    approval: ClosingApprovalProjection | None = None
    actions: tuple[ClosingActionProjection, ...]
    story_events: tuple[StoryEvent, ...]
    approval_token: StrictStr | None = None


class ClosingRescueApprovalRequest(BaseModel):
    """One-time demo decision; token possession is required but is not user auth."""

    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=1, max_length=200)
    approver_identity: str = Field(
        min_length=1,
        max_length=160,
        description=(
            "Self-asserted demo display metadata matched to the draft; "
            "not an authenticated identity."
        ),
    )
    approval_token: str = Field(min_length=1, max_length=512)
    approve: StrictBool
    simulate_timeout: StrictBool = False

    @field_validator("approval_id", "approver_identity", "approval_token")
    @classmethod
    def approval_strings_are_nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Approval fields must not be blank")
        return value
