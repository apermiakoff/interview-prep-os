import type { Bootstrap } from "../types";

export function TodayView({ data, navigate }: { data: Bootstrap; navigate: (route: string) => void }) {
  const active = data.active_assignment;
  const due = data.reviews.filter(review => review.due_on <= data.today).slice(0, 2);
  const previous = active ? data.attempts.find(attempt => attempt.problem_id === active.problem_id) : undefined;
  const memory = active ? data.memory.find(item => item.problem_id === active.problem_id) : undefined;

  if (!active) return (
    <main className="view page-shell" id="main-content">
      <div className="section-heading"><span className="eyebrow">Queue clear</span><h1>No active assignment.</h1><p>Your next daily selection will appear here.</p></div>
    </main>
  );

  return (
    <main className="view page-shell" id="main-content">
      <div className="section-rule"><span>{active.date_label}</span><span>{new Date(`${data.today}T12:00:00`).toLocaleDateString("en", { weekday: "long", month: "long", day: "numeric" })}</span></div>
      <section className="assignment-hero reveal">
        <div className="assignment-copy">
          <span className="mode-tag">{active.mode.replaceAll("_", " ")}</span>
          <p className="problem-number">#{active.leetcode_id || "—"}</p>
          <h1>{active.title}</h1>
          <p className="hero-lede">{active.goal}</p>
          <div className="hero-actions">
            <button className="button primary large" onClick={() => navigate("solve")}>Begin focused attempt <span>→</span></button>
            {active.url && <a className="text-link" href={active.url} target="_blank" rel="noreferrer">Open problem ↗</a>}
          </div>
        </div>
        <aside className="briefing-rail">
          <div><span>Timebox</span><strong>{active.timebox_minutes} min</strong></div>
          <div><span>Pattern visibility</span><strong>{active.highest_hint ? "Revealed by hint" : "Hidden for retrieval"}</strong></div>
          <div><span>Previous evidence</span><strong>{previous ? `${previous.result} · ${previous.highest_hint || "H0"} · ${previous.failure_tag || "unclassified"}` : "No prior attempt"}</strong></div>
          <div><span>Memory</span><strong>{memory ? `${memory.stability_days.toFixed(1)}d stability · ${memory.evidence_count} observations` : "Not calibrated"}</strong></div>
        </aside>
      </section>

      <section className="today-grid reveal">
        <article className="ruled-panel">
          <header><span className="eyebrow">Why this, now</span><h2>Retrieval before recognition.</h2></header>
          <p>{active.mode.includes("reconstruction") ? "The last attempt produced useful understanding but not yet independent implementation. Today's job is to reconstruct the DFS skeleton before seeing code." : "This problem represents the next useful learning obligation in the roadmap."}</p>
          <div className="micro-evidence"><span>Next review</span><strong>{memory?.next_due || active.assigned_on}</strong></div>
        </article>
        <article className="ruled-panel">
          <header><span className="eyebrow">Due retrievals</span><h2>{due.length ? `${due.length} review${due.length === 1 ? "" : "s"} ready` : "Queue is clear"}</h2></header>
          {due.length ? due.map(review => <button key={review.id} className="review-line" onClick={() => navigate("solve")}><span>{review.stage}</span><strong>{review.title}</strong><em>{review.due_on}</em></button>) : <p>No overdue work. The scheduler will surface the next obligation when evidence says it matters.</p>}
        </article>
      </section>

      <section className="diagnosis-strip reveal">
        <span className="eyebrow">Current learning signal</span>
        <strong>{data.evidence.count < 6 ? "Evidence is still early." : "The retrieval model is developing."}</strong>
        <p>{data.evidence.count} immutable events · {data.evidence.independent_count} independent · {data.evidence.accepted_count} accepted. Public solved count remains separate.</p>
        <button className="text-link button-link" onClick={() => navigate("evidence")}>Inspect evidence →</button>
      </section>
    </main>
  );
}
