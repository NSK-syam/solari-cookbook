import type { EvidenceScene } from "../presentation";

export function SpatialEvidence({ scene }: { scene: EvidenceScene }) {
  return <div className="scene scene-evidence">
    <div className="spatial-stage" aria-hidden="true">
      <svg viewBox="0 0 760 650" role="presentation">
        <defs><linearGradient id="land" x1="0" x2="1"><stop offset="0" stopColor="#263e35"/><stop offset="1" stopColor="#193129"/></linearGradient><filter id="soft"><feGaussianBlur stdDeviation="14"/></filter></defs>
        <path d="M-30 530C120 420 190 480 290 355S510 238 790 34V680H-30Z" fill="url(#land)"/>
        <path d="M-40 390C95 360 167 262 278 270s187-87 244-183 137-77 270-128" fill="none" stroke="#78988a" strokeWidth="2" opacity=".5"/>
        <path d="M20 610C208 515 263 483 323 392s162-111 218-167S641 73 777 12" fill="none" stroke="#c7d9cb" strokeWidth="22" opacity=".08"/>
        <circle cx="410" cy="314" r="98" fill="#bbff71" opacity=".08" filter="url(#soft)"/><circle cx="410" cy="314" r="12" fill="#d6ff86"/><circle cx="410" cy="314" r="42" fill="none" stroke="#d6ff86" opacity=".65"/><circle cx="410" cy="314" r="78" fill="none" stroke="#d6ff86" opacity=".18"/>
        <path d="M410 246V180M478 314h95M410 382v87M342 314h-92" stroke="#d6ff86" strokeWidth="1" strokeDasharray="4 6" opacity=".45"/>
      </svg>
      <div className="coordinate-label"><span>RESOLVED PROPERTY</span><strong>91 MARSH ROAD</strong><small>One parcel · cited joins only</small></div>
    </div>
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
