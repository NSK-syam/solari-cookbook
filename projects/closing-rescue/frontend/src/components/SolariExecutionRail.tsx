import type { SolariExecutionView, SolariStepReceipt } from "../api";

const products = [
  { id: "sandbox", label: "Sandbox", copy: "47-loan calculation manifest" },
  { id: "browser", label: "Browser", copy: "Recorded official permit capture" },
  { id: "desktop", label: "Desktop", copy: "Approval-gated form receipt" },
] as const;

const publicProofSteps: SolariStepReceipt[] = [
  {
    product: "sandbox",
    status: "succeeded",
    session_id: null,
    detail: "47 loans verified in an isolated Solari microVM.",
    started_at: null,
    completed_at: null,
    artifacts: [{
      kind: "manifest",
      label: "Open calculation manifest",
      url: "/proof/sandbox-manifest-bc4eed363440d4f5.json",
      sha256: "bc4eed363440d4f5c598becae30cea65e385a2e3992d8f9c0edae3fc0f631285",
      media_type: "application/json",
    }],
    failure_reason: null,
  },
  {
    product: "browser",
    status: "succeeded",
    session_id: null,
    detail: "Official Delaware permit captured; sensitive fields redacted.",
    started_at: null,
    completed_at: null,
    artifacts: [{
      kind: "screenshot",
      label: "View redacted capture",
      url: "/proof/permit-record-redacted-c6f2c45ab0f8dee2.png",
      sha256: "c6f2c45ab0f8dee2292fbc9fe880c45993297fb3109791f6b5ef7a8551ab3f81",
      media_type: "image/png",
    }],
    failure_reason: null,
  },
  {
    product: "desktop",
    status: "succeeded",
    session_id: null,
    detail: "Simulation-only form completed after the human approval gate.",
    started_at: null,
    completed_at: null,
    artifacts: [{
      kind: "receipt",
      label: "View desktop receipt",
      url: "/proof/desktop-form-receipt-16f16b9891a9e289.png",
      sha256: "16f16b9891a9e2894e6a62bcb747f83536685e65a6c2642240e62899d18908da",
      media_type: "image/png",
    }],
    failure_reason: null,
  },
];

export function SolariExecutionRail({ execution, busy, enabled, onRun }: { execution: SolariExecutionView | null; busy: boolean; enabled: boolean; onRun: () => void }) {
  return <aside className="solari-rail" aria-label="Solari execution receipts">
    <header><p>{enabled ? "LIVE INFRASTRUCTURE" : "VERIFIED SOLARI RECEIPTS"}</p><h2>Solari proof rail</h2><span>{enabled ? "Three isolated products. One auditable rescue." : "Live walkthrough passed · sanitized artifacts are public."}</span></header>
    <ol>{products.map((product) => {
      const steps = enabled ? execution?.steps ?? [] : publicProofSteps;
      const step = steps.find((item) => item.product === product.id);
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
      {enabled ? <button className="solari-run" onClick={onRun} disabled={busy || execution?.status === "running"}>{busy ? "Running on Solari…" : execution ? "Run proof again" : "Run live Solari proof"}</button> : <div className="solari-verified" role="status"><span aria-hidden="true">✓</span> Live walkthrough verified</div>}
      <p>{enabled ? "Desktop stays locked until the existing one-time human approval is consumed." : "Live reruns are disabled on this keyless demo. These receipts come from the successful September 1 walkthrough."}</p>
    </footer>
  </aside>;
}

function Artifacts({ step }: { step?: SolariStepReceipt }) {
  if (!step?.artifacts.length) return null;
  return <div className="solari-artifacts">{step.artifacts.map((artifact) => artifact.url ? <a key={`${artifact.kind}-${artifact.label}`} href={artifact.url} target="_blank" rel="noopener noreferrer">{artifact.label} ↗</a> : null)}</div>;
}
