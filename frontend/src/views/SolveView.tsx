import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { SessionTimer } from "../components/SessionTimer";
import type { Bootstrap, Result } from "../types";

const levels = ["H1", "H2", "H3", "H4"];

export function SolveView({ data, onData, navigate }: { data: Bootstrap; onData: (data: Bootstrap) => void; navigate: (route: string) => void }) {
  const active = data.active_assignment;
  const initialHint = active?.highest_hint ? levels.indexOf(active.highest_hint) + 1 : 0;
  const [revealed, setRevealed] = useState(initialHint);
  const [hintText, setHintText] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState(active?.notes || "");
  const [elapsed, setElapsed] = useState(0);
  const [accepted, setAccepted] = useState(false);
  const [independent, setIndependent] = useState(true);
  const [failure, setFailure] = useState("unspecified");
  const [explanation, setExplanation] = useState<number | undefined>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [saveState, setSaveState] = useState("autosaves");
  const saveTimer = useRef<number | null>(null);
  const lastSavedNotes = useRef(active?.notes || "");

  useEffect(() => {
    if (!active) return;
    if (notes === lastSavedNotes.current) return;
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    setSaveState("saving…");
    saveTimer.current = window.setTimeout(() => {
      api.saveNotes(active.id, notes)
        .then(() => { lastSavedNotes.current = notes; setSaveState("saved"); })
        .catch(() => { setSaveState("save failed"); setMessage("Notes could not be saved."); });
    }, 650);
    return () => { if (saveTimer.current) window.clearTimeout(saveTimer.current); };
  }, [notes, active?.id]);

  const requestedLevel = useMemo(() => levels[Math.max(0, Math.min(revealed - 1, 3))], [revealed]);
  if (!active) return <main className="view page-shell"><div className="section-heading"><span className="eyebrow">Solve room</span><h1>No active assignment.</h1><button className="button primary" onClick={() => navigate("today")}>Back to Today</button></div></main>;

  const revealThrough = async (level: string) => {
    setBusy(true); setMessage("");
    try {
      const result = await api.revealHint(active.id, level);
      const index = levels.indexOf(level) + 1;
      setHintText(current => ({ ...current, [level]: result.text }));
      setRevealed(Math.max(revealed, index));
      if (level === "H4") setIndependent(false);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Hint unavailable"); }
    finally { setBusy(false); }
  };

  const submit = async (result: Result) => {
    setBusy(true); setMessage("");
    try {
      const updated = await api.recordAttempt({
        assignment_id: active.id,
        event_id: crypto.randomUUID(),
        result,
        accepted,
        independent: result === "green" && independent,
        duration_minutes: elapsed,
        failure_tag: result === "green" ? "none" : failure,
        explanation_score: explanation,
      });
      onData(updated);
      navigate(result === "green" && independent ? "evidence" : "lab");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Attempt could not be recorded"); }
    finally { setBusy(false); }
  };

  return (
    <main className="view page-shell solve-page" id="main-content">
      <div className="section-rule"><span>Focused attempt</span><span>{active.title}</span></div>
      <section className="solve-header">
        <div><span className="mode-tag">{active.mode.replaceAll("_", " ")}</span><h1>{active.title}</h1><p>{active.goal}</p></div>
        <SessionTimer minutes={active.timebox_minutes} onElapsed={setElapsed} />
      </section>

      <section className="solve-workspace">
        <article className="work-column">
          <div className="workspace-title"><span className="eyebrow">Scratchpad</span><span className="save-state" role="status">{saveState}</span></div>
          <textarea aria-label="Solution notes" value={notes} onChange={event => setNotes(event.target.value)} placeholder="Clarify the graph, write the brute force, then name the invariant before coding…" />
          <div className="bujo-inline">
            <div><span>Trigger</span><p>{active.bujo.trigger || "What clue identifies this pattern?"}</p></div>
            <div><span>Bottleneck</span><p>{active.bujo.bottleneck || "What repeated work makes brute force slow?"}</p></div>
            <div><span>Invariant</span><p>{active.bujo.invariant || "What must remain true?"}</p></div>
          </div>
        </article>

        <aside className="hint-column">
          <div className="workspace-title"><span className="eyebrow">Progressive hints</span><span className="save-state">highest use recorded</span></div>
          <div className="hint-stack">
            {levels.map((level, index) => {
              const visible = index < revealed;
              return <article className={`hint-item ${visible ? "revealed" : ""}`} key={level}>
                <span>{level}</span>
                {visible ? <p>{hintText[level] || active.hints[level]}</p> : <p aria-hidden="true">Hidden until requested.</p>}
                <button disabled={busy || visible} onClick={() => revealThrough(level)}>{visible ? "Revealed" : `Reveal through ${level}`}</button>
              </article>;
            })}
          </div>
          {revealed > 0 && <p className="hint-warning">You have used through {requestedLevel}. A Green result will be normalized to assisted evidence.</p>}
        </aside>
      </section>

      <section className="outcome-panel">
        <div className="outcome-copy"><span className="eyebrow">Close the loop</span><h2>Record evidence, not a mood.</h2><p>Accepted and independent are separate facts. A copied Accepted can remain Red.</p></div>
        <div className="outcome-fields">
          <label><input type="checkbox" checked={accepted} onChange={event => setAccepted(event.target.checked)} /> Accepted by LeetCode</label>
          <label><input type="checkbox" checked={independent} onChange={event => setIndependent(event.target.checked)} /> Independent implementation</label>
          <label>Primary blocker<select value={failure} onChange={event => setFailure(event.target.value)}><option value="unspecified">Not specified</option><option value="recognition">Recognition</option><option value="derivation">Derivation</option><option value="implementation">Implementation</option><option value="bugs">Bug / edge case</option><option value="complexity">Complexity</option><option value="communication">Explanation</option></select></label>
          <label>Explanation quality<select value={explanation ?? ""} onChange={event => setExplanation(event.target.value ? Number(event.target.value) : undefined)}><option value="">Not rated</option><option value="1">1 — could not explain</option><option value="2">2 — fragmented</option><option value="3">3 — adequate</option><option value="4">4 — clear</option><option value="5">5 — interview-ready</option></select></label>
        </div>
        <div className="outcome-buttons"><button disabled={busy} className="result green" onClick={() => submit("green")}>✓ Independent</button><button disabled={busy} className="result yellow" onClick={() => submit("yellow")}>◐ Assisted / slow</button><button disabled={busy} className="result red" onClick={() => submit("red")}>× Needed solution</button><button disabled={busy} className="result skip" onClick={() => submit("skipped")}>→ Skip today</button></div>
        {message && <p className="form-message" role="status">{message}</p>}
      </section>
    </main>
  );
}
