import { useEffect, useState } from "react";
import { api } from "../api";
import type { Bootstrap, LearningProfile } from "../types";
import { DiagnosisPanel } from "../components/DiagnosisPanel";

export function BrainView({ data, navigate }: { data: Bootstrap; navigate: (route: string) => void }) {
  const [profile, setProfile] = useState<LearningProfile | null>(null);
  const [error, setError] = useState("");
  const [showLedger, setShowLedger] = useState(false);

  useEffect(() => {
    api.learningProfile().then(setProfile).catch(reason => setError(reason instanceof Error ? reason.message : "Could not load the learning profile."));
  }, []);

  const outcomeEntries = [
    ["Independent", data.evidence.independent_count, "green"],
    ["Assisted", data.evidence.outcomes.yellow || 0, "yellow"],
    ["Solution needed", data.evidence.outcomes.red || 0, "red"],
    ["Skipped", data.evidence.outcomes.skipped || 0, "neutral"],
  ] as const;
  const maxOutcome = Math.max(1, ...outcomeEntries.map(([, count]) => count));

  return (
    <main className="view page-shell brain-page" id="main-content">
      <div className="section-heading compact">
        <span className="eyebrow">Brain · diagnosis before data</span>
        <h1>What is actually breaking, with receipts.</h1>
        <p>{profile ? `${profile.evidence_summary.attempts} structured attempts · ${profile.evidence_summary.dimension_observations} dimension observations · confidence ${profile.confidence}.` : "Loading evidence…"} Nothing below is estimated without citing the attempts it came from.</p>
      </div>

      {error && <div className="empty-state">{error}</div>}

      {profile && (
        <>
          <section className="insight-stack" aria-label="Ranked diagnoses">
            {profile.traps.length === 0 && (
              <div className="empty-state">{profile.traps_note || "No classified failures yet. The first tagged Yellow/Red attempt starts the diagnosis."}</div>
            )}
            {profile.traps.slice(0, 3).map((trap, index) => (
              <article className="insight-card" key={trap.id}>
                <header>
                  <span className="insight-rank">{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <h2>{trap.title}</h2>
                    <span className={`chip ${trap.status}`}>{trap.status === "recurring" ? `recurring · ${trap.observation_count} observations` : `suspected · only ${trap.observation_count} observation`}</span>
                  </div>
                </header>
                <div className="insight-body">
                  <div>
                    <span className="eyebrow">Evidence</span>
                    <ul>
                      {trap.evidence.slice(0, 4).map(item => (
                        <li key={item.attempt_id}>{item.occurred_on} · {item.problem}{item.error_type ? ` · ${item.error_type}` : ""}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <span className="eyebrow">Intervention</span>
                    <p>{trap.intervention}</p>
                  </div>
                </div>
              </article>
            ))}
            {profile.traps_note && profile.traps.length > 0 && <p className="policy-note">{profile.traps_note}</p>}
          </section>

          <section className="memory-risk">
            <div className="section-rule"><span>Memory at risk</span><span>target retention {Math.round(profile.target_retention * 100)}%</span></div>
            {profile.memory_at_risk.length === 0 && <p className="quiet-note">Nothing is currently below the retention target.</p>}
            {profile.memory_at_risk.map(item => (
              <button key={item.problem_id} className="risk-line" onClick={() => navigate(`problem/${item.problem_id}`)}>
                <strong>{item.title}</strong>
                <span>retention ≈ {(item.retention_now * 100).toFixed(0)}% · stability {item.stability_days.toFixed(1)}d · was due {item.target_due_on}</span>
                <em className="chip recurring">reconstruct</em>
              </button>
            ))}
          </section>
        </>
      )}

      <DiagnosisPanel />

      <section className="evidence-ledger">
        <article className="evidence-summary">
          <span className="eyebrow">Outcome evidence</span>
          <div className="outcome-bars">{outcomeEntries.map(([label, count, tone]) => <div className="bar-row" key={label}><span>{label}</span><div><i className={tone} style={{ width: `${(count / maxOutcome) * 100}%` }} /></div><strong>{count}</strong></div>)}</div>
          <p className="confidence-note">Confidence: <strong>{data.evidence.confidence}</strong> · public profile statistics are excluded.</p>
        </article>
        <article className="evidence-summary">
          <span className="eyebrow">Failure signals</span>
          <h2>{Object.keys(data.evidence.failures).length ? "What broke first" : "No blockers recorded"}</h2>
          {Object.entries(data.evidence.failures).sort((a, b) => b[1] - a[1]).map(([name, count]) => <div className="failure-line" key={name}><span>{name.replaceAll("_", " ")}</span><strong>{count}</strong></div>)}
        </article>
      </section>

      <section className="attempt-ledger">
        <div className="section-rule">
          <span>Raw attempt ledger · secondary</span>
          <button className="button-link text-link" onClick={() => setShowLedger(value => !value)}>{showLedger ? "Hide" : `Show ${data.attempts.length} events`}</button>
        </div>
        {showLedger && (data.attempts.length ? data.attempts.map(attempt => <article className="attempt-line" key={attempt.id}>
          <time>{attempt.occurred_on}</time><span className={`status-dot ${attempt.result}`} aria-label={attempt.result} />
          <div><strong>{attempt.title}</strong><p>{attempt.pattern_id || "pattern unclassified"}</p></div>
          <div className="attempt-facts"><span>{attempt.independent ? "independent" : "assisted"}</span><span>{attempt.highest_hint || "H0"}</span><span>{attempt.failure_tag || "none"}</span>{attempt.duration_minutes != null && <span>{attempt.duration_minutes}m</span>}</div>
        </article>) : <div className="empty-state">The first recorded attempt will start the evidence ledger.</div>)}
      </section>
    </main>
  );
}
