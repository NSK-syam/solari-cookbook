import type { ApprovalScene } from "../presentation";

interface Props { scene: ApprovalScene; busy: boolean; tokenAvailable: boolean; canShowApproval: boolean; onDecide: (approve: boolean) => void }

export function RescueApproval({ scene, busy, tokenAvailable, canShowApproval, onDecide }: Props) {
  const resumeLabel = scene.phase === "succeeded" ? "Resume and finalize rescue" : "Resume approved rescue";
  const resumable = scene.phase === "approved" || scene.phase === "authorized" || scene.phase === "running" || scene.phase === "succeeded";
  return <div className="scene scene-approval">
    <div className="approval-copy">
      <p className="scene-kicker"><span>06</span>{scene.label}</p><p className="truth-chip">{scene.truthLabel}</p>
      <h2>{scene.phase === "pending" ? "A human decides what happens next." : scene.statusHeading}</h2><p className="scene-deck">{scene.statusCopy}</p>
      {scene.phase === "pending" && canShowApproval && <div className="approval-actions" role="group" aria-label="Human approval checkpoint"><button className="primary" onClick={() => onDecide(true)} disabled={busy || !tokenAvailable}>{scene.actionLabel}</button><button className="text-button" onClick={() => onDecide(false)} disabled={busy || !tokenAvailable}>Reject rescue</button></div>}
      {resumable && canShowApproval && <button className="primary" onClick={() => onDecide(true)} disabled={busy || !tokenAvailable}>{resumeLabel}</button>}
      {!tokenAvailable && (scene.phase === "pending" || resumable) && <p className="token-note">Approval token is unavailable. Reloaded evidence remains readable, but approval cannot be bypassed.</p>}
    </div>
    <article className="appointment-ticket">
      <header><span>ONLY VIABLE WINDOW</span><small>Simulation only</small></header>
      <div className="ticket-time"><span>{scene.appointment.split(",")[0]}</span><strong>{scene.appointment}</strong></div>
      <div className="ticket-vendor"><span>{scene.serviceType}</span><h3>{scene.vendorName}</h3><strong>{scene.price}</strong></div>
      <footer><span>Approved vendor</span><span>No payment · no real booking</span></footer>
    </article>
    {scene.phase === "completed" && <FinalMemo scene={scene}/>}
  </div>;
}

function FinalMemo({ scene }: { scene: ApprovalScene }) {
  return <article className="final-memo"><p>CLOSING RESCUE · OUTCOME MEMO</p><h3>The window is protected.</h3><p>{scene.statusCopy}</p><dl><div><dt>Action</dt><dd>Simulated inspection booking</dd></div><div><dt>Control</dt><dd>Human approved · one-time token consumed</dd></div></dl><small>Every fact remains linked to its stored source and timestamp.</small></article>;
}
