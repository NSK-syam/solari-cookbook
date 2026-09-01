import type { SolariExecutionView, SolariStepReceipt } from "../api";

const products = [
  { id: "sandbox", label: "Sandbox", copy: "47-loan calculation manifest" },
  { id: "browser", label: "Browser", copy: "Recorded official permit capture" },
  { id: "desktop", label: "Desktop", copy: "Approval-gated form receipt" },
] as const;

export function SolariExecutionRail({ execution, busy, onRun }: { execution: SolariExecutionView | null; busy: boolean; onRun: () => void }) {
  return <aside className="solari-rail" aria-label="Solari execution receipts">
    <header><p>LIVE INFRASTRUCTURE</p><h2>Solari proof rail</h2><span>Three isolated products. One auditable rescue.</span></header>
    <ol>{products.map((product) => {
      const step = execution?.steps.find((item) => item.product === product.id);
      const status = step?.status ?? (product.id === "desktop" ? "blocked" : "pending");
      return <li key={product.id} className={status}>
        <div className="solari-step-title"><i aria-hidden="true"/><span>{product.label}</span><b>{status.replaceAll("_", " ")}</b></div>
        <p>{step?.detail ?? product.copy}</p>
        {step?.session_id && <code title={step.session_id}>session {step.session_id.slice(0, 10)}…</code>}
        <Artifacts step={step}/>
        {step?.failure_reason && <small>{step.failure_reason}</small>}
      </li>;
    })}</ol>
    <footer>
      <button className="solari-run" onClick={onRun} disabled={busy || execution?.status === "running"}>{busy ? "Running on Solari…" : execution ? "Run proof again" : "Run live Solari proof"}</button>
      <p>Desktop stays locked until the existing one-time human approval is consumed.</p>
    </footer>
  </aside>;
}

function Artifacts({ step }: { step?: SolariStepReceipt }) {
  if (!step?.artifacts.length) return null;
  return <div className="solari-artifacts">{step.artifacts.map((artifact) => artifact.url ? <a key={`${artifact.kind}-${artifact.label}`} href={artifact.url} target="_blank" rel="noopener noreferrer">{artifact.label} ↗</a> : null)}</div>;
}
