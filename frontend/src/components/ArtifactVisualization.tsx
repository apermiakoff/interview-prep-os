import { useEffect, useMemo, useRef, useState, type ComponentType, type KeyboardEvent } from "react";
import type { VisualEntity, VisualEvent, VisualizationArtifact } from "../types";
import {
  createGraphModel, dsuGroups, GRAPH_HEIGHT, GRAPH_RENDERER_V1, GRAPH_RENDERER_V2, GRAPH_WIDTH, replayGraph,
  type GraphEdge, type GraphModel, type GraphSnapshot,
} from "../visualization/graphTrace";
import "../visualization/visualization.css";

const SAFE_ID = /^[A-Za-z0-9_.:-]{1,80}$/;

function edgeClass(edge: GraphEdge, snapshot: GraphSnapshot): string {
  return [
    "graph-edge",
    snapshot.visited.has(edge.id) && "is-visited",
    snapshot.selected.has(edge.id) && "is-selected",
    snapshot.comparing.has(edge.id) && "is-comparing",
    snapshot.accepted.has(edge.id) && "is-accepted",
    snapshot.rejected.has(edge.id) && "is-rejected",
  ].filter(Boolean).join(" ");
}

function GraphCanvas({ model, snapshot, title }: { model: GraphModel; snapshot: GraphSnapshot; title: string }) {
  const positions = new Map(model.nodes.map((node) => [node.id, node]));
  return <div className="graph-canvas">
    <svg className="graph-svg" viewBox={`0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}`} role="img" aria-label={`${title}, weighted graph`}>
      <title>{title}</title>
      <g className="graph-edges" aria-label="Weighted edges">
        {model.edges.map((edge) => {
          if (snapshot.hidden.has(edge.id)) return null;
          const from = positions.get(edge.from)!; const to = positions.get(edge.to)!;
          const midX = (from.x + to.x) / 2; const midY = (from.y + to.y) / 2;
          return <g key={edge.id} className={edgeClass(edge, snapshot)} data-entity-id={edge.id} aria-label={`${edge.label}, weight ${edge.weight}`}>
            <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} />
            <rect className="edge-weight-bg" x={midX - 18} y={midY - 13} width="36" height="26" rx="8" />
            <text className="edge-weight" x={midX} y={midY} dy="0.35em" textAnchor="middle">{edge.weight}</text>
          </g>;
        })}
      </g>
      <g className="graph-nodes" aria-label="Vertices">
        {model.nodes.map((node) => snapshot.hidden.has(node.id) ? null :
          <g key={node.id} className={`graph-node ${snapshot.visited.has(node.id) ? "is-visited" : ""} ${snapshot.selected.has(node.id) ? "is-selected" : ""}`} data-entity-id={node.id} transform={`translate(${node.x} ${node.y})`} aria-label={`Vertex ${node.label}`}>
            <circle r="25" /><text textAnchor="middle" dy="0.35em">{node.label}</text>
          </g>)}
      </g>
    </svg>
  </div>;
}

function PhaseTimeline({ model, snapshot }: { model: GraphModel; snapshot: GraphSnapshot }) {
  if (!model.frames.length) return null;
  return <section className="viz-inspector viz-phases" aria-label="Phase timeline">
    <h4>Phase timeline</h4>
    <ol>{model.frames.map((frame) => <li key={frame.id} className={`${snapshot.phase === frame.id ? "is-current" : ""} ${snapshot.completed.has(frame.id) ? "is-complete" : ""}`} aria-current={snapshot.phase === frame.id ? "step" : undefined}>
      <strong>{frame.label}</strong>{frame.data.goal !== undefined && frame.data.goal !== null && <span>{String(frame.data.goal)}</span>}
    </li>)}</ol>
  </section>;
}

function Inspector({ model, snapshot }: { model: GraphModel; snapshot: GraphSnapshot }) {
  const groups = dsuGroups(snapshot, model);
  return <div className="viz-inspectors">
    {model.renderer === GRAPH_RENDERER_V2 && <PhaseTimeline model={model} snapshot={snapshot} />}
    <section className="viz-inspector" aria-label="Metrics"><h4>Metrics</h4>
      {model.items.length ? <dl>{model.items.map((item) => !snapshot.hidden.has(item.id) && <div key={item.id}><dt>{item.label}</dt><dd>{snapshot.metrics.get(item.id) ?? "—"}</dd></div>)}</dl> : <p>No metrics</p>}
    </section>
    {model.renderer === GRAPH_RENDERER_V2 && <section className="viz-inspector" aria-label="Disjoint set inspector"><h4>Disjoint sets</h4>
      <ul>{groups.map((group, index) => <li key={`${index}-${group.join("-")}`}>{group.join(" · ")}</li>)}</ul>
    </section>}
  </div>;
}

function Playback({ step, count, playing, setPlaying, seek }: { step: number; count: number; playing: boolean; setPlaying: (value: boolean) => void; seek: (value: number) => void }) {
  const last = Math.max(0, count - 1);
  return <div className="viz-playback" aria-label="Visualization playback controls">
    <button type="button" aria-label="Previous visualization step" disabled={step === 0} onClick={() => seek(step - 1)}>←</button>
    <button type="button" aria-label={playing ? "Pause visualization" : "Play visualization"} disabled={last === 0} onClick={() => setPlaying(!playing)}>{playing ? "Pause" : "Play"}</button>
    <button type="button" aria-label="Next visualization step" disabled={step === last} onClick={() => seek(step + 1)}>→</button>
    <label className="viz-scrubber"><span>Timeline</span><input aria-label="Visualization step" type="range" min="0" max={last} value={step} onChange={(event) => seek(Number(event.currentTarget.value))} /></label>
    <output aria-live="polite">Step {step} / {last}</output>
  </div>;
}

function GraphTrace({ artifact }: { artifact: VisualizationArtifact }) {
  const model = useMemo(() => createGraphModel(artifact), [artifact]);
  const snapshots = useMemo(() => replayGraph(model), [model]);
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const rootRef = useRef<HTMLElement>(null);
  const last = snapshots.length - 1;
  const seek = (value: number) => setStep(Math.max(0, Math.min(last, value)));
  const setPlayback = (value: boolean) => {
    if (value && step >= last) setStep(0);
    setPlaying(value);
  };

  useEffect(() => { setStep(0); setPlaying(false); }, [artifact]);
  useEffect(() => {
    if (!playing) return;
    if (step >= last) { setPlaying(false); return; }
    const timer = window.setTimeout(() => setStep((value) => Math.min(last, value + 1)), 850);
    return () => window.clearTimeout(timer);
  }, [playing, step, last]);

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.target !== rootRef.current) return;
    let next: number | undefined;
    if (event.key === "ArrowLeft") next = step - 1;
    if (event.key === "ArrowRight") next = step + 1;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = last;
    if (event.key === "PageUp") next = step - 5;
    if (event.key === "PageDown") next = step + 5;
    if (event.key === " " || event.key === "Spacebar") { event.preventDefault(); setPlayback(!playing); return; }
    if (next !== undefined) { event.preventDefault(); seek(next); }
  };
  const snapshot = snapshots[step];
  const note = snapshot.event ? snapshot.event.note || `${snapshot.event.op}: ${snapshot.event.targets.map((id) => model.labels.get(id) ?? id).join(", ")}` : "Initial graph state";

  return <section ref={rootRef} className="semantic-viz graph-runtime" aria-label={`${artifact.title} visualization`} tabIndex={0} onKeyDown={onKeyDown}>
    <header><div><span className="eyebrow">Semantic graph trace</span><h3>{artifact.title}</h3></div><span className="ai-provenance">{artifact.renderer}</span></header>
    {model.nodes.length ? <>
      <Playback step={step} count={snapshots.length} playing={playing} setPlaying={setPlayback} seek={seek} />
      <GraphCanvas model={model} snapshot={snapshot} title={artifact.title} />
      <div className="viz-legend" aria-label="Graph legend"><span className="visit">Visited</span><span className="selected">Selected</span><span className="compare">Comparing</span>{model.renderer === GRAPH_RENDERER_V2 && <><span className="accept">Accepted</span><span className="reject">Rejected</span></>}<span className="exclude">Hidden</span></div>
      <p className="viz-note" aria-live="polite">{note}</p>
      <Inspector model={model} snapshot={snapshot} />
      <p className="viz-key-help">Keyboard: ←/→ step · Home/End jump · Page Up/Down skip · Space play/pause</p>
    </> : <p className="viz-empty">This graph contains no valid vertices to draw.</p>}
  </section>;
}

interface GenericSnapshot {
  hidden: Set<string>;
  active: Set<string>;
  values: Map<string, string>;
  event: VisualEvent | null;
}

function genericModel(artifact: VisualizationArtifact) {
  const entities: VisualEntity[] = [];
  const seen = new Set<string>();
  for (const entity of artifact.entities) {
    if (SAFE_ID.test(entity.id) && !seen.has(entity.id)) { entities.push(entity); seen.add(entity.id); }
  }
  const events = artifact.events.filter((event) => event.targets.length > 0 && event.targets.every((id) => seen.has(id)));
  const initial: GenericSnapshot = {
    hidden: new Set(), active: new Set(),
    values: new Map(entities.flatMap((entity) => entity.data.value === undefined || entity.data.value === null ? [] : [[entity.id, String(entity.data.value)]])),
    event: null,
  };
  const snapshots = [initial];
  for (const event of events) {
    const previous = snapshots[snapshots.length - 1];
    const next: GenericSnapshot = {
      hidden: new Set(previous.hidden), active: new Set(event.targets), values: new Map(previous.values), event,
    };
    for (const id of event.targets) {
      if (event.op === "show") next.hidden.delete(id);
      if (event.op === "hide") next.hidden.add(id);
      if (event.op === "update") next.values.set(id, event.value === undefined || event.value === null ? "—" : String(event.value));
    }
    snapshots.push(next);
  }
  return { entities, snapshots, labels: new Map(entities.map((entity) => [entity.id, entity.label])) };
}

function GenericPlayback({ artifact, unsupported = false }: { artifact: VisualizationArtifact; unsupported?: boolean }) {
  const model = useMemo(() => genericModel(artifact), [artifact]);
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const rootRef = useRef<HTMLElement>(null);
  const last = model.snapshots.length - 1;
  const seek = (value: number) => setStep(Math.max(0, Math.min(last, value)));
  const setPlayback = (value: boolean) => {
    if (value && step >= last) setStep(0);
    setPlaying(value);
  };
  useEffect(() => { setStep(0); setPlaying(false); }, [artifact]);
  useEffect(() => {
    if (!playing) return;
    if (step >= last) { setPlaying(false); return; }
    const timer = window.setTimeout(() => setStep((value) => Math.min(last, value + 1)), 850);
    return () => window.clearTimeout(timer);
  }, [playing, step, last]);
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.target !== rootRef.current) return;
    let next: number | undefined;
    if (event.key === "ArrowLeft") next = step - 1;
    if (event.key === "ArrowRight") next = step + 1;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = last;
    if (event.key === "PageUp") next = step - 5;
    if (event.key === "PageDown") next = step + 5;
    if (event.key === " " || event.key === "Spacebar") { event.preventDefault(); setPlayback(!playing); return; }
    if (next !== undefined) { event.preventDefault(); seek(next); }
  };
  const snapshot = model.snapshots[step];
  const note = snapshot.event
    ? snapshot.event.note || `${snapshot.event.op}: ${snapshot.event.targets.map((id) => model.labels.get(id) ?? id).join(", ")}`
    : "Initial semantic state";
  return <section ref={rootRef} className="semantic-viz generic-viz" aria-label={`${artifact.title} visualization`} tabIndex={0} onKeyDown={onKeyDown}>
    <header><div><span className="eyebrow">Semantic playback</span><h3>{artifact.title}</h3></div><span className="ai-provenance">{unsupported ? "Unsupported renderer" : artifact.renderer}</span></header>
    {unsupported && <div className="viz-fallback" role="note"><strong>No registered renderer is available for “{artifact.renderer}”.</strong><p>The semantic events are replayed as safe text.</p></div>}
    <Playback step={step} count={model.snapshots.length} playing={playing} setPlaying={setPlayback} seek={seek} />
    {model.entities.length ? <ul className="generic-entities">{model.entities.map((entity) => snapshot.hidden.has(entity.id) ? null : <li key={entity.id} className={snapshot.active.has(entity.id) ? "is-active" : ""} data-entity-id={entity.id}><span>{entity.kind}</span><strong>{entity.label}</strong>{snapshot.values.has(entity.id) && <output>{snapshot.values.get(entity.id)}</output>}</li>)}</ul> : <p className="viz-empty">No semantic entities were returned.</p>}
    <p className="viz-note" aria-live="polite">{note}</p>
    <p className="viz-key-help">Keyboard: ←/→ step · Home/End jump · Page Up/Down skip · Space play/pause</p>
  </section>;
}

const GenericRenderer = ({ artifact }: { artifact: VisualizationArtifact }) => <GenericPlayback artifact={artifact} />;
const RENDERERS: Record<string, ComponentType<{ artifact: VisualizationArtifact }>> = {
  [GRAPH_RENDERER_V1]: GraphTrace,
  [GRAPH_RENDERER_V2]: GraphTrace,
  "array-window@1": GenericRenderer,
  "tree-traversal@1": GenericRenderer,
  "grid-search@1": GenericRenderer,
  "dp-table@1": GenericRenderer,
  "call-stack@1": GenericRenderer,
};

export function ArtifactVisualization({ artifact }: { artifact: VisualizationArtifact }) {
  const Renderer = RENDERERS[artifact.renderer];
  return Renderer ? <Renderer artifact={artifact} /> : <GenericPlayback artifact={artifact} unsupported />;
}
