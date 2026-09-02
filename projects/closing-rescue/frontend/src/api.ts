export type TruthClass = "synthetic" | "external_cited";
export type CaseState = "received" | "resolving" | "collecting" | "reasoning" | "waiting_for_clarification" | "waiting_for_approval" | "action_in_progress" | "monitoring" | "resolved" | "manual_review";
export type ApprovalState = "not_required" | "pending" | "approved" | "rejected" | "consumed";
export type ActionState = "drafted" | "authorized" | "running" | "succeeded" | "failed" | "unknown";
export type EvidenceStatus = "success" | "record_not_found" | "ambiguous" | "evidence_unavailable" | "stale" | "malformed";
export type ContradictionKind = "direct" | "missing_corroboration" | "source_unavailable" | "unsupported";
export type ActionKind = "county_record_request" | "inspection_order";
export type VendorReasonCode = "name_not_approved" | "not_approved" | "not_qualified" | "appointment_expired" | "appointment_after_cutoff" | "availability_observation_after_as_of";

export interface FrozenDataItem { key: string; value_json: string }
export interface StoryEvent { id: string; case_id: string; event_type: string; chapter: number; message: string; data: FrozenDataItem[]; created_at: string }
export interface PortfolioSummary { loan_count: number; pipeline_value_cents: number; attention_candidate_count: number; total_estimated_exposure_cents: number; truth_class: "synthetic" }
export interface ClosingLoan { id: string; external_loan_id: string; address: string; loan_amount_cents: number; closing_date: string; rate_lock_daily_cost_cents: number; expected_extension_days: number; rescheduling_cost_cents: number; staff_cost_cents: number; seller_claims_json: string; approved_vendors: string[]; fixture_scenario: string; truth_class: TruthClass; delay_consequence_cents: number }
export interface PrioritySourceInput { name: string; value: string | number | boolean }
export interface PrioritySignals { delay_probability_bps: number; residual_probability_after_intervention_bps: number; intervention_cost_cents: number; intervention_available: boolean; evidence_completeness_bps: number; contradiction_score: number; uncertainty_score: number; source_failed: boolean; source_inputs: PrioritySourceInput[] }
export interface PriorityAssessment {
  external_loan_id: string;
  days_to_close: number;
  urgency_score: number;
  delay_consequence_cents: number;
  delay_probability_bps: number;
  residual_probability_after_intervention_bps: number;
  intervention_cost_cents: number;
  intervention_available: boolean;
  exposure_without_intervention_cents: number;
  exposure_after_intervention_cents: number;
  preventable_exposure_cents: number;
  evidence_completeness_bps: number;
  contradiction_score: number;
  uncertainty_score: number;
  source_failed: boolean;
  source_inputs: PrioritySourceInput[];
  input_signals: PrioritySignals;
  effective_signals: PrioritySignals;
  formula_version: "priority-v1";
  scenario_profile_version: "closing-rescue-scenarios-v1" | null;
  selection_explanation: string;
}
export interface PriorityView { initial_batch_id: string; current_batch_id: string; initial: PriorityAssessment[]; current: PriorityAssessment[]; truth_class: "synthetic" }
export interface Citation { id: string; source_name: string; source_url: string | null; retrieved_at: string; published_at: string | null; confidence: number | null; label: string | null }
export interface ClosingEvidence { id: string; case_id: string; source: string; kind: string; status: EvidenceStatus; retrieved_at: string; confidence: number | null; payload_json: string; citations: Citation[]; request_id: string | null; error_code: string | null; error_message: string | null; raw_json: string; truth_class: "external_cited" }
export interface ClaimView { id: string; field: string; value: string | number | boolean | null; truth_class: TruthClass; source_name: string; observed_at: string; citation_ids: string[] }
export interface ContradictionFinding { id: string; kind: ContradictionKind; claim_ids: string[]; citation_ids: string[]; source_names: string[]; summary: string; rule_id: string; rule_version: "contradiction-rules-v1"; created_at: string }
export interface ExposureEstimate { id: string; truth_class: "synthetic"; delay_consequence_cents: number; delay_probability_bps: number; residual_probability_bps: number; intervention_cost_cents: number; intervention_available: boolean; without_action_cents: number; after_action_cents: number; preventable_cents: number; formula_version: "closing-exposure-2026-08-05"; limitations: string[]; created_at: string }
export interface VendorOption { id: string; vendor_name: string; appointment_at: string; price_cents: number; service_type: string; approved: boolean; qualified: boolean; available_as_of: string; truth_class: "synthetic" }
export interface VendorSelection { selected: VendorOption | null; considered: Array<{ option: VendorOption; rejection_reason_codes: VendorReasonCode[] }>; approved_names: string[]; cutoff: string; evaluated_at: string; selected_at: string; truth_class: "synthetic" }
export interface ApprovalProjection { id: string; case_id: string; decision_id: string; action_kind: ActionKind; draft_json: string; approver_identity: string; state: ApprovalState; created_at: string; decided_at: string | null }
export interface ActionProjection { id: string; case_id: string; approval_id: string; kind: ActionKind; state: ActionState; payload_json: string; result_json: string; created_at: string; updated_at: string }

export interface ClosingRescueView {
  portfolio_id: string;
  status: "complete" | "recoverable" | "manual_review";
  reason: string | null;
  portfolio_summary: PortfolioSummary;
  selected_case: ClosingLoan;
  priority: PriorityView;
  case_state: CaseState;
  current_chapter: number;
  evidence: ClosingEvidence[];
  seller_claim: ClaimView | null;
  permit_claim: ClaimView | null;
  contradiction: ContradictionFinding | null;
  exposure: ExposureEstimate | null;
  proposed_rescue: VendorSelection | null;
  approval: ApprovalProjection | null;
  actions: ActionProjection[];
  story_events: StoryEvent[];
  approval_token: string | null;
}

export type SolariStepStatus = "pending" | "running" | "succeeded" | "failed" | "blocked";
export type SolariExecutionStatus = "running" | "awaiting_approval" | "succeeded" | "partial_failure" | "failed";
export interface SolariArtifact { kind: "manifest" | "citation" | "screenshot" | "replay" | "receipt"; label: string; url: string | null; sha256: string | null; media_type: string | null }
export interface SolariStepReceipt { product: "sandbox" | "browser" | "desktop"; status: SolariStepStatus; session_id: string | null; detail: string; started_at: string | null; completed_at: string | null; artifacts: SolariArtifact[]; failure_reason: string | null }
export interface SolariExecutionView { portfolio_id: string; status: SolariExecutionStatus; steps: [SolariStepReceipt, SolariStepReceipt, SolariStepReceipt]; manifest_sha256: string | null; updated_at: string }

export interface PublicRecordCheckInput {
  identifier_type: "permit" | "parcel";
  identifier: string;
  claimed_year: number;
  closing_date: string;
  loan_amount_cents: number;
  daily_delay_cost_cents: number;
  expected_delay_days: number;
  inspection_cost_cents: number;
}
export interface PublicPermitRecord { permit_number: string; parcel_reference: string; application_received_date: string | null; permit_status: string | null; system_type: string | null; construction_type: string | null; county: string | null; official_detail_url: string | null }
export interface PublicExposureScenario { loan_amount_cents: number; daily_delay_cost_cents: number; expected_delay_days: number; inspection_cost_cents: number; without_action_cents: number; after_action_cents: number; preventable_cents: number; formula: string; truth_class: "user_supplied_scenario" }
export interface PublicRecordCheckResult { query_type: "permit" | "parcel"; query_value: string; comparison: "aligned" | "needs_review" | "record_not_found"; summary: string; claimed_year: number; official_record_year: number | null; closing_date: string; days_to_close: number; matching_record_count: number; record: PublicPermitRecord | null; exposure: PublicExposureScenario; dataset_url: string; retrieved_at: string; limitation: string }

export type ApiErrorKind = "validation" | "authentication" | "conflict" | "not_found" | "server_error" | "network" | "aborted";

export class ApiError extends Error {
  constructor(public readonly kind: ApiErrorKind, public readonly status: number | null, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const invalid = (): never => { throw new ApiError("server_error", null, "The server returned an invalid Closing Rescue snapshot."); };
const record = (value: unknown, keys: readonly string[]): Record<string, unknown> => {
  if (!isObject(value) || Object.keys(value).length !== keys.length || keys.some((key) => !(key in value))) return invalid();
  return value;
};
const textValue = (value: unknown): string => typeof value === "string" && value.trim() ? value : invalid();
const nullableText = (value: unknown): string | null => value === null ? null : textValue(value);
const integer = (value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): number => typeof value === "number" && Number.isSafeInteger(value) && value >= min && value <= max ? value : invalid();
const bool = (value: unknown): boolean => typeof value === "boolean" ? value : invalid();
const finite = (value: unknown): number => typeof value === "number" && Number.isFinite(value) ? value : invalid();
const oneOf = <T extends string>(value: unknown, values: readonly T[]): T => typeof value === "string" && values.includes(value as T) ? value as T : invalid();
const list = <T>(value: unknown, parse: (item: unknown) => T, nonempty = false): T[] => {
  if (!Array.isArray(value) || (nonempty && value.length === 0)) return invalid();
  return value.map(parse);
};
const timestamp = (value: unknown): string => {
  const result = textValue(value);
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-](\d{2}):(\d{2}))$/.exec(result);
  if (!match || Number.isNaN(Date.parse(result))) return invalid();
  const [year, month, day, hour, minute, second] = match.slice(1, 7).map(Number);
  const calendar = new Date(Date.UTC(year, month - 1, day));
  if (calendar.getUTCFullYear() !== year || calendar.getUTCMonth() !== month - 1 || calendar.getUTCDate() !== day || hour > 23 || minute > 59 || second > 59 || Number(match[7] ?? 0) > 23 || Number(match[8] ?? 0) > 59) return invalid();
  return result;
};
const dateValue = (value: unknown): string => {
  const result = textValue(value);
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(result);
  if (!match) return invalid();
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  if (date.toISOString().slice(0, 10) !== result) return invalid();
  return result;
};
const jsonText = (value: unknown): string => { const result = textValue(value); try { JSON.parse(result); } catch { return invalid(); } return result; };
const stringList = (value: unknown, nonempty = false): string[] => list(value, textValue, nonempty);

const TRUTH = ["synthetic", "external_cited"] as const;
const CASE_STATES = ["received", "resolving", "collecting", "reasoning", "waiting_for_clarification", "waiting_for_approval", "action_in_progress", "monitoring", "resolved", "manual_review"] as const;
const EVIDENCE_STATES = ["success", "record_not_found", "ambiguous", "evidence_unavailable", "stale", "malformed"] as const;
const APPROVAL_STATES = ["not_required", "pending", "approved", "rejected", "consumed"] as const;
const ACTION_STATES = ["drafted", "authorized", "running", "succeeded", "failed", "unknown"] as const;
const ACTION_KINDS = ["county_record_request", "inspection_order"] as const;
const CONTRADICTION_KINDS = ["direct", "missing_corroboration", "source_unavailable", "unsupported"] as const;
const VENDOR_REASONS = ["name_not_approved", "not_approved", "not_qualified", "appointment_expired", "appointment_after_cutoff", "availability_observation_after_as_of"] as const;

function validateSourceInput(value: unknown): void {
  const item = record(value, ["name", "value"]); textValue(item.name);
  if (!(typeof item.value === "string" || typeof item.value === "boolean" || (typeof item.value === "number" && Number.isSafeInteger(item.value)))) invalid();
}
function validateSignals(value: unknown): void {
  const item = record(value, ["delay_probability_bps", "residual_probability_after_intervention_bps", "intervention_cost_cents", "intervention_available", "evidence_completeness_bps", "contradiction_score", "uncertainty_score", "source_failed", "source_inputs"]);
  integer(item.delay_probability_bps, 0, 10000); integer(item.residual_probability_after_intervention_bps, 0, 10000); integer(item.intervention_cost_cents); bool(item.intervention_available); integer(item.evidence_completeness_bps, 0, 10000); integer(item.contradiction_score, 0, 100); integer(item.uncertainty_score, 0, 100); bool(item.source_failed); list(item.source_inputs, (entry) => validateSourceInput(entry));
}
function validateAssessment(value: unknown): void {
  const keys = ["external_loan_id", "days_to_close", "urgency_score", "delay_consequence_cents", "delay_probability_bps", "residual_probability_after_intervention_bps", "intervention_cost_cents", "intervention_available", "exposure_without_intervention_cents", "exposure_after_intervention_cents", "preventable_exposure_cents", "evidence_completeness_bps", "contradiction_score", "uncertainty_score", "source_failed", "source_inputs", "input_signals", "effective_signals", "formula_version", "scenario_profile_version", "selection_explanation"];
  const item = record(value, keys); textValue(item.external_loan_id); integer(item.days_to_close); integer(item.urgency_score, 0, 100); integer(item.delay_consequence_cents); integer(item.delay_probability_bps, 0, 10000); integer(item.residual_probability_after_intervention_bps, 0, 10000); integer(item.intervention_cost_cents); bool(item.intervention_available); integer(item.exposure_without_intervention_cents); integer(item.exposure_after_intervention_cents); integer(item.preventable_exposure_cents); integer(item.evidence_completeness_bps, 0, 10000); integer(item.contradiction_score, 0, 100); integer(item.uncertainty_score, 0, 100); bool(item.source_failed); list(item.source_inputs, (entry) => validateSourceInput(entry)); validateSignals(item.input_signals); validateSignals(item.effective_signals); oneOf(item.formula_version, ["priority-v1"]); if (item.scenario_profile_version !== null) oneOf(item.scenario_profile_version, ["closing-rescue-scenarios-v1"]); textValue(item.selection_explanation);
}
function validateStoryEvent(value: unknown): StoryEvent {
  const item = record(value, ["id", "case_id", "event_type", "chapter", "message", "data", "created_at"]); textValue(item.id); textValue(item.case_id); textValue(item.event_type); const chapter = integer(item.chapter, 1, 6); textValue(item.message); const data = list(item.data, (entry) => { const part = record(entry, ["key", "value_json"]); textValue(part.key); const encoded = textValue(part.value_json); try { JSON.parse(encoded); } catch { invalid(); } return part; }); timestamp(item.created_at);
  if (!data.some((part) => part.key === "chapter" && part.value_json === String(chapter))) invalid();
  return value as StoryEvent;
}
function validateCitation(value: unknown): void { const item = record(value, ["id", "source_name", "source_url", "retrieved_at", "published_at", "confidence", "label"]); textValue(item.id); textValue(item.source_name); const sourceUrl = nullableText(item.source_url); if (sourceUrl !== null) { let parsed: URL; try { parsed = new URL(sourceUrl); } catch { return invalid(); } if (parsed.protocol !== "http:" && parsed.protocol !== "https:") invalid(); } timestamp(item.retrieved_at); if (item.published_at !== null) timestamp(item.published_at); if (item.confidence !== null) finite(item.confidence); nullableText(item.label); }
function validateEvidence(value: unknown): void { const item = record(value, ["id", "case_id", "source", "kind", "status", "retrieved_at", "confidence", "payload_json", "citations", "request_id", "error_code", "error_message", "raw_json", "truth_class"]); textValue(item.id); textValue(item.case_id); textValue(item.source); textValue(item.kind); oneOf(item.status, EVIDENCE_STATES); timestamp(item.retrieved_at); if (item.confidence !== null) finite(item.confidence); jsonText(item.payload_json); list(item.citations, (entry) => validateCitation(entry)); nullableText(item.request_id); nullableText(item.error_code); nullableText(item.error_message); jsonText(item.raw_json); oneOf(item.truth_class, ["external_cited"]); }
function validateClaim(value: unknown): void { const item = record(value, ["id", "field", "value", "truth_class", "source_name", "observed_at", "citation_ids"]); textValue(item.id); textValue(item.field); if (!(item.value === null || typeof item.value === "string" || typeof item.value === "boolean" || typeof item.value === "number")) invalid(); const truth = oneOf(item.truth_class, TRUTH); textValue(item.source_name); timestamp(item.observed_at); const citations = stringList(item.citation_ids); if (truth === "external_cited" && citations.length === 0) invalid(); }
function validateContradiction(value: unknown): void { const item = record(value, ["id", "kind", "claim_ids", "citation_ids", "source_names", "summary", "rule_id", "rule_version", "created_at"]); textValue(item.id); oneOf(item.kind, CONTRADICTION_KINDS); stringList(item.claim_ids, true); stringList(item.citation_ids); stringList(item.source_names, true); textValue(item.summary); textValue(item.rule_id); oneOf(item.rule_version, ["contradiction-rules-v1"]); timestamp(item.created_at); }
function validateExposure(value: unknown): void { const item = record(value, ["id", "truth_class", "delay_consequence_cents", "delay_probability_bps", "residual_probability_bps", "intervention_cost_cents", "intervention_available", "without_action_cents", "after_action_cents", "preventable_cents", "formula_version", "limitations", "created_at"]); textValue(item.id); oneOf(item.truth_class, ["synthetic"]); integer(item.delay_consequence_cents); integer(item.delay_probability_bps, 0, 10000); integer(item.residual_probability_bps, 0, 10000); integer(item.intervention_cost_cents); bool(item.intervention_available); integer(item.without_action_cents); integer(item.after_action_cents); integer(item.preventable_cents); oneOf(item.formula_version, ["closing-exposure-2026-08-05"]); stringList(item.limitations, true); timestamp(item.created_at); }
function validateVendor(value: unknown): void { const item = record(value, ["id", "vendor_name", "appointment_at", "price_cents", "service_type", "approved", "qualified", "available_as_of", "truth_class"]); textValue(item.id); textValue(item.vendor_name); timestamp(item.appointment_at); integer(item.price_cents); textValue(item.service_type); bool(item.approved); bool(item.qualified); timestamp(item.available_as_of); oneOf(item.truth_class, ["synthetic"]); }
function validateVendorSelection(value: unknown): void { const item = record(value, ["selected", "considered", "approved_names", "cutoff", "evaluated_at", "selected_at", "truth_class"]); if (item.selected !== null) validateVendor(item.selected); list(item.considered, (entry) => { const considered = record(entry, ["option", "rejection_reason_codes"]); validateVendor(considered.option); list(considered.rejection_reason_codes, (reason) => oneOf(reason, VENDOR_REASONS)); }); stringList(item.approved_names); timestamp(item.cutoff); timestamp(item.evaluated_at); timestamp(item.selected_at); oneOf(item.truth_class, ["synthetic"]); }
function validateApproval(value: unknown): void { const item = record(value, ["id", "case_id", "decision_id", "action_kind", "draft_json", "approver_identity", "state", "created_at", "decided_at"]); textValue(item.id); textValue(item.case_id); textValue(item.decision_id); oneOf(item.action_kind, ACTION_KINDS); jsonText(item.draft_json); textValue(item.approver_identity); oneOf(item.state, APPROVAL_STATES); timestamp(item.created_at); if (item.decided_at !== null) timestamp(item.decided_at); }
function validateAction(value: unknown): void { const item = record(value, ["id", "case_id", "approval_id", "kind", "state", "payload_json", "result_json", "created_at", "updated_at"]); textValue(item.id); textValue(item.case_id); textValue(item.approval_id); oneOf(item.kind, ACTION_KINDS); oneOf(item.state, ACTION_STATES); jsonText(item.payload_json); jsonText(item.result_json); timestamp(item.created_at); timestamp(item.updated_at); }

/** Validate the coherent read-model boundary before application state sees it. */
export function parseClosingRescueView(payload: unknown): ClosingRescueView {
  const root = record(payload, ["portfolio_id", "status", "reason", "portfolio_summary", "selected_case", "priority", "case_state", "current_chapter", "evidence", "seller_claim", "permit_claim", "contradiction", "exposure", "proposed_rescue", "approval", "actions", "story_events", "approval_token"]);
  textValue(root.portfolio_id); oneOf(root.status, ["complete", "recoverable", "manual_review"]); nullableText(root.reason);
  const summary = record(root.portfolio_summary, ["loan_count", "pipeline_value_cents", "attention_candidate_count", "total_estimated_exposure_cents", "truth_class"]); integer(summary.loan_count, 1); integer(summary.pipeline_value_cents); integer(summary.attention_candidate_count); integer(summary.total_estimated_exposure_cents); oneOf(summary.truth_class, ["synthetic"]);
  const loan = record(root.selected_case, ["id", "external_loan_id", "address", "loan_amount_cents", "closing_date", "rate_lock_daily_cost_cents", "expected_extension_days", "rescheduling_cost_cents", "staff_cost_cents", "seller_claims_json", "approved_vendors", "fixture_scenario", "truth_class", "delay_consequence_cents"]); textValue(loan.id); textValue(loan.external_loan_id); textValue(loan.address); integer(loan.loan_amount_cents); dateValue(loan.closing_date); integer(loan.rate_lock_daily_cost_cents); integer(loan.expected_extension_days); integer(loan.rescheduling_cost_cents); integer(loan.staff_cost_cents); jsonText(loan.seller_claims_json); stringList(loan.approved_vendors); textValue(loan.fixture_scenario); oneOf(loan.truth_class, TRUTH); integer(loan.delay_consequence_cents);
  const priority = record(root.priority, ["initial_batch_id", "current_batch_id", "initial", "current", "truth_class"]); textValue(priority.initial_batch_id); textValue(priority.current_batch_id); list(priority.initial, (entry) => validateAssessment(entry), true); list(priority.current, (entry) => validateAssessment(entry), true); oneOf(priority.truth_class, ["synthetic"]);
  oneOf(root.case_state, CASE_STATES); const currentChapter = integer(root.current_chapter, 1, 6); list(root.evidence, (entry) => validateEvidence(entry)); if (root.seller_claim !== null) validateClaim(root.seller_claim); if (root.permit_claim !== null) validateClaim(root.permit_claim); if (root.contradiction !== null) validateContradiction(root.contradiction); if (root.exposure !== null) validateExposure(root.exposure); if (root.proposed_rescue !== null) validateVendorSelection(root.proposed_rescue); if (root.approval !== null) validateApproval(root.approval); list(root.actions, (entry) => validateAction(entry)); if (root.approval_token !== null) textValue(root.approval_token);
  const events = list(root.story_events, validateStoryEvent);
  const eventIds = new Set<string>();
  let persistedChapter = 1;
  let previousChapter = 1;
  for (const item of events) {
    if (item.chapter < previousChapter || eventIds.has(item.id)) invalid();
    eventIds.add(item.id);
    previousChapter = item.chapter;
    persistedChapter = Math.max(persistedChapter, item.chapter);
  }
  if (persistedChapter !== currentChapter) invalid();
  const parsed = payload as unknown as ClosingRescueView;
  const selectedId = parsed.selected_case.external_loan_id;
  if (parsed.priority.initial.filter((item) => item.external_loan_id === selectedId).length !== 1 || parsed.priority.current.filter((item) => item.external_loan_id === selectedId).length !== 1) invalid();
  const caseIds = new Set<string>([
    ...parsed.story_events.map((event) => event.case_id),
    ...parsed.evidence.map((evidence) => evidence.case_id),
    ...(parsed.approval ? [parsed.approval.case_id] : []),
    ...parsed.actions.map((action) => action.case_id)
  ]);
  if (caseIds.size > 1) invalid();
  if (parsed.actions.length && !parsed.approval) invalid();
  if (parsed.approval && parsed.actions.some((action) => action.approval_id !== parsed.approval?.id)) invalid();
  const citationIds = new Set(parsed.evidence.flatMap((evidence) => evidence.citations.map((citation) => citation.id)));
  const claims = [parsed.seller_claim, parsed.permit_claim].filter((claim): claim is ClaimView => claim !== null);
  if (claims.some((claim) => claim.citation_ids.some((id) => !citationIds.has(id)))) invalid();
  if (parsed.contradiction) {
    const claimIds = new Set(claims.map((claim) => claim.id));
    if (parsed.contradiction.claim_ids.some((id) => !claimIds.has(id)) || parsed.contradiction.citation_ids.some((id) => !citationIds.has(id))) invalid();
  }
  return parsed;
}

export function parseSolariExecution(payload: unknown): SolariExecutionView {
  const root = record(payload, ["portfolio_id", "status", "steps", "manifest_sha256", "updated_at"]);
  textValue(root.portfolio_id);
  oneOf(root.status, ["running", "awaiting_approval", "succeeded", "partial_failure", "failed"]);
  if (root.manifest_sha256 !== null && !/^[a-f0-9]{64}$/.test(textValue(root.manifest_sha256))) invalid();
  timestamp(root.updated_at);
  const steps = list(root.steps, (value) => {
    const step = record(value, ["product", "status", "session_id", "detail", "started_at", "completed_at", "artifacts", "failure_reason"]);
    oneOf(step.product, ["sandbox", "browser", "desktop"]); oneOf(step.status, ["pending", "running", "succeeded", "failed", "blocked"]); nullableText(step.session_id); textValue(step.detail); if (step.started_at !== null) timestamp(step.started_at); if (step.completed_at !== null) timestamp(step.completed_at); nullableText(step.failure_reason);
    list(step.artifacts, (entry) => { const artifact = record(entry, ["kind", "label", "url", "sha256", "media_type"]); oneOf(artifact.kind, ["manifest", "citation", "screenshot", "replay", "receipt"]); textValue(artifact.label); const url = nullableText(artifact.url); if (url !== null && !(url.startsWith("https://") || url.startsWith("/api/v2/"))) invalid(); const digest = nullableText(artifact.sha256); if (digest !== null && !/^[a-f0-9]{64}$/.test(digest)) invalid(); nullableText(artifact.media_type); });
    return value as SolariStepReceipt;
  });
  if (steps.length !== 3 || new Set(steps.map((step) => step.product)).size !== 3) invalid();
  return payload as SolariExecutionView;
}

export function parsePublicRecordCheck(payload: unknown): PublicRecordCheckResult {
  const root = record(payload, ["query_type", "query_value", "comparison", "summary", "claimed_year", "official_record_year", "closing_date", "days_to_close", "matching_record_count", "record", "exposure", "dataset_url", "retrieved_at", "limitation"]);
  oneOf(root.query_type, ["permit", "parcel"]); textValue(root.query_value); oneOf(root.comparison, ["aligned", "needs_review", "record_not_found"]); textValue(root.summary); integer(root.claimed_year, 1900, 2100); if (root.official_record_year !== null) integer(root.official_record_year, 1900, 2100); dateValue(root.closing_date); integer(root.days_to_close); integer(root.matching_record_count); timestamp(root.retrieved_at); textValue(root.limitation);
  for (const key of ["dataset_url"] as const) { const parsed = new URL(textValue(root[key])); if (parsed.protocol !== "https:") invalid(); }
  if (root.record !== null) {
    const permit = record(root.record, ["permit_number", "parcel_reference", "application_received_date", "permit_status", "system_type", "construction_type", "county", "official_detail_url"]);
    textValue(permit.permit_number); textValue(permit.parcel_reference); if (permit.application_received_date !== null) dateValue(permit.application_received_date); nullableText(permit.permit_status); nullableText(permit.system_type); nullableText(permit.construction_type); nullableText(permit.county);
    if (permit.official_detail_url !== null) { const parsed = new URL(textValue(permit.official_detail_url)); if (parsed.protocol !== "https:" || parsed.hostname !== "den.dnrec.delaware.gov") invalid(); }
  }
  const exposure = record(root.exposure, ["loan_amount_cents", "daily_delay_cost_cents", "expected_delay_days", "inspection_cost_cents", "without_action_cents", "after_action_cents", "preventable_cents", "formula", "truth_class"]);
  integer(exposure.loan_amount_cents); integer(exposure.daily_delay_cost_cents); integer(exposure.expected_delay_days, 1, 365); integer(exposure.inspection_cost_cents); integer(exposure.without_action_cents); integer(exposure.after_action_cents); integer(exposure.preventable_cents); textValue(exposure.formula); oneOf(exposure.truth_class, ["user_supplied_scenario"]);
  return payload as PublicRecordCheckResult;
}

function classifyStatus(status: number): ApiErrorKind {
  if (status === 401 || status === 403) return "authentication";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status >= 500) return "server_error";
  return "validation";
}

async function request<T>(url: string, init: RequestInit | undefined, parse: (payload: unknown) => T): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: { ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers }
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw new ApiError("aborted", null, "Request cancelled.");
    throw new ApiError("network", null, "Closing Rescue could not reach the server.");
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const kind = classifyStatus(response.status);
    const detail = isObject(payload) && typeof payload.detail === "string" ? payload.detail : null;
    // Never reflect private server details from a 5xx response into the UI.
    const publicSolariMessage = response.status === 503 && detail === "SOLARI_API_KEY is not configured"
      ? "Live Solari is not enabled on this public demo. The complete fixture investigation remains available."
      : null;
    const message = publicSolariMessage ?? (kind === "server_error" ? "Closing Rescue is temporarily unavailable." : detail ?? `Request failed (${response.status}).`);
    throw new ApiError(kind, response.status, message);
  }
  return parse(payload);
}

const api = "/api/v2/closing-rescue";
const parseEvents = (payload: unknown): StoryEvent[] => {
  const events = list(payload, validateStoryEvent);
  const ids = new Set<string>();
  let previousChapter = 1;
  for (const event of events) {
    if (ids.has(event.id) || event.chapter < previousChapter) invalid();
    ids.add(event.id);
    previousChapter = event.chapter;
  }
  return events;
};

export const apiClient = {
  createDemo: (idempotencyKey: string, signal?: AbortSignal) => request(`${api}/demo`, { method: "POST", headers: { "Idempotency-Key": idempotencyKey }, signal }, parseClosingRescueView),
  getRescue: (portfolioId: string, signal?: AbortSignal) => request(`${api}/${encodeURIComponent(portfolioId)}`, { signal }, parseClosingRescueView),
  getStoryEvents: (portfolioId: string, after?: string, signal?: AbortSignal) => {
    const cursor = after ? `?after=${encodeURIComponent(after)}` : "";
    return request(`${api}/${encodeURIComponent(portfolioId)}/events${cursor}`, { signal }, parseEvents);
  },
  decideRescue: (portfolioId: string, payload: { approval_id: string; approver_identity: string; approval_token: string; approve: boolean; simulate_timeout?: boolean }, signal?: AbortSignal) =>
    request(`${api}/${encodeURIComponent(portfolioId)}/approve`, { method: "POST", body: JSON.stringify({ ...payload, simulate_timeout: payload.simulate_timeout ?? false }), signal }, parseClosingRescueView),
  runSolari: (portfolioId: string, signal?: AbortSignal) => request(`${api}/${encodeURIComponent(portfolioId)}/solari`, { method: "POST", signal }, parseSolariExecution),
  getSolari: (portfolioId: string, signal?: AbortSignal) => request(`${api}/${encodeURIComponent(portfolioId)}/solari`, { signal }, parseSolariExecution),
  checkPublicRecord: (payload: PublicRecordCheckInput, signal?: AbortSignal) => request(`${api}/public-record-check`, { method: "POST", body: JSON.stringify(payload), signal }, parsePublicRecordCheck)
};
