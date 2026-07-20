import type { Bootstrap } from "../types";

export function PatternsView({ data, navigate }: { data: Bootstrap; navigate: (route: string) => void }) {
  return (
    <main className="view page-shell" id="main-content">
      <div className="section-heading"><span className="eyebrow">Pattern library</span><h1>Recognition is a retrieval skill.</h1><p>Each pattern is organized around its trigger, brute-force bottleneck, invariant, implementation skeleton, and delayed evidence.</p></div>
      <section className="pattern-list">
        {data.patterns.map((pattern, index) => <article className="pattern-row" key={pattern.id}>
          <span className="pattern-index">{String(index + 1).padStart(2, "0")}</span>
          <div className="pattern-main"><span className="eyebrow">{pattern.id}</span><h2>{pattern.title}</h2><p>{pattern.description}</p><ul>{pattern.recognition_signals.map(signal => <li key={signal}>{signal}</li>)}</ul></div>
          <aside><span>Evidence</span><strong>{pattern.evidence_count}</strong><span>Independent</span><strong>{pattern.independent_count}</strong><span>Confidence</span><strong>{pattern.confidence}</strong><button className="text-link button-link" onClick={() => navigate("problems")}>Browse problem library →</button></aside>
        </article>)}
      </section>
      <div className="roadmap-note"><span className="eyebrow">Next pattern engines</span><p>Sliding window · binary search · backtracking · DP state modeling · union-find</p></div>
    </main>
  );
}
