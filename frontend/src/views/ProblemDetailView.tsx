import { useEffect, useState } from "react";
import { api } from "../api";
import { AlgorithmVisualizer } from "../components/AlgorithmVisualizer";
import type { ProblemDetail, SkillStateCell } from "../types";

const CORE_DIMENSIONS = ["recognition", "derivation", "implementation"] as const;

function stateSummary(states: Record<string, SkillStateCell>) {
  const parts = CORE_DIMENSIONS
    .map(dimension => ({ dimension, cell: states[dimension] }))
    .filter(entry => entry.cell && entry.cell.state !== "no_evidence");
  if (!parts.length) return "no evidence yet";
  return parts.map(entry => `${entry.dimension} ${entry.cell!.state.replace("_", " ")}`).join(" · ");
}

export function ProblemDetailView({ problemId, navigate }: { problemId: number; navigate: (route: string) => void }) {
  const [detail, setDetail] = useState<ProblemDetail | null>(null);
  const [tab, setTab] = useState<"overview" | "attempts" | "reviews" | "lesson">("overview");
  const [error, setError] = useState("");

  useEffect(() => {
    setDetail(null);
    setError("");
    setTab("overview");
    api.problem(problemId).then(setDetail).catch(reason => setError(reason instanceof Error ? reason.message : "Could not load problem."));
  }, [problemId]);

  if (error) return <main className="view page-shell" id="main-content"><button className="back-link" onClick={() => navigate("library")}>← Library</button><div className="empty-state">{error}</div></main>;
  if (!detail) return <main className="view page-shell" id="main-content"><div className="collection-loading">Loading problem workspace…</div></main>;

  const { problem, attempts, reviews, memory, active_assignment: active, lesson, lesson_availability, skills, prerequisites, related_problems, placements } = detail;
  return (
    <main className="view page-shell problem-detail" id="main-content">
      <button className="back-link" onClick={() => navigate("library")}>← Library</button>
      <header className="problem-detail-hero">
        <div>
          <div className="problem-kicker"><span>{problem.leetcode_id ? `LeetCode ${problem.leetcode_id}` : "Personal catalog"}</span><i>{problem.difficulty || "Difficulty unverified"}</i></div>
          <h1>{problem.title}</h1>
          {placements.length > 0 && (
            <div className="placement-chips">
              {placements.map(placement => (
                <span className={`placement-chip ${placement.kind}`} key={`${placement.curriculum_id}:${placement.position}`}>
                  {placement.curriculum_title}
                  {placement.week_label ? ` · ${placement.week_label}` : ""}
                  {placement.topic ? ` · ${placement.topic}` : ""}
                </span>
              ))}
            </div>
          )}
          <div className="hero-actions">
            {active && <button className="button primary" onClick={() => navigate("solve")}>Continue active session →</button>}
            {problem.url && <a className="text-link" href={problem.url} target="_blank" rel="noreferrer">Open on LeetCode ↗</a>}
          </div>
        </div>
        <aside className="detail-facts">
          <div><span>Queue</span><strong>{problem.queue_state || "catalog"}</strong></div>
          <div><span>Evidence</span><strong>{attempts.length} attempt{attempts.length === 1 ? "" : "s"} · {attempts.filter(item => item.independent).length} independent</strong></div>
          <div><span>Next review</span><strong>{reviews.find(item => item.status !== "completed")?.due_on || memory?.next_due || "Not scheduled"}</strong></div>
          <div><span>Lesson</span><strong>{lesson_availability.status === "authored" ? "Authored" : "None yet"}</strong></div>
        </aside>
      </header>

      <nav className="detail-tabs" aria-label="Problem sections">
        {(["overview", "attempts", "reviews", "lesson"] as const).map(value => <button key={value} className={tab === value ? "active" : ""} onClick={() => setTab(value)}>{value === "lesson" ? `Lesson${lesson ? " · authored" : ""}` : value}</button>)}
      </nav>

      {tab === "overview" && <>
        <section className="detail-overview">
          <article>
            <span className="eyebrow">Skills this problem trains</span>
            {skills.length ? (
              <ul className="skill-list">
                {skills.map(skill => (
                  <li key={skill.skill_id}>
                    <span className={`skill-chip ${skill.role}`}>{skill.title}</span>
                    <em className="skill-role">{skill.role} · w{skill.weight}{skill.provenance === "pattern-backfill" ? " · coarse mapping" : ""}</em>
                    <p className="skill-states">{stateSummary(skill.states)}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No skill mapping yet. Evidence will attach to skills once this problem is mapped.</p>
            )}
          </article>
          <article>
            <span className="eyebrow">Prerequisites</span>
            {prerequisites.length ? (
              <ul className="skill-list">
                {prerequisites.map(prereq => (
                  <li key={prereq.skill_id}>
                    <span className="skill-chip prereq">{prereq.title}</span>
                    <p className="skill-states">{stateSummary(prereq.states)}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <p>No prerequisite edges are mapped for this problem's core skills.</p>
            )}
            <span className="eyebrow" style={{ marginTop: 24 }}>Memory state</span>
            <p>{memory ? `${memory.stability_days.toFixed(1)} days estimated stability from ${memory.evidence_count} observation(s) — an evidence-limited estimate, not a mastery score.` : "No private retrieval evidence yet. Public solved history is intentionally not counted."}</p>
          </article>
        </section>
        {related_problems.length > 0 && (
          <section className="related-problems">
            <div className="section-rule"><span>Related through shared skills</span><span>{related_problems.length} problems</span></div>
            <div className="related-grid">
              {related_problems.map(related => (
                <button key={related.id} onClick={() => navigate(`problem/${related.id}`)}>
                  <strong>{related.title}</strong>
                  <em>{related.shared_skill}{related.difficulty ? ` · ${related.difficulty}` : ""} · {related.attempt_count ? `${related.attempt_count} attempts` : "untouched"}</em>
                </button>
              ))}
            </div>
          </section>
        )}
      </>}

      {tab === "attempts" && <section className="detail-ledger"><div className="section-rule"><span>Attempt history</span><span>{attempts.length} immutable events</span></div>{attempts.length ? attempts.map(attempt => <article className="attempt-line" key={attempt.id}><time>{attempt.occurred_on}</time><span className={`status-dot ${attempt.result}`} /><div><strong>{attempt.result}</strong><p>{attempt.failure_tag || "unclassified blocker"}</p></div><div className="attempt-facts"><span>{attempt.independent ? "independent" : "assisted"}</span><span>{attempt.highest_hint || "H0"}</span>{attempt.duration_minutes != null && <span>{attempt.duration_minutes}m</span>}</div></article>) : <div className="empty-state">No attempts recorded for this problem.</div>}</section>}

      {tab === "reviews" && <section className="detail-ledger"><div className="section-rule"><span>Review obligations</span><span>{reviews.filter(item => item.status !== "completed").length} open</span></div>{reviews.length ? reviews.map(review => <article className="review-detail-line" key={review.id}><time>{review.due_on}</time><div><strong>{review.stage}</strong><p>{review.status.replaceAll("_", " ")}</p></div><i className={`status-pill ${review.status === "completed" ? "stable" : "upcoming"}`}>{review.status}</i></article>) : <div className="empty-state">No review has been scheduled yet.</div>}</section>}

      {tab === "lesson" && (lesson ? <section className="embedded-lesson"><div className="section-heading compact"><span className="eyebrow">{lesson_availability.label} · hand-built, not generated</span><h2>{lesson.pattern.title}</h2><p>A deterministic semantic-event visualization authored for this pattern.</p></div><AlgorithmVisualizer lesson={lesson} /></section> : <div className="empty-state lesson-empty"><strong>{lesson_availability.label}.</strong><span>Attempts, hints, reviews, and skill evidence all work without it. A deep authored lesson can be attached later; the system does not fabricate one.</span></div>)}
    </main>
  );
}
