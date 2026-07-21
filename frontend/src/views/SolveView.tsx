import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { CompactTimer, clearTimer, readTimerElapsedMinutes } from "../components/CompactTimer";
import { FinishSheet, type FinishFacts } from "../components/FinishSheet";
import type { Bootstrap, SessionEnvelope, SessionHintLevel } from "../types";

/*
 * Paper-first solve room. The screen is a command cockpit, not an editor:
 * session bar on top, a printed-style attempt brief in the main column, and a
 * sticky hint staircase on the right. Reading happens on LeetCode, reasoning on
 * paper, implementation there — this room only frames the attempt and records
 * the evidence.
 */

const RANK: Record<string, number> = { H1: 1, H2: 2, H3: 3, H4: 4 };

const FRAMEWORK: Array<{ title: string; prompts: string[] }> = [
  { title: "Clarify", prompts: ["Inputs and output, exactly.", "Constraints and size bounds.", "Edge cases the constraints allow."] },
  { title: "Derive", prompts: ["Brute force first.", "Name the bottleneck.", "State the invariant before code."] },
  { title: "Verify", prompts: ["Dry-run one small case.", "Time and space bounds.", "Hunt one counterexample."] },
];

function scheduledDate(value: string) {
  return new Date(`${value}T12:00:00`).toLocaleDateString("en", { month: "long", day: "numeric" });
}

interface Props {
  sessionId: string | null;
  data: Bootstrap;
  onData: (data: Bootstrap) => void;
  navigate: (route: string) => void;
  replaceRoute: (route: string) => void;
}

export function SolveView({ sessionId, data, onData, navigate, replaceRoute }: Props) {
  const [envelope, setEnvelope] = useState<SessionEnvelope | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [confirmingFirstHint, setConfirmingFirstHint] = useState(false);
  const [railOpen, setRailOpen] = useState(false);
  const [finishOpen, setFinishOpen] = useState(false);
  const [finishError, setFinishError] = useState("");
  const [finishElapsed, setFinishElapsed] = useState(0);
  const [elapsedCapped, setElapsedCapped] = useState(false);
  const attemptRef = useRef<{ signature: string; eventId: string } | null>(null);
  const finishButtonRef = useRef<HTMLButtonElement>(null);

  // Bare #solve keeps working: it creates/continues the scheduled session.
  useEffect(() => {
    if (sessionId) return;
    const active = data.active_assignment;
    if (!active) return;
    api.startAssignmentSession(active.id)
      .then(result => replaceRoute(`solve/${result.session.id}`))
      .catch(reason => setError(reason instanceof Error ? reason.message : "Could not open the session."));
  }, [sessionId, data.active_assignment?.id]);

  useEffect(() => {
    if (!sessionId) return;
    setEnvelope(null);
    setError("");
    api.practiceSession(sessionId)
      .then(setEnvelope)
      .catch(reason => setError(reason instanceof Error ? reason.message : "Could not load the session."));
  }, [sessionId]);

  const session = envelope?.session ?? null;
  const problem = envelope?.problem ?? null;
  const consumed = session?.highest_hint ? RANK[session.highest_hint] || 0 : 0;
  const hintsUsed = consumed > 0;
  const preservedScheduled = data.active_assignment && session?.origin === "ad_hoc"
    ? data.active_assignment
    : null;

  const levels = useMemo<SessionHintLevel[]>(() => envelope?.hints.levels ?? [], [envelope]);

  const reveal = async (level: string) => {
    if (!session) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await api.revealSessionHint(session.id, level);
      setEnvelope(current => {
        if (!current) return current;
        const rank = RANK[result.highest_hint] || 0;
        return {
          ...current,
          session: { ...current.session, highest_hint: result.highest_hint },
          hints: {
            ...current.hints,
            levels: current.hints.levels.map(entry => {
              const entryRank = RANK[entry.level];
              if (entry.level === result.level) return { ...entry, state: "revealed", body: result.body };
              if (entryRank <= rank) return { ...entry, state: "revealed" };
              if (entryRank === rank + 1) return { ...entry, state: "next" };
              return { ...entry, state: "locked" };
            }),
          },
        };
      });
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Hint unavailable.");
    } finally {
      setBusy(false);
      setConfirmingFirstHint(false);
    }
  };

  const openFinish = () => {
    if (!session) return;
    const elapsed = readTimerElapsedMinutes(session.id);
    setFinishElapsed(Math.min(360, elapsed));
    setElapsedCapped(elapsed > 360);
    setFinishError("");
    attemptRef.current = null;
    setFinishOpen(true);
  };

  const closeFinish = () => {
    setFinishOpen(false);
    setFinishError("");
    attemptRef.current = null;
    window.requestAnimationFrame(() => finishButtonRef.current?.focus());
  };

  const submit = async (facts: FinishFacts) => {
    if (!session || !problem) return;
    const signature = JSON.stringify({ ...facts, duration_minutes: finishElapsed });
    if (!attemptRef.current || attemptRef.current.signature !== signature) {
      attemptRef.current = { signature, eventId: crypto.randomUUID() };
    }
    setBusy(true);
    setFinishError("");
    try {
      const result = await api.recordSessionAttempt(session.id, {
        event_id: attemptRef.current.eventId,
        result: facts.result,
        accepted: facts.accepted,
        independent: facts.independent,
        duration_minutes: finishElapsed,
        failure_tag: facts.failure_tag,
        explanation_score: facts.explanation_score,
      });
      clearTimer(session.id);
      onData(result.bootstrap);
      const canonical = result.attempt;
      const closedTheLoop = session.origin === "scheduled"
        && canonical?.result === "green"
        && canonical.independent;
      attemptRef.current = null;
      navigate(closedTheLoop ? "brain" : `problem/${problem.id}`);
    } catch (reason) {
      setFinishError(reason instanceof Error ? reason.message : "Attempt could not be recorded.");
      setBusy(false);
    }
  };

  const abandon = async () => {
    if (!session || !problem) return;
    setBusy(true);
    setFinishError("");
    try {
      await api.abandonSession(session.id);
      clearTimer(session.id);
      navigate(`problem/${problem.id}`);
    } catch (reason) {
      setFinishError(reason instanceof Error ? reason.message : "Could not abandon the session.");
      setBusy(false);
    }
  };

  if (error) {
    return (
      <main className="view page-shell solve-page" id="main-content">
        <div className="empty-state">{error}</div>
        <button className="button" onClick={() => navigate("library")}>Back to Library</button>
      </main>
    );
  }

  if (!sessionId && !data.active_assignment) {
    return (
      <main className="view page-shell solve-page" id="main-content">
        <div className="section-heading"><span className="eyebrow">Solve room</span><h1>No scheduled session.</h1><p>Pick any problem in the Library and start a paper attempt.</p></div>
        <div className="hero-actions">
          <button className="button primary" onClick={() => navigate("library")}>Open Library</button>
          <button className="button subtle" onClick={() => navigate("today")}>Back to Today</button>
        </div>
      </main>
    );
  }

  if (!envelope || !session || !problem) {
    return <main className="view page-shell solve-page" id="main-content"><div className="collection-loading">Opening the session…</div></main>;
  }

  if (session.status !== "active") {
    return (
      <main className="view page-shell solve-page" id="main-content">
        <div className="section-heading">
          <span className="eyebrow">Solve room</span>
          <h1>This session is {session.status}.</h1>
          <p>{problem.title} — the evidence lives on the problem page.</p>
        </div>
        <div className="hero-actions">
          <button className="button primary" onClick={() => navigate(`problem/${problem.id}`)}>Open problem workspace</button>
          <button className="button subtle" onClick={() => navigate("library")}>Back to Library</button>
        </div>
      </main>
    );
  }

  const nextLevel = levels.find(entry => entry.state === "next" && entry.available)?.level ?? null;

  return (
    <main className="view solve-page" id="main-content">
      <section className="session-bar" aria-label="Session command bar">
        <div className="session-bar-context">
          <button className="bar-back" onClick={() => navigate("library")}>← Library</button>
          <span className={`origin-chip ${session.origin}`}>{session.origin === "scheduled" ? "Scheduled assignment" : "Extra practice"}</span>
          <div className="bar-identity">
            <strong>{problem.title}</strong>
            <span>{problem.leetcode_id ? `#${problem.leetcode_id}` : problem.slug}{problem.difficulty ? ` · ${problem.difficulty}` : ""} · {session.timebox_minutes} min</span>
          </div>
        </div>
        <div className="session-bar-commands">
          <a className="button leetcode-cta" href={problem.url || `https://leetcode.com/problems/${problem.slug}/`} target="_blank" rel="noreferrer">Open on LeetCode ↗</a>
          <CompactTimer sessionId={session.id} timeboxMinutes={session.timebox_minutes} />
          <button ref={finishButtonRef} className="button primary finish-cta" disabled={busy} onClick={openFinish}>Finish attempt</button>
        </div>
      </section>

      <div className="solve-shell page-shell">
        {preservedScheduled && (
          <p className="extra-practice-note">
            Extra practice. {preservedScheduled.problem_id === session.problem_id
              ? `This problem's scheduled assignment remains scheduled for ${scheduledDate(preservedScheduled.assigned_on)}.`
              : `${preservedScheduled.title} remains scheduled for ${scheduledDate(preservedScheduled.assigned_on)}.`}
          </p>
        )}

        <button className="hint-drawer-toggle" aria-expanded={railOpen} onClick={() => setRailOpen(open => !open)}>
          Hints · {session.highest_hint ? `used through ${session.highest_hint}` : "H0 independent"}
        </button>

        <div className="solve-grid">
          <article className="paper-brief">
            <p className="brief-goal">{session.goal}</p>
            <p className="brief-method">Read on LeetCode. Reason on paper. Implement there.</p>
            <div className="paper-framework">
              {FRAMEWORK.map(column => (
                <section className="framework-column" key={column.title}>
                  <h3>{column.title}</h3>
                  <ul>{column.prompts.map(prompt => <li key={prompt}>{prompt}</li>)}</ul>
                </section>
              ))}
            </div>
          </article>

          <aside className={`hint-rail ${railOpen ? "open" : ""}`} aria-label="Progressive hints">
            <div className="rail-head">
              <span className="rail-title">Hints</span>
              <span className={`rail-state ${hintsUsed ? "assisted" : "independent"}`}>
                {hintsUsed ? `Used through ${session.highest_hint}` : "H0 · independent"}
              </span>
            </div>
            {envelope.hints.availability === "unavailable" ? (
              <p className="rail-unavailable">No hint content is mapped for this problem yet. The attempt still records honestly.</p>
            ) : (
              <ol className="hint-staircase">
                {levels.map(entry => {
                  const isNext = entry.level === nextLevel;
                  if (entry.state === "revealed") {
                    return (
                      <li className="hint-step revealed" key={entry.level}>
                        <span className="step-level">{entry.level}</span>
                        <p>{entry.body || "Revealed earlier in this session."}</p>
                      </li>
                    );
                  }
                  if (isNext) {
                    return (
                      <li className="hint-step next" key={entry.level}>
                        <span className="step-level">{entry.level}</span>
                        {!hintsUsed && confirmingFirstHint ? (
                          <div className="hint-confirm">
                            <p>Revealing a hint records this attempt as assisted — a Green result becomes Yellow.</p>
                            <div className="hint-confirm-actions">
                              <button disabled={busy} onClick={() => reveal(entry.level)}>Reveal {entry.level} — record assisted</button>
                              <button className="hint-cancel" disabled={busy} onClick={() => setConfirmingFirstHint(false)}>Stay independent</button>
                            </div>
                          </div>
                        ) : (
                          <button
                            className="hint-reveal"
                            disabled={busy}
                            onClick={() => (hintsUsed ? reveal(entry.level) : setConfirmingFirstHint(true))}
                          >
                            Reveal {entry.level}
                          </button>
                        )}
                      </li>
                    );
                  }
                  return (
                    <li className="hint-step locked" key={entry.level}>
                      <span className="step-level">{entry.level}</span>
                      <span className="step-locked">{entry.available ? "locked" : "no content"}</span>
                    </li>
                  );
                })}
              </ol>
            )}
            <p className="rail-provenance">
              {envelope.hints.label}
              {envelope.hints.generator ? ` · ${envelope.hints.generator}` : ""}
            </p>
            {message && <p className="form-message" role="status">{message}</p>}
          </aside>
        </div>
      </div>

      {finishOpen && (
        <FinishSheet
          origin={session.origin}
          hintsUsed={hintsUsed}
          highestHint={session.highest_hint}
          elapsedMinutes={finishElapsed}
          elapsedCapped={elapsedCapped}
          busy={busy}
          error={finishError}
          onSubmit={submit}
          onAbandon={session.origin === "ad_hoc" ? abandon : undefined}
          onClose={closeFinish}
        />
      )}
    </main>
  );
}
