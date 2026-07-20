import { useEffect, useState } from "react";
import { api } from "../api";
import { AlgorithmVisualizer } from "../components/AlgorithmVisualizer";
import type { ProblemDetail } from "../types";

export function ProblemDetailView({ problemId, navigate }: { problemId: number; navigate: (route: string) => void }) {
  const [detail, setDetail] = useState<ProblemDetail | null>(null);
  const [tab, setTab] = useState<"overview" | "attempts" | "reviews" | "lesson">("overview");
  const [error, setError] = useState("");

  useEffect(() => {
    setDetail(null);
    setError("");
    api.problem(problemId).then(setDetail).catch(reason => setError(reason instanceof Error ? reason.message : "Could not load problem."));
  }, [problemId]);

  if (error) return <main className="view page-shell" id="main-content"><button className="back-link" onClick={() => navigate("problems")}>← Problems</button><div className="empty-state">{error}</div></main>;
  if (!detail) return <main className="view page-shell" id="main-content"><div className="collection-loading">Loading problem workspace…</div></main>;

  const { problem, attempts, reviews, memory, active_assignment: active, lesson } = detail;
  return (
    <main className="view page-shell problem-detail" id="main-content">
      <button className="back-link" onClick={() => navigate("problems")}>← All problems</button>
      <header className="problem-detail-hero">
        <div>
          <div className="problem-kicker"><span>{problem.leetcode_id ? `LeetCode ${problem.leetcode_id}` : `Roadmap week ${problem.roadmap_week ?? "—"}`}</span><i>{problem.difficulty || "Difficulty unverified"}</i></div>
          <h1>{problem.title}</h1>
          <p>{problem.pattern_description || "This roadmap item does not have a pattern lesson yet. Evidence and reviews will accumulate here after the first attempt."}</p>
          <div className="hero-actions">
            {active && <button className="button primary" onClick={() => navigate("solve")}>Continue active session →</button>}
            {problem.url && <a className="text-link" href={problem.url} target="_blank" rel="noreferrer">Open on LeetCode ↗</a>}
          </div>
        </div>
        <aside className="detail-facts">
          <div><span>Queue</span><strong>{problem.queue_state || "catalog"}</strong></div>
          <div><span>Evidence</span><strong>{attempts.length} attempt{attempts.length === 1 ? "" : "s"}</strong></div>
          <div><span>Independent</span><strong>{attempts.filter(item => item.independent).length}</strong></div>
          <div><span>Next review</span><strong>{reviews.find(item => item.status !== "completed")?.due_on || memory?.next_due || "Not scheduled"}</strong></div>
        </aside>
      </header>

      <nav className="detail-tabs" aria-label="Problem sections">
        {(["overview", "attempts", "reviews", "lesson"] as const).map(value => <button key={value} className={tab === value ? "active" : ""} onClick={() => setTab(value)}>{value === "lesson" ? `Lesson${lesson ? " · available" : ""}` : value}</button>)}
      </nav>

      {tab === "overview" && <section className="detail-overview">
        <article><span className="eyebrow">Pattern</span><h2>{problem.pattern_title || "Unclassified"}</h2><p>{problem.pattern_description || "The daily coach will classify this when it becomes active."}</p>{problem.recognition_signals?.length > 0 && <ul>{problem.recognition_signals.map(signal => <li key={signal}>{signal}</li>)}</ul>}</article>
        <article><span className="eyebrow">Memory state</span><h2>{memory ? `${memory.evidence_count} observations` : "No private evidence"}</h2><p>{memory ? `${memory.stability_days.toFixed(1)} days estimated stability. This is an evidence-limited estimate, not a mastery score.` : "Public solved history is intentionally not treated as proof of independent delayed retrieval."}</p></article>
      </section>}

      {tab === "attempts" && <section className="detail-ledger"><div className="section-rule"><span>Attempt history</span><span>{attempts.length} immutable events</span></div>{attempts.length ? attempts.map(attempt => <article className="attempt-line" key={attempt.id}><time>{attempt.occurred_on}</time><span className={`status-dot ${attempt.result}`} /><div><strong>{attempt.result}</strong><p>{attempt.failure_tag || "unclassified blocker"}</p></div><div className="attempt-facts"><span>{attempt.independent ? "independent" : "assisted"}</span><span>{attempt.highest_hint || "H0"}</span>{attempt.duration_minutes != null && <span>{attempt.duration_minutes}m</span>}</div></article>) : <div className="empty-state">No attempts recorded for this problem.</div>}</section>}

      {tab === "reviews" && <section className="detail-ledger"><div className="section-rule"><span>Review obligations</span><span>{reviews.filter(item => item.status !== "completed").length} open</span></div>{reviews.length ? reviews.map(review => <article className="review-detail-line" key={review.id}><time>{review.due_on}</time><div><strong>{review.stage}</strong><p>{review.status.replaceAll("_", " ")}</p></div><i className={`status-pill ${review.status === "completed" ? "stable" : "upcoming"}`}>{review.status}</i></article>) : <div className="empty-state">No review has been scheduled yet.</div>}</section>}

      {tab === "lesson" && (lesson ? <section className="embedded-lesson"><div className="section-heading compact"><span className="eyebrow">Problem-specific lesson</span><h2>{lesson.pattern.title}</h2><p>The visualization is loaded only for this problem. It no longer occupies a global product destination.</p></div><AlgorithmVisualizer lesson={lesson} /></section> : <div className="empty-state lesson-empty"><strong>No bespoke visualizer yet.</strong><span>This problem will still support attempts, hints, reviews, and pattern evidence. A deterministic visual lesson can be attached later without changing the queue.</span></div>)}
    </main>
  );
}
