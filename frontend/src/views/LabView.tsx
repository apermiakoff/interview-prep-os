import { AlgorithmVisualizer } from "../components/AlgorithmVisualizer";
import type { Bootstrap } from "../types";

export function LabView({ data }: { data: Bootstrap }) {
  const lesson = data.lesson;
  return (
    <main className="view page-shell" id="main-content">
      <div className="section-heading lab-heading"><span className="eyebrow">Visual Lab · {lesson.pattern.title}</span><h1>Alternate routes are the idea. Low-link is the measurement.</h1><p>Walk the semantic event trace. The animation is generated from algorithm state—not stored as a video.</p></div>
      <AlgorithmVisualizer lesson={lesson} />
      <section className="lesson-grid">
        <article><span className="eyebrow">Invariant</span><blockquote>{lesson.pattern.invariant}</blockquote><pre><code>{`visited non-parent:\n  low[u] = min(low[u], tin[v])\n\nreturned DFS child:\n  low[u] = min(low[u], low[v])\n\nbridge:\n  low[v] > tin[u]`}</code></pre></article>
        <article><span className="eyebrow">Implementation traps</span><ol>{lesson.pattern.failure_modes.map((mode: string) => <li key={mode}>{mode}</li>)}</ol><div className="retrieval-prompt"><strong>Close the visual, then reconstruct:</strong><p>build graph → tin/low → skip parent → recurse → merge child low → test strict bridge condition</p></div></article>
      </section>
    </main>
  );
}
