import type { ClosingEvidence, ClosingRescueView, Citation } from "./api";
import type { StorySnapshot } from "./story";
import { workflowLifecycle } from "./workflow";

export interface CitationPresentation { id: string; label: string; href: string | null }
export interface EvidencePresentation {
  id: string;
  source: string;
  kind: string;
  status: string;
  timestamp: string;
  truthLabel: "External · cited";
  citations: CitationPresentation[];
}

interface SceneBase { chapter: number; label: string; truthLabel: string }
export interface PortfolioScene extends SceneBase { kind: "portfolio"; headline: string; pipelineValue: string; attentionCandidates: number; exposure: string }
export interface SelectionScene extends SceneBase { kind: "selection"; address: string; loanAmount: string; daysToClose: number; rationale: string; urgency: number; preventable: string }
export interface EvidenceScene extends SceneBase { kind: "evidence"; address: string; items: EvidencePresentation[]; allItems: EvidencePresentation[] }
export interface ContradictionScene extends SceneBase { kind: "contradiction"; headline: string; findingLabel: string; sellerYear: string; permitYear: string; gapYears: number; summary: string; sellerSource: string; permitSource: string; citations: CitationPresentation[] }
export interface ExposureScene extends SceneBase { kind: "exposure"; withoutAction: string; afterAction: string; preventable: string; formulaLines: string[]; disclaimer: string; limitations: string[] }
export type RescuePhase = "pending" | "approved" | "authorized" | "running" | "succeeded" | "completed" | "rejected" | "failed" | "unknown" | "consumed" | "unavailable";
export interface ApprovalScene extends SceneBase { kind: "approval"; vendorName: string; appointment: string; price: string; serviceType: string; protectedExposure: string; actionLabel: "Approve rescue"; phase: RescuePhase; statusHeading: string; statusCopy: string; simulated: boolean }
export type InvestigationScene = PortfolioScene | SelectionScene | EvidenceScene | ContradictionScene | ExposureScene | ApprovalScene;

export interface DocumentaryCut {
  scenes: [PortfolioScene, SelectionScene, EvidenceScene, ContradictionScene, ExposureScene, ApprovalScene];
  activeScene: InvestigationScene;
  story: StorySnapshot;
  canShowApproval: boolean;
  caseAddress: string;
  evidenceLedger: EvidencePresentation[];
  completed: boolean;
}

const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const compactDollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 });
const dateTime = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/New_York", timeZoneName: "short" });

export function formatMoney(cents: number): string { return dollars.format(cents / 100); }
export function formatCompactMoney(cents: number): string { return compactDollars.format(cents / 100); }
export function formatTimestamp(value: string): string { return dateTime.format(new Date(value)); }
export function formatPercent(basisPoints: number): string { return `${basisPoints / 100}%`; }
export function truthLabel(value: "synthetic" | "external_cited"): string { return value === "synthetic" ? "Synthetic" : "External · cited"; }

function safeCitation(citation: Citation): CitationPresentation {
  let href: string | null = null;
  if (citation.source_url) {
    try {
      const url = new URL(citation.source_url);
      if (url.protocol === "https:" || url.protocol === "http:") href = url.href;
    } catch { href = null; }
  }
  return { id: citation.id, label: citation.label ?? citation.source_name, href };
}

function evidencePresentation(evidence: ClosingEvidence): EvidencePresentation {
  return {
    id: evidence.id,
    source: evidence.source,
    kind: evidence.kind.replaceAll("_", " "),
    status: evidence.status.replaceAll("_", " "),
    timestamp: formatTimestamp(evidence.retrieved_at),
    truthLabel: "External · cited",
    citations: evidence.citations.map(safeCitation)
  };
}

function evidenceIds(data: Array<{ key: string; value_json: string }>): string[] {
  const raw = data.find((item) => item.key === "evidence_ids")?.value_json;
  if (!raw) return [];
  try { const value: unknown = JSON.parse(raw); return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []; }
  catch { return []; }
}

function approvalPhase(view: ClosingRescueView): RescuePhase {
  const action = view.actions.at(-1);
  if (!view.approval) return "unavailable";
  if (view.approval.state === "rejected") return "rejected";
  if (workflowLifecycle(view).phase === "completed") return "completed";
  if (action?.state === "unknown") return "unknown";
  if (action?.state === "failed") return "failed";
  if (action?.state === "authorized") return "authorized";
  if (action?.state === "running" || action?.state === "drafted") return "running";
  if (action?.state === "succeeded") return "succeeded";
  if (view.approval.state === "consumed") return "consumed";
  if (view.approval.state === "approved") return "approved";
  return "pending";
}

function phaseCopy(phase: RescuePhase): [string, string] {
  switch (phase) {
    case "completed": return ["Rescue completed", "Simulated booking completed and portfolio exposure re-evaluated."];
    case "rejected": return ["Rescue rejected", "No simulated booking was created."];
    case "unknown": return ["Booking outcome unknown", "Reconciliation required before any retry."];
    case "failed": return ["Rescue action failed", "The failure is persisted. Review the audit record before retrying."];
    case "authorized": return ["Rescue authorized", "The approved action is durable and has not started execution."];
    case "running": return ["Rescue in progress", "The action checkpoint is persisted; completion has not been confirmed."];
    case "succeeded": return ["Booking succeeded; finalization pending", "The booking result is persisted, but rescue.completed has not been recorded."];
    case "approved": return ["Rescue approved", "The approval is persisted. Resume the same idempotent workflow to reconcile execution."];
    case "consumed": return ["Approval consumed", "The terminal action result is not yet available."];
    case "unavailable": return ["Manual intervention required", "No approval proposal is available."];
    default: return ["A human decides what happens next", "Approve one simulated booking. The agent cannot cross this checkpoint alone."];
  }
}

export function projectInvestigation(view: ClosingRescueView, story: StorySnapshot): DocumentaryCut {
  const assessment = view.priority.initial.find((item) => item.external_loan_id === view.selected_case.external_loan_id) ?? view.priority.initial[0];
  const ledger = view.evidence.map(evidencePresentation);
  const visibleEvidenceEvents = view.story_events.filter((event) => event.chapter === 3 && story.visibleEventIds.includes(event.id));
  const ids = new Set(visibleEvidenceEvents.flatMap((event) => evidenceIds(event.data)));
  const visibleEvidence = ids.size ? ledger.filter((item) => ids.has(item.id)) : ledger.slice(0, Math.max(1, visibleEvidenceEvents.length));
  const sellerYear = String(view.seller_claim?.value ?? "Not provided");
  const permitYear = String(view.permit_claim?.value ?? "No record");
  const gap = Number(sellerYear) - Number(permitYear);
  const contradictionCitations = ledger.flatMap((item) => item.citations).filter((citation) => view.contradiction?.citation_ids.includes(citation.id));
  const exposure = view.exposure;
  const vendor = view.proposed_rescue?.selected;
  const phase = approvalPhase(view);
  const [statusHeading, statusCopy] = phaseCopy(phase);
  const scenes: DocumentaryCut["scenes"] = [
    { kind: "portfolio", chapter: 1, label: "Portfolio scan", truthLabel: "Synthetic lender fixture", headline: `${view.portfolio_summary.loan_count} active loans`, pipelineValue: formatCompactMoney(view.portfolio_summary.pipeline_value_cents), attentionCandidates: view.portfolio_summary.attention_candidate_count, exposure: formatMoney(view.portfolio_summary.total_estimated_exposure_cents) },
    { kind: "selection", chapter: 2, label: "Case selected", truthLabel: "Agent-selected · synthetic loan data", address: view.selected_case.address, loanAmount: formatMoney(view.selected_case.loan_amount_cents), daysToClose: assessment.days_to_close, rationale: assessment.selection_explanation, urgency: assessment.urgency_score, preventable: formatMoney(assessment.preventable_exposure_cents) },
    { kind: "evidence", chapter: 3, label: "Physical evidence", truthLabel: "External · cited · timestamped", address: view.selected_case.address, items: visibleEvidence, allItems: ledger },
    { kind: "contradiction", chapter: 4, label: "Record contradiction", truthLabel: "Record mismatch · no diagnosis or allegation", headline: `Two records, ${Number.isFinite(gap) ? Math.abs(gap) : 0} years apart`, findingLabel: "Record contradiction", sellerYear, permitYear, gapYears: Number.isFinite(gap) ? Math.abs(gap) : 0, summary: view.contradiction?.summary ?? "The available records do not establish a contradiction.", sellerSource: view.seller_claim?.source_name ?? "Seller submission", permitSource: view.permit_claim?.source_name ?? "Permit record", citations: contradictionCitations },
    { kind: "exposure", chapter: 5, label: "Rescue calculation", truthLabel: "Synthetic planning estimate", withoutAction: formatMoney(exposure?.without_action_cents ?? 0), afterAction: formatMoney(exposure?.after_action_cents ?? 0), preventable: formatMoney(exposure?.preventable_cents ?? 0), formulaLines: exposure ? [`${formatMoney(exposure.delay_consequence_cents)} × ${formatPercent(exposure.delay_probability_bps)} = ${formatMoney(exposure.without_action_cents)}`, `(${formatMoney(exposure.delay_consequence_cents)} × ${formatPercent(exposure.residual_probability_bps)}) + ${formatMoney(exposure.intervention_cost_cents)} = ${formatMoney(exposure.after_action_cents)}`] : [], disclaimer: "Planning estimate, not guaranteed savings.", limitations: exposure?.limitations ?? ["Missing cost inputs suppress the estimate."] },
    { kind: "approval", chapter: 6, label: "Human checkpoint", truthLabel: "Synthetic vendor data · simulated action", vendorName: vendor?.vendor_name ?? "No qualifying vendor", appointment: vendor ? formatTimestamp(vendor.appointment_at) : "Manual escalation required", price: formatMoney(vendor?.price_cents ?? 0), serviceType: vendor?.service_type ?? "No appointment available", protectedExposure: formatMoney(assessment.preventable_exposure_cents), actionLabel: "Approve rescue", phase, statusHeading, statusCopy, simulated: true }
  ];
  const activeScene = scenes[Math.max(0, Math.min(5, story.visibleChapter - 1))];
  return { scenes, activeScene, story, canShowApproval: story.visibleChapter === 6, caseAddress: view.selected_case.address, evidenceLedger: ledger, completed: phase === "completed" };
}
