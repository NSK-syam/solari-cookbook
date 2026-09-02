import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiClient, type ClosingRescueView, type SolariExecutionView } from "./api";
import { InvestigationExperience } from "./components/InvestigationExperience";
import { LiveRecordCheck } from "./components/LiveRecordCheck";
import { projectInvestigation } from "./presentation";
import { StoryController, type StorySnapshot } from "./story";
import { SafeSessionStore } from "./session";
import { workflowLifecycle } from "./workflow";

const PORTFOLIO_KEY = "closing-rescue:portfolio";
const IDEMPOTENCY_KEY = "closing-rescue:idempotency";
const LIVE_SOLARI_ENABLED = import.meta.env.MODE !== "production" || import.meta.env.VITE_SOLARI_LIVE_AVAILABLE === "true";
const STORY_SPEED = Number(import.meta.env.VITE_STORY_SPEED ?? "1");
const STORY_DELAY_MS = Number.isFinite(STORY_SPEED) ? Math.max(0, 1800 * STORY_SPEED) : 1800;
const initialStory: StorySnapshot = { visibleChapter: 1, persistedChapter: 1, paused: false, replaying: false, skipped: false, eventIds: [], visibleEventIds: [] };

function tokenKey(approvalId: string): string { return `closing-rescue:approval:${approvalId}`; }
function activeApprovalKey(portfolioId: string): string { return `closing-rescue:active-approval:${portfolioId}`; }
function safeMessage(error: unknown): string { return error instanceof ApiError || error instanceof Error ? error.message : "Closing Rescue could not complete the request."; }
function withoutToken(snapshot: ClosingRescueView): ClosingRescueView { return snapshot.approval_token === null ? snapshot : { ...snapshot, approval_token: null }; }
function makeIdempotencyKey(): string { return `closing-rescue-web-${crypto.randomUUID()}`; }

export default function App() {
  const [view, setView] = useState<ClosingRescueView | null>(null);
  const [story, setStory] = useState(initialStory);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [storageWarning, setStorageWarning] = useState<string | null>(null);
  const [tokenAvailable, setTokenAvailable] = useState(false);
  const [solariExecution, setSolariExecution] = useState<SolariExecutionView | null>(null);
  const [solariBusy, setSolariBusy] = useState(false);
  const [publicCheckOpen, setPublicCheckOpen] = useState(false);
  const controllerRef = useRef<StoryController | null>(null);
  const requestRef = useRef<{ id: number; controller: AbortController } | null>(null);
  const requestIdRef = useRef(0);
  const sessionRef = useRef<SafeSessionStore | null>(null);
  if (sessionRef.current === null) sessionRef.current = new SafeSessionStore(setStorageWarning);
  const session = sessionRef.current;

  const replaceController = useCallback((snapshot: ClosingRescueView, startAtBeginning: boolean) => {
    controllerRef.current?.dispose();
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const controller = new StoryController(snapshot.story_events, { startAtBeginning, delayMs: reduceMotion ? 0 : STORY_DELAY_MS });
    controllerRef.current = controller;
    controller.subscribe(setStory);
  }, []);

  const beginRequest = useCallback(() => {
    requestRef.current?.controller.abort();
    const operation = { id: ++requestIdRef.current, controller: new AbortController() };
    requestRef.current = operation;
    return operation;
  }, []);

  const commitSnapshot = useCallback((snapshot: ClosingRescueView, startAtBeginning: boolean) => {
    const activeKey = activeApprovalKey(snapshot.portfolio_id);
    const previousTokenKey = session.get(activeKey);
    if (snapshot.approval_token && snapshot.approval) {
      session.set(tokenKey(snapshot.approval.id), snapshot.approval_token);
    }
    if (snapshot.approval) {
      const currentTokenKey = tokenKey(snapshot.approval.id);
      if (previousTokenKey && previousTokenKey !== currentTokenKey) session.remove(previousTokenKey);
      if (workflowLifecycle(snapshot).retainToken) session.set(activeKey, currentTokenKey);
      else { session.remove(currentTokenKey); session.remove(activeKey); }
    } else {
      if (previousTokenKey) session.remove(previousTokenKey);
      session.remove(activeKey);
    }
    session.set(PORTFOLIO_KEY, snapshot.portfolio_id);
    setTokenAvailable(snapshot.approval ? session.get(tokenKey(snapshot.approval.id)) !== null : false);
    const publicSnapshot = withoutToken(snapshot);
    setView(publicSnapshot);
    replaceController(publicSnapshot, startAtBeginning);
  }, [replaceController, session]);

  const loadExisting = useCallback(async (portfolioId: string) => {
    const operation = beginRequest();
    setBusy(true);
    try {
      const snapshot = await apiClient.getRescue(portfolioId, operation.controller.signal);
      if (requestRef.current?.id === operation.id) commitSnapshot(snapshot, false);
    } catch (error) {
      if (requestRef.current?.id === operation.id && !(error instanceof ApiError && error.kind === "aborted")) {
        setNotice(safeMessage(error));
        if (error instanceof ApiError && error.kind === "not_found") {
          const activeKey = activeApprovalKey(portfolioId);
          const obsoleteTokenKey = session.get(activeKey);
          if (obsoleteTokenKey) session.remove(obsoleteTokenKey);
          session.remove(activeKey);
          session.remove(PORTFOLIO_KEY);
          session.remove(IDEMPOTENCY_KEY);
          setTokenAvailable(false);
        }
      }
    } finally {
      if (requestRef.current?.id === operation.id) setBusy(false);
    }
  }, [beginRequest, commitSnapshot, session]);

  useEffect(() => {
    const portfolioId = session.get(PORTFOLIO_KEY);
    if (portfolioId) void loadExisting(portfolioId);
    return () => {
      requestRef.current?.controller.abort();
      controllerRef.current?.dispose();
    };
  }, [loadExisting, session]);

  const startJourney = async () => {
    const operation = beginRequest();
    setBusy(true);
    setNotice(null);
    let idempotencyKey = session.get(IDEMPOTENCY_KEY);
    if (!idempotencyKey) {
      idempotencyKey = makeIdempotencyKey();
      session.set(IDEMPOTENCY_KEY, idempotencyKey);
    }
    try {
      const snapshot = await apiClient.createDemo(idempotencyKey, operation.controller.signal);
      if (requestRef.current?.id === operation.id) commitSnapshot(snapshot, true);
    } catch (error) {
      if (requestRef.current?.id === operation.id && !(error instanceof ApiError && error.kind === "aborted")) setNotice(safeMessage(error));
    } finally {
      if (requestRef.current?.id === operation.id) setBusy(false);
    }
  };

  const decide = async (approve: boolean) => {
    if (!view?.approval) return;
    const secret = session.get(tokenKey(view.approval.id));
    if (!secret) { setNotice("Approval token is unavailable. Start a fresh session to continue."); return; }
    const operation = beginRequest();
    setBusy(true);
    setNotice(null);
    try {
      const snapshot = await apiClient.decideRescue(view.portfolio_id, {
        approval_id: view.approval.id,
        approver_identity: view.approval.approver_identity,
        approval_token: secret,
        approve
      }, operation.controller.signal);
      if (requestRef.current?.id === operation.id) {
        commitSnapshot(snapshot, false);
        const action = snapshot.actions.at(-1);
        if (snapshot.approval?.state === "pending") setNotice("Approval is still pending; no action has been created.");
        else if (snapshot.approval?.state === "rejected") setNotice("Rescue rejected. No simulated booking was created.");
        else if (action?.state === "unknown") setNotice("Booking outcome is unknown. Reconciliation is required before any retry.");
        else if (action?.state === "failed") setNotice("The simulated rescue action failed. Review the audit record before retrying.");
        else if (workflowLifecycle(snapshot).phase === "completed") setNotice("Rescue completed. The simulated booking and re-evaluation are persisted.");
        else if (snapshot.approval?.state === "approved" || action?.state === "drafted" || action?.state === "authorized" || action?.state === "running") setNotice("Approval is persisted and execution can resume safely.");
        else if (action?.state === "succeeded") setNotice("Booking succeeded; finalization is still pending.");
        else setNotice("Rescue state updated; completion has not been confirmed.");
        if (approve && solariExecution) {
          try { setSolariExecution(await apiClient.getSolari(view.portfolio_id)); }
          catch (error) { setNotice(`Core approval succeeded. ${safeMessage(error)}`); }
        }
      }
    } catch (error) {
      if (requestRef.current?.id === operation.id && !(error instanceof ApiError && error.kind === "aborted")) setNotice(safeMessage(error));
    } finally {
      if (requestRef.current?.id === operation.id) setBusy(false);
    }
  };

  const runSolari = async () => {
    if (!view) return;
    if (!LIVE_SOLARI_ENABLED) {
      setNotice("Live Solari is not enabled on this public demo. The complete fixture investigation remains available.");
      return;
    }
    setSolariBusy(true);
    setNotice(null);
    const poll = window.setInterval(() => {
      void apiClient.getSolari(view.portfolio_id).then(setSolariExecution).catch(() => undefined);
    }, 750);
    try { setSolariExecution(await apiClient.runSolari(view.portfolio_id)); }
    catch (error) { setNotice(safeMessage(error)); }
    finally { window.clearInterval(poll); setSolariBusy(false); }
  };

  return (
    <div className="shell closing-rescue-shell">
      <header className="topbar">
        <div className="brand-lockup"><div><p className="eyebrow">Physical-world closing intelligence</p><h1>Closing Rescue</h1><span>Septic Sentinel · specialist agent</span></div></div>
        <nav className="mode-nav" aria-label="Experience mode">
          <button className={publicCheckOpen ? "active" : ""} onClick={() => setPublicCheckOpen(true)}>Live record check</button>
          <button className={!publicCheckOpen && view ? "active" : ""} onClick={() => setPublicCheckOpen(false)}>Guided demo</button>
        </nav>
      </header>

      {notice && view && <div className="notice" role="status">{notice}</div>}
      {storageWarning && <div className="notice storage-warning" role="status">{storageWarning}</div>}

      {publicCheckOpen ? (
        <LiveRecordCheck onBack={() => setPublicCheckOpen(false)} />
      ) : !view ? (
        busy ? (
          <InvestigationExperience state="loading" />
        ) : notice ? (
          <InvestigationExperience state="error" message={notice} onRetry={() => void startJourney()} retryLabel="Start the rescue" />
        ) : (
          <InvestigationExperience state="empty" onStart={() => void startJourney()} onStartLive={() => setPublicCheckOpen(true)} />
        )
      ) : (
        <InvestigationExperience
          cut={projectInvestigation(view, story)}
          busy={busy}
          tokenAvailable={tokenAvailable}
          onDecide={(approve) => void decide(approve)}
          playback={{
            pause: () => controllerRef.current?.pause(),
            resume: () => controllerRef.current?.resume(),
            replay: () => controllerRef.current?.replay(),
            skip: () => controllerRef.current?.skipToResult(),
          }}
          solariExecution={solariExecution}
          solariBusy={solariBusy}
          solariEnabled={LIVE_SOLARI_ENABLED}
          onRunSolari={() => void runSolari()}
        />
      )}
    </div>
  );
}
