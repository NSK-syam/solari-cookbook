import type { ContradictionScene } from "../presentation";

export function ContradictionFinding({ scene }: { scene: ContradictionScene }) {
  return <div className="scene scene-contradiction">
    <div className="editorial-heading"><p className="scene-kicker"><span>04</span>{scene.label}</p><p className="truth-chip warning">{scene.truthLabel}</p><h2>{scene.headline}</h2><p className="scene-deck">The agent found a material disagreement in the file. It did not infer why.</p></div>
    <div className="record-spread">
      <article><header><span>SELLER SUBMISSION</span><small>Synthetic business data</small></header><p>“Septic system<br/>replaced in”</p><strong>{scene.sellerYear}</strong><footer>{scene.sellerSource}</footer></article>
      <div className="versus" aria-hidden="true"><span>{scene.gapYears}</span><small>YEAR<br/>GAP</small></div>
      <article className="permit-record"><header><span>LATEST PERMIT RECORD</span><small>External · cited</small></header><p>Latest recorded<br/>septic permit</p><strong>{scene.permitYear}</strong><footer>{scene.permitSource}{scene.citations.map((citation) => citation.href ? <a key={citation.id} href={citation.href} target="_blank" rel="noopener noreferrer">View source ↗</a> : null)}</footer></article>
    </div>
    <aside className="finding-note"><strong>{scene.findingLabel}</strong><p>{scene.summary} This requires resolution—not an allegation of fraud, failure, or unpermitted work.</p></aside>
  </div>;
}
