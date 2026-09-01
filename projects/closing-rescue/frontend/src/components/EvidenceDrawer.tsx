import { useEffect, useRef } from "react";
import type { EvidencePresentation } from "../presentation";

export function EvidenceDrawer({ items, onClose }: { items: EvidencePresentation[]; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { closeRef.current?.focus(); const escape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); }; window.addEventListener("keydown", escape); return () => window.removeEventListener("keydown", escape); }, [onClose]);
  return <div className="drawer-scrim" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose(); }}>
    <aside className="evidence-drawer" role="dialog" aria-modal="true" aria-labelledby="evidence-ledger-heading">
      <header><div><p>Evidence ledger</p><h2 id="evidence-ledger-heading">Sources behind the finding</h2></div><button ref={closeRef} onClick={onClose} aria-label="Close evidence ledger">×</button></header>
      <p className="drawer-intro">External facts retain their source and retrieval time. Synthetic business inputs are labeled elsewhere in the investigation.</p>
      <ol>{items.map((item) => <li key={item.id}><div><span>{item.truthLabel}</span><strong>{item.source} · {item.kind}</strong><time>{item.timestamp}</time></div><small>{item.status}</small>{item.citations.map((citation) => citation.href ? <a key={citation.id} href={citation.href} target="_blank" rel="noopener noreferrer">{citation.label} ↗</a> : <span key={citation.id}>Stored citation</span>)}</li>)}</ol>
    </aside>
  </div>;
}
