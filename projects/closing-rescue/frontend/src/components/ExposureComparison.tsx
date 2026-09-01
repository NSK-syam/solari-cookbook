import type { ExposureScene } from "../presentation";

export function ExposureComparison({ scene }: { scene: ExposureScene }) {
  return <div className="scene scene-exposure">
    <div className="exposure-heading"><p className="scene-kicker"><span>05</span>{scene.label}</p><p className="truth-chip">{scene.truthLabel}</p><h2>There is still time<br/>to change the outcome.</h2></div>
    <div className="exposure-ledger">
      <article className="do-nothing"><p>DO NOTHING</p><strong>{scene.withoutAction}</strong><span>estimated exposure</span><code>{scene.formulaLines[0]}</code></article>
      <div className="exposure-arrow" aria-hidden="true">→</div>
      <article className="do-rescue"><p>RESCUE</p><strong>{scene.afterAction}</strong><span>projected residual exposure</span><code>{scene.formulaLines[1]}</code></article>
    </div>
    <div className="preventable"><span>Estimated preventable exposure</span><strong>{scene.preventable}</strong></div>
    <details className="formula-disclosure"><summary>Show assumptions and limitations</summary><p>{scene.disclaimer}</p>{scene.limitations.map((item) => <p key={item}>{item}</p>)}</details>
  </div>;
}
