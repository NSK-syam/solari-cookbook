import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import App from "./App";
import { ApiError, apiClient, parseClosingRescueView, parseSolariExecution, type ClosingRescueView, type SolariExecutionView } from "./api";
import { resetSessionFallbackForTests } from "./session";
import { InvestigationExperience } from "./components/InvestigationExperience";
import { projectInvestigation } from "./presentation";

const chapters = [1, 2, 3, 3, 3, 4, 5, 6].map((chapter, index) => ({
  id: `evt-${index + 1}`,
  case_id: "case-1",
  event_type: chapter === 4 ? "contradiction.detected" : `story.chapter.${chapter}`,
  chapter,
  message: `Persisted chapter ${chapter}`,
  data: [{ key: "chapter", value_json: String(chapter) }],
  created_at: `2026-08-05T14:${String(index).padStart(2, "0")}:00Z`
}));
const completionEvent = { id: "evt-completed", case_id: "case-1", event_type: "rescue.completed", chapter: 6, message: "Rescue completed", data: [{ key: "chapter", value_json: "6" }, { key: "story_order", value_json: "8" }], created_at: "2026-08-05T14:07:00Z" };

const signals = { delay_probability_bps: 7500, residual_probability_after_intervention_bps: 1800, intervention_cost_cents: 48000, intervention_available: true, evidence_completeness_bps: 10000, contradiction_score: 100, uncertainty_score: 0, source_failed: false, source_inputs: [{ name: "fixture", value: true }] };
const assessment = { external_loan_id: "CR-0047", days_to_close: 6, urgency_score: 90, delay_consequence_cents: 2400000, delay_probability_bps: 7500, residual_probability_after_intervention_bps: 1800, intervention_cost_cents: 48000, intervention_available: true, exposure_without_intervention_cents: 1800000, exposure_after_intervention_cents: 480000, preventable_exposure_cents: 1320000, evidence_completeness_bps: 10000, contradiction_score: 100, uncertainty_score: 0, source_failed: false, source_inputs: [{ name: "fixture", value: true }], input_signals: signals, effective_signals: signals, formula_version: "priority-v1" as const, scenario_profile_version: "closing-rescue-scenarios-v1" as const, selection_explanation: "Highest preventable exposure" };

export const view: ClosingRescueView = {
  portfolio_id: "portfolio-1",
  status: "complete",
  reason: null,
  portfolio_summary: { loan_count: 47, pipeline_value_cents: 1420000000, attention_candidate_count: 4, total_estimated_exposure_cents: 1800000, truth_class: "synthetic" },
  selected_case: { id: "loan-47", external_loan_id: "CR-0047", address: "91 Marsh Road, Milton, DE 19968", loan_amount_cents: 41200000, closing_date: "2026-08-11", rate_lock_daily_cost_cents: 180000, expected_extension_days: 7, rescheduling_cost_cents: 900000, staff_cost_cents: 240000, seller_claims_json: "[]", approved_vendors: ["First State Environmental"], fixture_scenario: "priority", truth_class: "synthetic", delay_consequence_cents: 2400000 },
  priority: { initial_batch_id: "batch-1", current_batch_id: "batch-1", initial: [assessment], current: [assessment], truth_class: "synthetic" },
  case_state: "waiting_for_approval",
  current_chapter: 6,
  evidence: [{ id: "evidence-1", case_id: "case-1", source: "Mireye", kind: "terrain", status: "success", retrieved_at: "2026-08-05T14:02:00Z", confidence: 0.96, payload_json: "{}", citations: [{ id: "citation-1", source_name: "Mireye", source_url: "https://example.test/mireye", retrieved_at: "2026-08-05T14:02:00Z", published_at: null, confidence: 0.96, label: "Terrain" }], request_id: null, error_code: null, error_message: null, raw_json: "{}", truth_class: "external_cited" }],
  seller_claim: { id: "claim-seller", field: "septic_replacement_year", value: 2018, truth_class: "synthetic", source_name: "Seller submission", observed_at: "2026-08-05T14:01:00Z", citation_ids: [] },
  permit_claim: { id: "claim-permit", field: "septic_replacement_year", value: 1991, truth_class: "external_cited", source_name: "Delaware", observed_at: "2026-08-05T14:02:00Z", citation_ids: ["citation-1"] },
  contradiction: { id: "contradiction-1", kind: "direct", claim_ids: ["claim-seller", "claim-permit"], citation_ids: ["citation-1"], source_names: ["Seller submission", "Delaware"], summary: "The records disagree.", rule_id: "replacement-year", rule_version: "contradiction-rules-v1", created_at: "2026-08-05T14:03:00Z" },
  exposure: { id: "exposure-1", truth_class: "synthetic", delay_consequence_cents: 2400000, delay_probability_bps: 7500, residual_probability_bps: 1800, intervention_cost_cents: 48000, intervention_available: true, without_action_cents: 1800000, after_action_cents: 480000, preventable_cents: 1320000, formula_version: "closing-exposure-2026-08-05", limitations: ["Planning estimate"], created_at: "2026-08-05T14:04:00Z" },
  proposed_rescue: { selected: { id: "vendor-1", vendor_name: "First State Environmental", appointment_at: "2026-08-07T14:00:00Z", price_cents: 48000, service_type: "septic inspection", approved: true, qualified: true, available_as_of: "2026-08-05T14:04:00Z", truth_class: "synthetic" }, considered: [], approved_names: ["First State Environmental"], cutoff: "2026-08-10T12:00:00Z", evaluated_at: "2026-08-05T14:04:00Z", selected_at: "2026-08-05T14:04:00Z", truth_class: "synthetic" },
  approval: { id: "approval-1", case_id: "case-1", decision_id: "decision-1", action_kind: "inspection_order", draft_json: "{}", approver_identity: "ops@harbor.demo", state: "pending", created_at: "2026-08-05T14:05:00Z", decided_at: null },
  actions: [], story_events: chapters, approval_token: "one-time-secret"
};

function response(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

describe("Closing Rescue documentary controller", () => {
  beforeEach(() => sessionStorage.clear());
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); resetSessionFallbackForTests(); });

  test("creates a journey, captures the token in session scope, and never renders it", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(view, 201)));
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /start the rescue/i }));
    expect(await screen.findByText("47 active loans")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("one-time-secret");
    expect(window.localStorage.length).toBe(0);
    expect(Object.values(sessionStorage)).toContain("one-time-secret");
  });

  test("skip changes presentation but preserves the pending approval gate", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(view, 201)));
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /start the rescue/i }));
    fireEvent.click(await screen.findByRole("button", { name: /skip to finding/i }));
    expect(await screen.findByRole("button", { name: /approve rescue/i })).toBeEnabled();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  test("approves with the captured token and clears it after consumption", async () => {
    const consumed = { ...view, approval: { ...view.approval!, state: "consumed" as const }, case_state: "monitoring" as const, actions: [{ id: "action-1", case_id: "case-1", approval_id: "approval-1", kind: "inspection_order" as const, state: "succeeded" as const, payload_json: "{}", result_json: "{}", created_at: "2026-08-05T14:06:00Z", updated_at: "2026-08-05T14:06:00Z" }], story_events: [...chapters, completionEvent], approval_token: null };
    const fetchMock = vi.fn().mockResolvedValueOnce(response(view, 201)).mockResolvedValueOnce(response(consumed));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /start the rescue/i }));
    fireEvent.click(await screen.findByRole("button", { name: /skip to finding/i }));
    fireEvent.click(screen.getByRole("button", { name: /approve rescue/i }));
    expect(await screen.findByRole("heading", { name: "Rescue completed" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith("/api/v2/closing-rescue/portfolio-1/approve", expect.objectContaining({ body: expect.stringContaining("one-time-secret") }));
    expect(Object.values(sessionStorage)).not.toContain("one-time-secret");
  });

  test("reload reconstructs the persisted chapter without requiring the secret", async () => {
    sessionStorage.setItem("closing-rescue:portfolio", "portfolio-1");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ...view, approval_token: null })));
    render(<App />);
    expect(await screen.findByRole("button", { name: /approve rescue/i })).toBeDisabled();
    expect(screen.getByText(/approval token is unavailable/i)).toBeInTheDocument();
  });

  test("newer navigation aborts the stale request so it cannot overwrite state", async () => {
    let firstSignal: AbortSignal | undefined;
    const fetchMock = vi.fn((_: RequestInfo | URL, init?: RequestInit) => {
      firstSignal = init?.signal ?? undefined;
      return new Promise<Response>(() => undefined);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { unmount } = render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /start the rescue/i }));
    unmount();
    expect(firstSignal?.aborted).toBe(true);
  });

  test("rejects without creating an action and removes the one-time token", async () => {
    const rejected = { ...view, approval: { ...view.approval!, state: "rejected" as const }, actions: [], approval_token: null };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(view, 201)).mockResolvedValueOnce(response(rejected)));
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /start the rescue/i }));
    fireEvent.click(await screen.findByRole("button", { name: /skip to finding/i }));
    fireEvent.click(screen.getByRole("button", { name: /reject rescue/i }));
    expect(await screen.findByRole("heading", { name: "Rescue rejected" })).toBeInTheDocument();
    expect(Object.values(sessionStorage)).not.toContain("one-time-secret");
  });

  test("shows unknown outcome as reconciliation-only and does not offer retry", async () => {
    const unknown = { ...view, approval: { ...view.approval!, state: "consumed" as const }, case_state: "monitoring" as const, approval_token: null, actions: [{ id: "action-1", case_id: "case-1", approval_id: "approval-1", kind: "inspection_order" as const, state: "unknown" as const, payload_json: "{}", result_json: "{}", created_at: "2026-08-05T14:06:00Z", updated_at: "2026-08-05T14:06:00Z" }] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(unknown)));
    sessionStorage.setItem("closing-rescue:portfolio", "portfolio-1");
    render(<App />);
    expect(await screen.findByText(/reconciliation required/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve rescue/i })).not.toBeInTheDocument();
  });

  test("validates coherent read models and rejects mismatched persisted chapters", () => {
    expect(parseClosingRescueView(view).portfolio_id).toBe("portfolio-1");
    expect(() => parseClosingRescueView({ ...view, current_chapter: 5 })).toThrow(ApiError);
    expect(() => parseClosingRescueView({ ...view, story_events: [...chapters, chapters[0]] })).toThrow(ApiError);
  });

  test("uses the event cursor and classifies 5xx without leaking response details", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(chapters.slice(1))).mockResolvedValueOnce(response({ detail: "private database path" }, 500));
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiClient.getStoryEvents("portfolio-1", "evt-1")).resolves.toEqual(chapters.slice(1));
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/v2/closing-rescue/portfolio-1/events?after=evt-1", expect.any(Object));
    await expect(apiClient.getRescue("portfolio-1")).rejects.toMatchObject({ kind: "server_error", message: "Closing Rescue is temporarily unavailable." });
  });

  test("rejects a malformed cursor event payload recursively", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response([{ ...chapters[0], data: [{ key: "chapter", value_json: "garbage" }] }])));
    await expect(apiClient.getStoryEvents("portfolio-1", "evt-before")).rejects.toMatchObject({ kind: "server_error" });
  });

  test.each([
    ["empty selected case", { ...view, selected_case: {} }],
    ["missing assessment inputs", { ...view, priority: { ...view.priority, initial: [{}] } }],
    ["invalid truth label", { ...view, portfolio_summary: { ...view.portfolio_summary, truth_class: "live" } }],
    ["invalid evidence status", { ...view, evidence: [{ ...view.evidence[0], status: "available" }] }],
    ["invalid nested citation", { ...view, evidence: [{ ...view.evidence[0], citations: [{}] }] }],
    ["invalid timestamp", { ...view, evidence: [{ ...view.evidence[0], retrieved_at: "yesterday" }] }],
    ["impossible timestamp date", { ...view, evidence: [{ ...view.evidence[0], retrieved_at: "2026-02-30T14:02:00Z" }] }],
    ["empty priority batch", { ...view, priority: { ...view.priority, current: [] } }],
    ["invalid contradiction enum", { ...view, contradiction: { ...view.contradiction!, kind: "direct_contradiction" } }],
    ["invalid approval enum", { ...view, approval: { ...view.approval!, state: "done" } }],
    ["invalid action enum", { ...view, actions: [{ id: "a", state: "complete" }] }],
    ["invalid event payload", { ...view, story_events: chapters.map((event, index) => index === 0 ? { ...event, data: [{ key: "chapter", value_json: "not-json" }] } : event) }]
  ])("rejects malformed nested snapshot: %s", (_label, malformed) => {
    expect(() => parseClosingRescueView(malformed)).toThrow(ApiError);
  });

  test("retains the token and resumes an approved workflow with no action", async () => {
    const approved = { ...view, approval: { ...view.approval!, state: "approved" as const }, actions: [], approval_token: null };
    const consumed = { ...approved, approval: { ...approved.approval, state: "consumed" as const }, actions: [action("succeeded")], story_events: [...chapters, completionEvent], approval_token: null };
    sessionStorage.setItem("closing-rescue:portfolio", "portfolio-1");
    sessionStorage.setItem("closing-rescue:approval:approval-1", "one-time-secret");
    const fetchMock = vi.fn().mockResolvedValueOnce(response(approved)).mockResolvedValueOnce(response(consumed));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    const resume = await screen.findByRole("button", { name: /resume approved rescue/i });
    expect(resume).toBeEnabled();
    expect(Object.values(sessionStorage)).toContain("one-time-secret");
    expect(document.body).not.toHaveTextContent("one-time-secret");
    fireEvent.click(resume);
    expect(await screen.findByRole("heading", { name: "Rescue completed" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith("/api/v2/closing-rescue/portfolio-1/approve", expect.objectContaining({ body: expect.stringContaining("one-time-secret") }));
  });

  test.each([
    ["authorized", "Rescue authorized"],
    ["running", "Rescue in progress"],
    ["failed", "Rescue action failed"]
  ] as const)("reload renders %s action without claiming completion", async (state, heading) => {
    const interrupted = { ...view, approval: { ...view.approval!, state: "approved" as const }, actions: [action(state)], approval_token: null };
    sessionStorage.setItem("closing-rescue:portfolio", "portfolio-1");
    sessionStorage.setItem("closing-rescue:approval:approval-1", "one-time-secret");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(interrupted)));
    render(<App />);
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    expect(screen.queryByText(/rescue recorded/i)).not.toBeInTheDocument();
    if (state === "failed") expect(Object.values(sessionStorage)).not.toContain("one-time-secret");
    else expect(Object.values(sessionStorage)).toContain("one-time-secret");
  });

  test("consumed booking success remains resumable until rescue.completed is persisted", async () => {
    const finalizationPending = { ...view, approval: { ...view.approval!, state: "consumed" as const }, actions: [action("succeeded")], approval_token: null };
    const finalized = { ...finalizationPending, story_events: [...chapters, completionEvent] };
    sessionStorage.setItem("closing-rescue:portfolio", "portfolio-1");
    sessionStorage.setItem("closing-rescue:approval:approval-1", "one-time-secret");
    const fetchMock = vi.fn().mockResolvedValueOnce(response(finalizationPending)).mockResolvedValueOnce(response(finalized));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    expect(await screen.findByRole("heading", { name: /booking succeeded.*finalization pending/i })).toBeInTheDocument();
    expect(Object.values(sessionStorage)).toContain("one-time-secret");
    const finalize = screen.getByRole("button", { name: /resume.*finalize/i });
    fireEvent.click(finalize);
    expect(await screen.findByRole("heading", { name: "Rescue completed" })).toBeInTheDocument();
    expect(Object.values(sessionStorage)).not.toContain("one-time-secret");
    expect(fetchMock).toHaveBeenLastCalledWith("/api/v2/closing-rescue/portfolio-1/approve", expect.objectContaining({ body: expect.stringContaining("one-time-secret") }));
  });

  test.each(["failed", "unknown"] as const)("approve response %s deletes the non-resumable token", async (state) => {
    const terminal = { ...view, approval: { ...view.approval!, state: "consumed" as const }, actions: [action(state)], approval_token: null };
    const fetchMock = vi.fn().mockResolvedValueOnce(response(view, 201)).mockResolvedValueOnce(response(terminal));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /start the rescue/i }));
    fireEvent.click(await screen.findByRole("button", { name: /skip to finding/i }));
    fireEvent.click(screen.getByRole("button", { name: /approve rescue/i }));
    expect(await screen.findByRole("heading", { name: state === "failed" ? /rescue action failed/i : /booking outcome unknown/i })).toBeInTheDocument();
    expect(Object.values(sessionStorage)).not.toContain("one-time-secret");
  });

  test("reload deletes a token for bare consumed approval", async () => {
    const bareConsumed = { ...view, approval: { ...view.approval!, state: "consumed" as const }, actions: [], approval_token: null };
    sessionStorage.setItem("closing-rescue:portfolio", "portfolio-1");
    sessionStorage.setItem("closing-rescue:approval:approval-1", "one-time-secret");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(bareConsumed)));
    render(<App />);
    expect(await screen.findByRole("heading", { name: /approval consumed/i })).toBeInTheDocument();
    expect(Object.values(sessionStorage)).not.toContain("one-time-secret");
  });

  test.each([
    ["selected missing from current", { ...view, priority: { ...view.priority, current: [{ ...assessment, external_loan_id: "CR-0001" }] } }],
    ["cross-case evidence", { ...view, evidence: [{ ...view.evidence[0], case_id: "case-other" }] }],
    ["cross-case event", { ...view, story_events: chapters.map((event, index) => index === 3 ? { ...event, case_id: "case-other" } : event) }],
    ["cross-case approval", { ...view, approval: { ...view.approval!, case_id: "case-other" } }],
    ["action missing approval", { ...view, actions: [action("running")], approval: null }],
    ["action wrong approval", { ...view, actions: [{ ...action("running"), approval_id: "approval-other" }] }],
    ["contradiction missing claim", { ...view, contradiction: { ...view.contradiction!, claim_ids: ["claim-seller", "claim-missing"] } }],
    ["contradiction missing citation", { ...view, contradiction: { ...view.contradiction!, citation_ids: ["citation-missing"] } }],
    ["permit missing citation", { ...view, permit_claim: { ...view.permit_claim!, citation_ids: ["citation-missing"] } }],
    ["unsafe citation URL", { ...view, evidence: [{ ...view.evidence[0], citations: [{ ...view.evidence[0].citations[0], source_url: "javascript:alert(1)" }] }] }],
    ["impossible calendar date", { ...view, selected_case: { ...view.selected_case, closing_date: "2026-02-30" } }]
  ])("rejects incoherent relationship: %s", (_label, incoherent) => {
    expect(() => parseClosingRescueView(incoherent)).toThrow(ApiError);
  });

  test("storage read failure keeps the read-only start screen available", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("denied"); });
    render(<App />);
    expect(screen.getByRole("button", { name: /start the rescue/i })).toBeEnabled();
    expect(await screen.findByText(/only in this tab/i)).toBeInTheDocument();
  });

  test("storage write failure uses active-tab fallback without exposing the token", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("denied"); });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(view, 201)));
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /start the rescue/i }));
    fireEvent.click(await screen.findByRole("button", { name: /skip to finding/i }));
    expect(screen.getByRole("button", { name: /approve rescue/i })).toBeEnabled();
    expect(screen.getByText(/only in this tab/i)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("one-time-secret");
  });

  test("storage remove failure is nonfatal and surfaces a persistence warning", async () => {
    const rejected = { ...view, approval: { ...view.approval!, state: "rejected" as const }, actions: [], approval_token: null };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(response(view, 201)).mockResolvedValueOnce(response(rejected)));
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /start the rescue/i }));
    fireEvent.click(await screen.findByRole("button", { name: /skip to finding/i }));
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new DOMException("denied"); });
    fireEvent.click(screen.getByRole("button", { name: /reject rescue/i }));
    expect(await screen.findByRole("heading", { name: /rescue rejected/i })).toBeInTheDocument();
    expect(screen.getByText(/only in this tab/i)).toBeInTheDocument();
  });

  test("saved portfolio 404 purges its obsolete token and idempotency pointers", async () => {
    sessionStorage.setItem("closing-rescue:portfolio", "portfolio-missing");
    sessionStorage.setItem("closing-rescue:idempotency", "old-idempotency");
    sessionStorage.setItem("closing-rescue:active-approval:portfolio-missing", "closing-rescue:approval:approval-old");
    sessionStorage.setItem("closing-rescue:approval:approval-old", "obsolete-secret");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ detail: "Closing Rescue portfolio not found" }, 404)));
    render(<App />);
    expect(await screen.findByText("Closing Rescue portfolio not found")).toBeInTheDocument();
    expect(sessionStorage.getItem("closing-rescue:portfolio")).toBeNull();
    expect(sessionStorage.getItem("closing-rescue:idempotency")).toBeNull();
    expect(sessionStorage.getItem("closing-rescue:active-approval:portfolio-missing")).toBeNull();
    expect(sessionStorage.getItem("closing-rescue:approval:approval-old")).toBeNull();
    expect(screen.getByRole("button", { name: /start the rescue/i })).toBeEnabled();
  });
});

describe("Closing Rescue cinematic presentation", () => {
  afterEach(() => cleanup());

  const documentary = () => projectInvestigation(view, {
    visibleChapter: 6,
    persistedChapter: 6,
    paused: false,
    replaying: false,
    skipped: true,
    eventIds: chapters.map((event) => event.id),
    visibleEventIds: chapters.map((event) => event.id)
  });

  test("projects a discriminated six-scene documentary without mutating domain data", () => {
    const original = structuredClone(view);
    const cut = documentary();

    expect(cut.scenes.map((scene) => scene.kind)).toEqual([
      "portfolio",
      "selection",
      "evidence",
      "contradiction",
      "exposure",
      "approval"
    ]);
    expect(cut.scenes[0]).toMatchObject({ headline: "47 active loans", pipelineValue: "$14.2M", attentionCandidates: 4 });
    expect(cut.scenes[1]).toMatchObject({ address: "91 Marsh Road, Milton, DE 19968", loanAmount: "$412,000", daysToClose: 6 });
    expect(cut.scenes[3]).toMatchObject({ findingLabel: "Record contradiction", sellerYear: "2018", permitYear: "1991" });
    expect(cut.scenes[4]).toMatchObject({ withoutAction: "$18,000", afterAction: "$4,800", preventable: "$13,200" });
    expect(cut.scenes[5]).toMatchObject({ vendorName: "First State Environmental", price: "$480", actionLabel: "Approve rescue" });
    expect(view).toEqual(original);
  });

  test("centralizes truth, source, timestamp, formula, and approval gating policy", () => {
    const cut = documentary();
    const evidence = cut.scenes[2];
    const exposure = cut.scenes[4];

    expect(evidence.kind).toBe("evidence");
    if (evidence.kind !== "evidence" || exposure.kind !== "exposure") throw new Error("wrong scene");
    expect(evidence.items[0]).toMatchObject({ truthLabel: "External · cited", source: "Mireye" });
    expect(evidence.items[0].timestamp).toMatch(/2026/);
    expect(evidence.items[0].citations[0].href).toMatch(/^https:\/\//);
    expect(exposure.truthLabel).toBe("Synthetic planning estimate");
    expect(exposure.disclaimer).toMatch(/not guaranteed/i);
    expect(exposure.formulaLines).toEqual(expect.arrayContaining([
      "$24,000 × 75% = $18,000",
      "($24,000 × 18%) + $480 = $4,800"
    ]));
    expect(cut.canShowApproval).toBe(true);
    expect(projectInvestigation(view, { ...cut.story, visibleChapter: 5 }).canShowApproval).toBe(false);
  });

  test("renders one dominant chapter, a persistent rail, evidence drawer, and no early approval", () => {
    const cut = documentary();
    render(<InvestigationExperience cut={{ ...cut, activeScene: cut.scenes[3], canShowApproval: false }} busy={false} tokenAvailable onDecide={vi.fn()} playback={{ pause: vi.fn(), resume: vi.fn(), replay: vi.fn(), skip: vi.fn() }} />);

    expect(screen.getByRole("heading", { level: 2, name: /two records.*27 years apart/i })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: /investigation chapters/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /open evidence ledger/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve rescue/i })).not.toBeInTheDocument();
    expect(screen.getByText(/requires resolution/i)).toBeInTheDocument();
  });

  test("renders the exact approval CTA only in chapter six and exposes accessible playback", () => {
    const cut = documentary();
    render(<InvestigationExperience cut={cut} busy={false} tokenAvailable onDecide={vi.fn()} playback={{ pause: vi.fn(), resume: vi.fn(), replay: vi.fn(), skip: vi.fn() }} />);

    expect(screen.getByRole("button", { name: "Approve rescue" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Reject rescue" })).toBeEnabled();
    expect(screen.getByRole("group", { name: /story playback controls/i })).toBeInTheDocument();
    expect(screen.getByText(/synthetic vendor data/i)).toBeInTheDocument();
    expect(screen.getByText(/simulated booking/i)).toBeInTheDocument();
  });

  test("renders resilient loading, error, and empty states with live announcements", () => {
    const { rerender } = render(<InvestigationExperience state="loading" />);
    expect(screen.getByRole("status")).toHaveTextContent(/scanning 47 active loans/i);
    rerender(<InvestigationExperience state="error" message="The cited record service is unavailable." onRetry={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/unavailable/i);
    expect(screen.getByRole("button", { name: /try again/i })).toBeEnabled();
    rerender(<InvestigationExperience state="empty" onStart={vi.fn()} />);
    expect(screen.getByRole("button", { name: /start the rescue/i })).toBeEnabled();
  });
});

describe("Solari execution rail", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  const execution: SolariExecutionView = {
    portfolio_id: "portfolio-1",
    status: "awaiting_approval",
    manifest_sha256: "a".repeat(64),
    updated_at: "2026-08-05T14:08:00Z",
    steps: [
      { product: "sandbox", status: "succeeded", session_id: "sandbox-session", detail: "Verified 47 loans", started_at: "2026-08-05T14:06:00Z", completed_at: "2026-08-05T14:07:00Z", failure_reason: null, artifacts: [{ kind: "manifest", label: "Calculation manifest", url: "/api/v2/closing-rescue/artifacts/manifest.json", sha256: "a".repeat(64), media_type: "application/json" }] },
      { product: "browser", status: "succeeded", session_id: "browser-session", detail: "Captured official permit", started_at: "2026-08-05T14:07:00Z", completed_at: "2026-08-05T14:08:00Z", failure_reason: null, artifacts: [{ kind: "replay", label: "Recorded browser replay", url: "https://example.test/replay", sha256: null, media_type: null }] },
      { product: "desktop", status: "blocked", session_id: null, detail: "Waiting for human approval", started_at: null, completed_at: null, failure_reason: null, artifacts: [] }
    ]
  };

  test("validates unique products and safe artifact URLs", () => {
    expect(parseSolariExecution(execution)).toEqual(execution);
    expect(() => parseSolariExecution({ ...execution, steps: [execution.steps[0], execution.steps[0], execution.steps[2]] })).toThrow(ApiError);
    const unsafe = structuredClone(execution); unsafe.steps[0].artifacts[0].url = "javascript:alert(1)";
    expect(() => parseSolariExecution(unsafe)).toThrow(ApiError);
  });

  test("runs the proof explicitly and displays persisted artifacts", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(view, 201)).mockResolvedValueOnce(response(execution));
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /start the rescue/i }));
    fireEvent.click(await screen.findByRole("button", { name: /run live solari proof/i }));
    expect(await screen.findByRole("link", { name: /recorded browser replay/i })).toHaveAttribute("href", "https://example.test/replay");
    expect(screen.getByText(/waiting for human approval/i)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith("/api/v2/closing-rescue/portfolio-1/solari", expect.objectContaining({ method: "POST" }));
  });
});

function action(state: "authorized" | "running" | "failed" | "succeeded" | "unknown") {
  return { id: `action-${state}`, case_id: "case-1", approval_id: "approval-1", kind: "inspection_order" as const, state, payload_json: "{}", result_json: "{}", created_at: "2026-08-05T14:06:00Z", updated_at: "2026-08-05T14:06:00Z" };
}
