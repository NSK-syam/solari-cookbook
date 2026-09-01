import { useState } from "react";

import type { DocumentaryCut, InvestigationScene } from "../presentation";
import type { SolariExecutionView } from "../api";
import { CaseSelection } from "./CaseSelection";
import { ContradictionFinding } from "./ContradictionFinding";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { ExposureComparison } from "./ExposureComparison";
import { PortfolioOpening } from "./PortfolioOpening";
import { RescueApproval } from "./RescueApproval";
import { SpatialEvidence } from "./SpatialEvidence";
import { SolariExecutionRail } from "./SolariExecutionRail";

interface PlaybackActions {
  pause: () => void;
  resume: () => void;
  replay: () => void;
  skip: () => void;
}

interface ReadyProps {
  cut: DocumentaryCut;
  busy: boolean;
  tokenAvailable: boolean;
  onDecide: (approve: boolean) => void;
  playback: PlaybackActions;
  solariExecution?: SolariExecutionView | null;
  solariBusy?: boolean;
  onRunSolari?: () => void;
  state?: never;
  message?: never;
  onRetry?: never;
  onStart?: never;
}

interface BoundaryProps {
  cut?: never;
  busy?: never;
  tokenAvailable?: never;
  onDecide?: never;
  playback?: never;
  state: "loading" | "error" | "empty";
  message?: string;
  onRetry?: () => void;
  onStart?: () => void;
  retryLabel?: string;
}

export type InvestigationExperienceProps = ReadyProps | BoundaryProps;

const chapterLabels = [
  "Portfolio",
  "Selection",
  "Evidence",
  "Contradiction",
  "Exposure",
  "Approval",
] as const;

export function InvestigationExperience(props: InvestigationExperienceProps) {
  if (!props.cut) return <Boundary {...props} />;

  const { cut, busy, tokenAvailable, onDecide, playback, solariExecution, solariBusy, onRunSolari } = props;
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <main className="investigation-experience" data-chapter={cut.story.visibleChapter}>
      <aside className="investigation-rail">
        <div className="rail-case">
          <span>ACTIVE RESCUE</span>
          <strong>{cut.caseAddress}</strong>
        </div>
        <nav aria-label="Investigation chapters">
          {chapterLabels.map((label, index) => {
            const chapter = index + 1;
            const active = cut.story.visibleChapter === chapter;
            const complete = cut.story.visibleChapter > chapter;
            return (
              <div
                className={active ? "active" : complete ? "complete" : "pending"}
                key={label}
                aria-current={active ? "step" : undefined}
              >
                <span>{String(chapter).padStart(2, "0")}</span>
                <strong>{label}</strong>
                <i aria-hidden="true" />
              </div>
            );
          })}
        </nav>
        <button className="ledger-button" onClick={() => setDrawerOpen(true)}>
          Open evidence ledger
          <span>{cut.evidenceLedger.length}</span>
        </button>
      </aside>

      <section className="documentary-stage" aria-live="polite">
        <Scene
          scene={cut.activeScene}
          busy={busy}
          tokenAvailable={tokenAvailable}
          canShowApproval={cut.canShowApproval}
          onDecide={onDecide}
        />
        <footer className="documentary-controls">
          <div className="story-status">
            <span>{cut.story.replaying ? "PLAYING INVESTIGATION" : cut.completed ? "RESCUE COMPLETE" : "INVESTIGATION READY"}</span>
            <i aria-hidden="true" />
          </div>
          <div role="group" aria-label="Story playback controls">
            {cut.story.paused ? (
              <button onClick={playback.resume}>Resume story</button>
            ) : (
              <button onClick={playback.pause}>Pause story</button>
            )}
            <button onClick={playback.replay}>Replay investigation</button>
            <button onClick={playback.skip}>Skip to finding</button>
          </div>
        </footer>
      </section>

      <SolariExecutionRail execution={solariExecution ?? null} busy={solariBusy ?? false} onRun={onRunSolari ?? (() => undefined)} />

      {drawerOpen && <EvidenceDrawer items={cut.evidenceLedger} onClose={() => setDrawerOpen(false)} />}
    </main>
  );
}

function Scene({
  scene,
  busy,
  tokenAvailable,
  canShowApproval,
  onDecide,
}: {
  scene: InvestigationScene;
  busy: boolean;
  tokenAvailable: boolean;
  canShowApproval: boolean;
  onDecide: (approve: boolean) => void;
}) {
  switch (scene.kind) {
    case "portfolio":
      return <PortfolioOpening scene={scene} />;
    case "selection":
      return <CaseSelection scene={scene} />;
    case "evidence":
      return <SpatialEvidence scene={scene} />;
    case "contradiction":
      return <ContradictionFinding scene={scene} />;
    case "exposure":
      return <ExposureComparison scene={scene} />;
    case "approval":
      return (
        <RescueApproval
          scene={scene}
          busy={busy}
          tokenAvailable={tokenAvailable}
          canShowApproval={canShowApproval}
          onDecide={onDecide}
        />
      );
  }
}

function Boundary({
  state,
  message,
  onRetry,
  onStart,
  retryLabel,
}: BoundaryProps) {
  if (state === "loading") {
    return (
      <main className="experience-boundary loading-boundary" role="status">
        <div className="loading-orbit" aria-hidden="true"><i /><i /><i /></div>
        <p>SCANNING PORTFOLIO</p>
        <h2>Scanning 47 active loans…</h2>
        <span>Ranking urgency, evidence gaps, and preventable exposure.</span>
      </main>
    );
  }
  if (state === "error") {
    return (
      <main className="experience-boundary" role="alert">
        <p>INVESTIGATION INTERRUPTED</p>
        <h2>{message ?? "Closing Rescue could not complete the request."}</h2>
        <span>No external action was taken.</span>
        {onRetry && <button className="primary" onClick={onRetry}>{retryLabel ?? "Try again"}</button>}
      </main>
    );
  }
  return (
    <main className="experience-boundary empty-boundary">
      <p>ONE AGENT · FORTY-SEVEN CLOSINGS</p>
      <h2>Find the delay a human team can still prevent.</h2>
      <span>The agent selects the case, gathers cited physical evidence, and stops for approval before it acts.</span>
      <button className="primary" onClick={onStart}>Start the rescue</button>
    </main>
  );
}
