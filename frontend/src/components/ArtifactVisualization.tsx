import { useMemo, useState } from "react";
import type { VisualizationArtifact } from "../types";

const SUPPORTED = new Set(["graph-trace@1", "array-trace@1", "state-trace@1", "array-window@1", "tree-traversal@1", "grid-search@1", "dp-table@1", "call-stack@1"]);
export function ArtifactVisualization({ artifact }: { artifact: VisualizationArtifact }) {
  const valid = useMemo(() => {
    const ids = new Set(artifact.entities.filter(entity => /^[A-Za-z0-9_.:-]{1,80}$/.test(entity.id)).map(entity => entity.id));
    return artifact.events.filter(event => event.targets.length > 0 && event.targets.every(id => ids.has(id)));
  }, [artifact]);
  const [step, setStep] = useState(0); const event = valid[step]; const active = new Set(event?.targets || []);
  return <section className="semantic-viz" aria-label={`${artifact.title} visualization`}>
    <header><div><span className="eyebrow">Validated semantic events</span><h3>{artifact.title}</h3></div><span className="ai-provenance">{SUPPORTED.has(artifact.renderer) ? artifact.renderer : `generic · ${artifact.renderer}`}</span></header>
    <div className={`semantic-stage ${artifact.renderer.startsWith("graph") ? "graph" : "sequence"}`}>
      {artifact.entities.map(entity => <div key={entity.id} className={`semantic-entity ${entity.kind} ${active.has(entity.id) ? "active" : ""}`}><strong>{entity.label}</strong>{Object.keys(entity.data).length > 0 && <small>{Object.entries(entity.data).map(([key, value]) => `${key}: ${String(value)}`).join(" · ")}</small>}</div>)}
      {!artifact.entities.length && <p>No semantic entities were returned.</p>}
    </div>
    <p className="viz-note">{event ? `${event.op}: ${event.note || event.targets.join(", ")}` : "Initial state"}</p>
    <div className="step-controls"><button aria-label="Previous visualization step" disabled={step === 0} onClick={() => setStep(value => value - 1)}>←</button><span>Step {valid.length ? step + 1 : 0} / {valid.length}</span><button aria-label="Next visualization step" disabled={!valid.length || step >= valid.length - 1} onClick={() => setStep(value => value + 1)}>→</button></div>
  </section>;
}
