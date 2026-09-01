import type { SelectionScene } from "../presentation";

export function CaseSelection({ scene }: { scene: SelectionScene }) {
  return <div className="scene scene-selection">
    <div className="selection-index" aria-hidden="true"><span>47</span><i>→</i><strong>01</strong></div>
    <div className="selection-copy">
      <p className="scene-kicker"><span>02</span>{scene.label}</p>
      <p className="truth-chip">{scene.truthLabel}</p>
      <h2>The agent chose<br/><em>{scene.address}</em></h2>
      <p className="scene-deck">It closes in {scene.daysToClose} days and carries the highest preventable exposure in the portfolio.</p>
      <div className="selection-statline"><strong>{scene.loanAmount}</strong><span>loan amount</span><strong>{scene.preventable}</strong><span>preventable exposure</span></div>
      <details className="rationale"><summary>Why this file ranked first</summary><p>{scene.rationale}</p><dl><div><dt>Urgency</dt><dd>{scene.urgency}/100</dd></div><div><dt>Window</dt><dd>{scene.daysToClose} days</dd></div></dl></details>
    </div>
  </div>;
}
