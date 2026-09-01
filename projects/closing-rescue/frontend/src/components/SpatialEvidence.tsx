import type { EvidenceScene } from "../presentation";
import { ApproximatePropertyMap } from "./ApproximatePropertyMap";

export function SpatialEvidence({ scene }: { scene: EvidenceScene }) {
  return <div className="scene scene-evidence">
    <ApproximatePropertyMap />
    <div className="evidence-copy">
      <p className="scene-kicker"><span>03</span>{scene.label}</p>
      <p className="truth-chip">{scene.truthLabel}</p>
      <h2>Ground truth,<br/>one source at a time.</h2>
      <p className="scene-deck">Mireye resolves the physical place. Permit and weather records join only after that identity holds.</p>
      <ol className="source-sequence">
        {scene.items.map((item, index) => <li key={item.id}>
          <span className="source-number">0{index + 1}</span><div><strong>{item.source}</strong><small>{item.kind} · {item.status}</small><time>{item.timestamp}</time></div>
          {item.citations.map((citation) => citation.href ? <a key={citation.id} href={citation.href} target="_blank" rel="noopener noreferrer" aria-label={`${citation.label}, opens cited source in a new tab`}>Source ↗</a> : <span key={citation.id} className="citation-unlinked">Stored citation</span>)}
        </li>)}
      </ol>
    </div>
  </div>;
}
