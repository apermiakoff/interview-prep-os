import { useEffect, useState } from "react";
import { api } from "../api";
import { AlgorithmVisualizer } from "../components/AlgorithmVisualizer";
import type { Bootstrap, LessonDocument, ProblemDetail, SkillStateCell } from "../types";

const CORE_DIMENSIONS = ["recognition", "derivation", "implementation"] as const;

function stateSummary(states: Record<string, SkillStateCell>) {
  const parts = CORE_DIMENSIONS
    .map(dimension => ({ dimension, cell: states[dimension] }))
    .filter(entry => entry.cell && entry.cell.state !== "no_evidence");
  if (!parts.length) return "no evidence yet";
  return parts.map(entry => `${entry.dimension} ${entry.cell!.state.replace("_", " ")}`).join(" · ");
}

function scheduledDate(value: string) {
  return new Date(`${value}T12:00:00`).toLocaleDateString("en", { month: "long", day: "numeric" });
}

export function ProblemDetailView({ problemId, data, navigate }: { problemId: number; data: Bootstrap; navigate: (route: string) => void }) {
  const [detail, setDetail] = useState<ProblemDetail | null>(null);
  const [tab, setTab] = useState<"overview" | "attempts" | "reviews" | "lesson">("overview");
  const [error, setError] = useState("");
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState("");
  const [lessonDoc, setLessonDoc] = useState<LessonDocument | null>(null);
  const [lessonError, setLessonError] = useState("");

  useEffect(() => {
    let current = true;
    setDetail(null);
    setError("");
    setTab("overview");
    setLessonDoc(null);
    setLessonError("");
    api.problem(problemId)
      .then(result => { if (current) setDetail(result); })
      .catch(reason => { if (current) setError(reason instanceof Error ? reason.message : "Could not load problem."); });
    return () => { current = false; };
  }, [problemId]);

  // Lesson bodies are lazy: fetched only when the tab is opened.
  useEffect(() => {
    if (tab !== "lesson" || lessonDoc || lessonError) return;
    let current = true;
    api.problemLesson(problemId)
      .then(result => { if (current) setLessonDoc(result); })
      .catch(reason => { if (current) setLessonError(reason instanceof Error ? reason.message : "Could not load the lesson."); });
    return () => { current = false; };
  }, [tab, problemId, lessonDoc, lessonError]);

  if (error) return <main className="view page-shell" id="main-content"><button className="back-link" onClick={() => navigate("library")}>← Library</button><div className="empty-state">{error}</div></main>;
  if (!detail) return <main className="view page-shell" id="main-content"><div className="collection-loading">Loading problem workspace…</div></main>;

  const { problem, attempts, reviews, memory, content, scheduled_assignment, open_practice_session, skills, prerequisites, related_problems, placements } = detail;
  const otherScheduled = data.active_assignment && data.active_assignment.problem_id !== problemId ? data.active_assignment : null;

  const startPaperAttempt = async () => {
    setLaunching(true);
    setLaunchError("");
    try {
      const envelope = await api.startProblemSession(problemId);
      navigate(`solve/${envelope.session.id}`);
    } catch (reason) {
      setLaunchError(reason instanceof Error ? reason.message : "Could not start the session.");
      setLaunching(false);
    }
  };

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
            {scheduled_assignment ? (
              <>
                <button className="button primary" onClick={() => navigate("solve")}>
                  Continue scheduled attempt →
                </button>
                <button className="button subtle" disabled={launching} onClick={startPaperAttempt}>
                  {open_practice_session ? "Continue extra practice →" : "Practice extra →"}
                </button>
              </>
            ) : (
              <button className="button primary" disabled={launching} onClick={startPaperAttempt}>
                {open_practice_session ? "Continue paper attempt →" : "Start paper attempt →"}
              </button>
            )}
            <a className="text-link" href={problem.url || `https://leetcode.com/problems/${problem.slug}/`} target="_blank" rel="noreferrer">Open on LeetCode ↗</a>
          </div>
          {scheduled_assignment && (
            <p className="extra-practice-note">Extra practice creates a separate session; the scheduled assignment remains untouched.</p>
          )}
          {otherScheduled && !scheduled_assignment && (
            <p className="extra-practice-note">Extra practice. {otherScheduled.title} remains scheduled for {scheduledDate(otherScheduled.assigned_on)}.</p>
          )}
          {launchError && <p className="form-message" role="status">{launchError}</p>}
        </div>
        <aside className="detail-facts">
          <div><span>Queue</span><strong>{problem.queue_state || "catalog"}</strong></div>
          <div><span>Evidence</span><strong>{attempts.length} attempt{attempts.length === 1 ? "" : "s"} · {attempts.filter(item => item.independent).length} independent</strong></div>
          <div><span>Next review</span><strong>{reviews.find(item => item.status !== "completed")?.due_on || memory?.next_due || "Not scheduled"}</strong></div>
          <div><span>Lesson</span><strong className="fact-provenance">{content.lesson.label}</strong></div>
          <div><span>Hints</span><strong className="fact-provenance">{content.hints.label}</strong></div>
        </aside>
      </header>

      <nav className="detail-tabs" aria-label="Problem sections">
        {(["overview", "attempts", "reviews", "lesson"] as const).map(value => <button key={value} className={tab === value ? "active" : ""} onClick={() => setTab(value)}>{value === "lesson" ? `Lesson · ${content.lesson.provenance}` : value}</button>)}
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

      {tab === "lesson" && (
        <section className="embedded-lesson">
          {lessonError && <div className="empty-state">{lessonError}</div>}
          {!lessonError && !lessonDoc && <div className="collection-loading">Resolving lesson…</div>}
          {lessonDoc?.provenance === "curated" && lessonDoc.lesson && (
            <>
              <div className="section-heading compact"><span className="eyebrow">{lessonDoc.label} · hand-built, not generated</span><h2>{lessonDoc.lesson.pattern.title}</h2><p>A deterministic semantic-event visualization authored for this pattern.</p></div>
              <AlgorithmVisualizer lesson={lessonDoc.lesson} />
            </>
          )}
          {lessonDoc?.provenance === "generated" && lessonDoc.scaffold && (
            <>
              <div className="section-heading compact">
                <span className="eyebrow">{lessonDoc.label} · {lessonDoc.generator}</span>
                <h2>Practice scaffold</h2>
                <p>Assembled from this problem's skill map — targeted questions, not an authored walkthrough. It will never pretend to hold a worked solution.</p>
              </div>
              <ol className="scaffold-stages">
                {lessonDoc.scaffold.stages.map(stage => (
                  <li className="scaffold-stage" key={stage.id}>
                    <h3>{stage.title}</h3>
                    <p className="stage-intent">{stage.intent}</p>
                    <ul>{stage.prompts.map(prompt => <li key={prompt}>{prompt}</li>)}</ul>
                  </li>
                ))}
              </ol>
            </>
          )}
          {lessonDoc && lessonDoc.availability === "unavailable" && (
            <div className="empty-state lesson-empty"><strong>{lessonDoc.label}.</strong><span>Attempts, hints, reviews, and skill evidence all work without it. Nothing is fabricated to fill the gap.</span></div>
          )}
        </section>
      )}
    </main>
  );
}
