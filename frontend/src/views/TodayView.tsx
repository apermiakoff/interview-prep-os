import { useEffect, useState } from "react";
import { api } from "../api";
import type { Bootstrap, LearningToday } from "../types";

export function TodayView({ data, navigate }: { data: Bootstrap; navigate: (route: string) => void }) {
  const [today, setToday] = useState<LearningToday | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.learningToday().then(setToday).catch(reason => setError(reason instanceof Error ? reason.message : "Could not load today's selection."));
  }, []);

  const active = data.active_assignment;
  const selected = today?.selected ?? null;
  const isActiveSelection = Boolean(active && selected && active.problem_id === selected.problem_id);
  const due = data.reviews.filter(review => review.due_on <= data.today);

  const beginLabel = isActiveSelection
    ? (active && active.mode.includes("reconstruction") ? "Begin reconstruction" : "Begin focused attempt")
    : "Open problem workspace";
  const begin = () => {
    if (isActiveSelection) navigate("solve");
    else if (selected) navigate(`problem/${selected.problem_id}`);
  };

  return (
    <main className="view page-shell today-page" id="main-content">
      <div className="section-rule"><span>{active?.date_label || "Today"}</span><span>{new Date(`${active?.assigned_on || data.today}T12:00:00`).toLocaleDateString("en", { weekday: "long", month: "long", day: "numeric" })}</span></div>

      {error && <div className="empty-state">{error}</div>}
      {!error && !today && <div className="collection-loading">Selecting today’s work…</div>}

      {today && (
        <section className="now-grid">
          <article className="now-panel">
            <span className="eyebrow">Now</span>
            {selected ? (
              <>
                <div className="now-kicker">
                  {active && isActiveSelection && <span className="mode-tag">{active.mode.replaceAll("_", " ")}</span>}
                  <span className="now-meta">{selected.leetcode_id ? `#${selected.leetcode_id}` : "roadmap"}{selected.difficulty ? ` · ${selected.difficulty}` : ""} · ~{selected.estimated_minutes} min</span>
                </div>
                <h1 className="now-title">{selected.title}</h1>
                {active && isActiveSelection && <p className="now-goal">{active.goal}</p>}
                <div className="hero-actions">
                  <button className="button primary large" onClick={begin}>{beginLabel} <span>→</span></button>
                  {selected.url && <a className="text-link" href={selected.url} target="_blank" rel="noreferrer">Open problem ↗</a>}
                </div>
              </>
            ) : (
              <>
                <h1 className="now-title">Nothing eligible to train.</h1>
                <p className="now-goal">Import a curriculum or clear queue blocks to get a selection.</p>
              </>
            )}
            <div className="why-block">
              <span className="eyebrow">Why this, from your evidence</span>
              <ul className="why-list">
                {today.why.slice(0, 3).map(fact => <li key={fact}>{fact}</li>)}
              </ul>
              <p className="policy-note">Deterministic selection · {today.policy_version} · {today.candidates_considered} candidates scored</p>
            </div>
          </article>

          <aside className="today-rail">
            <button className="rail-item" onClick={() => navigate("brain")}>
              <span className="rail-label">Risk</span>
              {today.risk ? (
                <>
                  <strong>{today.risk.title}</strong>
                  <em className={`chip ${today.risk.status}`}>{today.risk.status} · {today.risk.observation_count} obs</em>
                </>
              ) : (
                <strong>No trap named yet — not enough evidence.</strong>
              )}
            </button>
            <button className="rail-item" onClick={() => navigate("library/reviews")}>
              <span className="rail-label">Memory below target</span>
              <strong>{today.due_count} problem{today.due_count === 1 ? "" : "s"} below {Math.round(today.target_retention * 100)}% retention</strong>
              {today.due_count > 0 && due.length > 0 && <em>{due[0].title} first</em>}
            </button>
            <button className="rail-item" onClick={() => today.next_gate && navigate("roadmap")}>
              <span className="rail-label">Next gate</span>
              {today.next_gate ? (
                <strong>{today.next_gate.criterion}</strong>
              ) : (
                <strong>No gate computed yet.</strong>
              )}
            </button>
          </aside>
        </section>
      )}

      {due.length > 0 && (
        <section className="due-strip">
          <div className="section-rule"><span>Due retrievals</span><button className="button-link text-link" onClick={() => navigate("library/reviews")}>Open review inbox →</button></div>
          {due.slice(0, 3).map(review => <button key={review.id} className="review-line" onClick={() => navigate(`problem/${review.problem_id}`)}><span>{review.stage}</span><strong>{review.title}</strong><em>{review.due_on}</em></button>)}
        </section>
      )}

      <section className="queue-preview">
        <div className="section-rule"><span>Coming up the tracks</span><button className="button-link text-link" onClick={() => navigate("library")}>Open library →</button></div>
        <div>{data.workload.preview.filter(item => item.status !== "active").slice(0, 4).map(item => <button key={item.id} onClick={() => navigate(`problem/${item.id}`)}><span>{item.roadmap_week != null ? `W${item.roadmap_week}` : "—"}</span><strong>{item.title}</strong><em>{item.pattern_title || "Unclassified"}</em><i className={`status-pill ${item.status}`}>{item.status}</i></button>)}</div>
      </section>

      <section className="diagnosis-strip">
        <span className="eyebrow">Evidence base</span>
        <strong>{data.evidence.count} recorded attempt{data.evidence.count === 1 ? "" : "s"} · confidence {data.evidence.confidence}</strong>
        <p>{data.evidence.independent_count} independent · {data.evidence.accepted_count} accepted. Public solved count stays separate from private mastery evidence.</p>
        <button className="text-link button-link" onClick={() => navigate("brain")}>Open the Brain →</button>
      </section>
    </main>
  );
}
