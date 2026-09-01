import type { PortfolioScene } from "../presentation";

export function PortfolioOpening({ scene }: { scene: PortfolioScene }) {
  return <div className="scene scene-portfolio">
    <div className="portfolio-copy">
      <p className="scene-kicker"><span>01</span>{scene.label}</p>
      <p className="truth-chip">{scene.truthLabel}</p>
      <h2>{scene.headline}</h2>
      <p className="scene-deck">One specialist agent is reading the whole pipeline—then choosing the delay the team can still prevent.</p>
      <dl className="portfolio-facts">
        <div><dt>Pipeline</dt><dd>{scene.pipelineValue}</dd></div>
        <div><dt>Attention candidates</dt><dd>{scene.attentionCandidates}</dd></div>
        <div><dt>Estimated exposure</dt><dd>{scene.exposure}</dd></div>
      </dl>
    </div>
    <div className="portfolio-radar" aria-hidden="true">
      <div className="radar-copy"><span>SEPTIC SENTINEL</span><strong>SCANNING</strong></div>
      <div className="radar-orbit orbit-one"/><div className="radar-orbit orbit-two"/>
      <div className="loan-field">{Array.from({ length: 47 }, (_, index) => <i key={index} className={index === 46 ? "selected" : index < 4 ? "candidate" : ""}/>)}</div>
      <div className="scan-line"/>
    </div>
  </div>;
}
