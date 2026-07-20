import { useEffect, useMemo, useState } from "react";
import type { Lesson, TraceEvent } from "../types";

type GraphState = {
  visited: Set<number>;
  treeEdges: Set<string>;
  backEdges: Set<string>;
  bridges: Set<string>;
  low: Record<number, number>;
  tin: Record<number, number>;
  activeNode?: number;
  activeEdge?: string;
};

const key = (a: number, b: number) => [Math.min(a, b), Math.max(a, b)].join("-");

function reduceTrace(events: TraceEvent[]): GraphState {
  const state: GraphState = { visited: new Set(), treeEdges: new Set(), backEdges: new Set(), bridges: new Set(), low: {}, tin: {} };
  for (const event of events) {
    state.activeNode = undefined;
    state.activeEdge = undefined;
    if (event.type === "visit_node" && event.node !== undefined) {
      state.visited.add(event.node); state.activeNode = event.node;
      if (event.tin !== undefined) state.tin[event.node] = event.tin;
      if (event.low !== undefined) state.low[event.node] = event.low;
    }
    if (event.type === "tree_edge" && event.from !== undefined && event.to !== undefined) {
      const edge = key(event.from, event.to); state.treeEdges.add(edge); state.activeEdge = edge;
    }
    if (event.type === "back_edge" && event.from !== undefined && event.to !== undefined) {
      const edge = key(event.from, event.to); state.backEdges.add(edge); state.activeEdge = edge;
    }
    if (event.type === "merge_low" && event.node !== undefined && event.new !== undefined) {
      state.low[event.node] = event.new; state.activeNode = event.node;
    }
    if (event.type === "bridge_check" && event.from !== undefined && event.to !== undefined) {
      const edge = key(event.from, event.to); state.activeEdge = edge;
      if (event.bridge) state.bridges.add(edge);
    }
  }
  return state;
}

export function AlgorithmVisualizer({ lesson }: { lesson: Lesson }) {
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(false);
  const event = lesson.trace[step];
  const state = useMemo(() => reduceTrace(lesson.trace.slice(0, step + 1)), [lesson, step]);

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      setStep(current => {
        if (current >= lesson.trace.length - 1) { setPlaying(false); return current; }
        return current + 1;
      });
    }, 1500);
    return () => window.clearInterval(id);
  }, [playing, lesson.trace.length]);

  return (
    <section className="visualizer-shell">
      <div className="visualizer-stage">
        <svg viewBox="0 0 760 300" role="img" aria-label="Animated low-link DFS graph">
          {lesson.graph.edges.map(([a, b]) => {
            const left = lesson.graph.nodes.find(node => node.id === a)!;
            const right = lesson.graph.nodes.find(node => node.id === b)!;
            const edge = key(a, b);
            const classes = ["graph-edge", state.treeEdges.has(edge) && "tree", state.backEdges.has(edge) && "back", state.bridges.has(edge) && "bridge", state.activeEdge === edge && "active"].filter(Boolean).join(" ");
            return <line key={edge} className={classes} x1={left.x} y1={left.y} x2={right.x} y2={right.y} />;
          })}
          {lesson.graph.nodes.map(node => (
            <g key={node.id} className={`graph-node ${state.visited.has(node.id) ? "visited" : ""} ${state.activeNode === node.id ? "active" : ""}`} transform={`translate(${node.x} ${node.y})`}>
              <circle r="27" />
              <text className="node-id" textAnchor="middle" dy="5">{node.id}</text>
              {state.tin[node.id] !== undefined && <text className="node-state" textAnchor="middle" y="44">{state.tin[node.id]} / {state.low[node.id]}</text>}
            </g>
          ))}
        </svg>
        <div className="trace-legend"><span><i className="tree" />DFS tree</span><span><i className="back" />Back edge</span><span><i className="bridge" />Bridge</span><span><code>tin / low</code></span></div>
      </div>
      <aside className="trace-narration">
        <span className="eyebrow">Event {step + 1} / {lesson.trace.length}</span>
        <h3>{event.title || event.type.replaceAll("_", " ")}</h3>
        <p>{event.copy}</p>
        <div className="trace-controls">
          <button className="icon-button" aria-label="Previous event" onClick={() => setStep(value => Math.max(0, value - 1))} disabled={step === 0}>←</button>
          <button className="button primary" onClick={() => setPlaying(value => !value)}>{playing ? "Pause trace" : "Play trace"}</button>
          <button className="icon-button" aria-label="Next event" onClick={() => setStep(value => Math.min(lesson.trace.length - 1, value + 1))} disabled={step === lesson.trace.length - 1}>→</button>
        </div>
        <input className="trace-slider" aria-label="Trace position" type="range" min="0" max={lesson.trace.length - 1} value={step} onChange={event => { setPlaying(false); setStep(Number(event.target.value)); }} />
      </aside>
    </section>
  );
}
