import { ForgettingCurve } from "../components/ForgettingCurve";
import type { Bootstrap } from "../types";

export function EvidenceView({ data }: { data: Bootstrap }) {
  const primaryMemory = data.memory[0];
  const outcomeEntries = [
    ["Independent", data.evidence.independent_count, "green"],
    ["Assisted", data.evidence.outcomes.yellow || 0, "yellow"],
    ["Solution needed", data.evidence.outcomes.red || 0, "red"],
    ["Skipped", data.evidence.outcomes.skipped || 0, "neutral"],
  ] as const;
  const maxOutcome = Math.max(1, ...outcomeEntries.map(([, count]) => count));
  const failures = Object.entries(data.evidence.failures).sort((a, b) => b[1] - a[1]);

  return (
    <main className="view page-shell" id="main-content">
      <div className="section-heading"><span className="eyebrow">Learning evidence</span><h1>Memory, without the vanity metrics.</h1><p>{data.evidence.count < 6 ? `Only ${data.evidence.count} observations exist. The interface shows early signals rather than inventing mastery.` : "Independent retrieval and delay determine progress—not raw Accepted totals."}</p></div>
      <section className="evidence-ledger">
        <article className="evidence-summary">
          <span className="eyebrow">Outcome evidence</span>
          <div className="outcome-bars">{outcomeEntries.map(([label, count, tone]) => <div className="bar-row" key={label}><span>{label}</span><div><i className={tone} style={{ width: `${(count / maxOutcome) * 100}%` }} /></div><strong>{count}</strong></div>)}</div>
          <p className="confidence-note">Confidence: <strong>{data.evidence.confidence}</strong> · public profile statistics are excluded.</p>
        </article>
        <article className="evidence-summary">
          <span className="eyebrow">Failure signals</span>
          <h2>{failures.length ? "What broke first" : "No blockers recorded"}</h2>
          {failures.length ? failures.map(([name, count]) => <div className="failure-line" key={name}><span>{name.replaceAll("_", " ")}</span><strong>{count}</strong></div>) : <p>Future Yellow and Red attempts will identify whether the miss was recognition, derivation, implementation, bugs, complexity, or communication.</p>}
        </article>
      </section>

      <ForgettingCurve memory={primaryMemory} />

      <section className="attempt-ledger">
        <div className="section-rule"><span>Immutable attempt ledger</span><span>{data.attempts.length} events</span></div>
        {data.attempts.length ? data.attempts.map(attempt => <article className="attempt-line" key={attempt.id}>
          <time>{attempt.occurred_on}</time><span className={`status-dot ${attempt.result}`} aria-label={attempt.result} />
          <div><strong>{attempt.title}</strong><p>{attempt.pattern_id || "pattern unclassified"}</p></div>
          <div className="attempt-facts"><span>{attempt.independent ? "independent" : "assisted"}</span><span>{attempt.highest_hint || "H0"}</span><span>{attempt.failure_tag || "none"}</span>{attempt.duration_minutes != null && <span>{attempt.duration_minutes}m</span>}</div>
        </article>) : <div className="empty-state">The first recorded attempt will start the evidence ledger.</div>}
      </section>
    </main>
  );
}
