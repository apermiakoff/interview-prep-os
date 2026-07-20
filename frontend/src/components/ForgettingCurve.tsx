import type { MemoryState } from "../types";

export function ForgettingCurve({ memory }: { memory?: MemoryState }) {
  if (!memory) return <div className="empty-state">No memory evidence yet. Complete an attempt to create the first curve.</div>;
  const width = 720;
  const height = 250;
  const pad = 32;
  const points = memory.curve.map((point) => {
    const x = pad + (point.day / 30) * (width - pad * 2);
    const y = pad + (1 - point.value) * (height - pad * 2);
    return `${x},${y}`;
  }).join(" ");
  const dueDay = Math.max(0, Math.min(30, Math.round(memory.stability_days)));
  const dueX = pad + (dueDay / 30) * (width - pad * 2);

  return (
    <figure className="curve-card">
      <figcaption>
        <div><span className="eyebrow">Retrievability model</span><strong>{memory.title}</strong></div>
        <span className="confidence-badge">{memory.evidence_count} observation{memory.evidence_count === 1 ? "" : "s"}</span>
      </figcaption>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Estimated forgetting curve for ${memory.title}`}>
        {[0, .25, .5, .75, 1].map(value => {
          const y = pad + (1 - value) * (height - pad * 2);
          return <g key={value}><line className="chart-grid" x1={pad} y1={y} x2={width - pad} y2={y} /><text className="chart-label" x={4} y={y + 4}>{Math.round(value * 100)}%</text></g>;
        })}
        <line className="due-line" x1={dueX} y1={pad} x2={dueX} y2={height - pad} />
        <polyline className="curve-line" points={points} />
        <circle className="curve-now" cx={pad} cy={pad} r="5" />
        <text className="chart-label" x={dueX + 7} y={pad + 12}>review zone</text>
      </svg>
      <p>Stability {memory.stability_days.toFixed(1)} days · next retrieval {memory.next_due} · confidence remains {memory.evidence_count < 6 ? "early" : "developing"}.</p>
    </figure>
  );
}
