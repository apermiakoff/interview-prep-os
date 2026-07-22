import { useEffect, useRef, useState } from "react";
import { api, waitForAIRun } from "../api";
import type { AIArtifact, AIStatus, LessonArtifact, VisualizationArtifact } from "../types";
import { aiErrorMessage } from "./AIState";
import { ArtifactVisualization } from "./ArtifactVisualization";

export function AIArtifactPanel({ problemId, kind }: { problemId: number; kind: "lesson" | "visualization" }) {
  const [status, setStatus] = useState<AIStatus | null>(null); const [artifacts, setArtifacts] = useState<AIArtifact[]>([]); const [selected, setSelected] = useState(0);
  const [instruction, setInstruction] = useState(""); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const pending = useRef<{ instructions: string; key: string } | null>(null);
  const load = async () => { const configured = await api.aiStatus(); setStatus(configured); if (configured.status === "ready") { const rows = await api.aiArtifacts("problem", problemId, kind); setArtifacts(rows); setSelected(0); } };
  useEffect(() => { load().catch(reason => setError(aiErrorMessage(reason))); }, [problemId, kind]);
  const generate = async () => {
    const request = pending.current || { instructions: instruction, key: crypto.randomUUID() }; pending.current = request; setBusy(true); setError("");
    try { const result = await api.aiGenerate("problem", problemId, kind, request.instructions, request.key); const run = await waitForAIRun(result.run.id); if (run.status !== "completed") throw new Error(run.error_message || `Generation ${run.status}.`); pending.current = null; setInstruction(""); await load(); }
    catch (reason) { setError(aiErrorMessage(reason)); } finally { setBusy(false); }
  };
  const artifact = artifacts[selected];
  return <section className="ai-artifact-panel">
    <header><div><span className="eyebrow">Community AI · generated artifact</span><h2>{kind === "lesson" ? "Generated lesson" : "Visualization"}</h2></div>{artifacts.length > 1 && <label>Version<select value={selected} onChange={event => setSelected(Number(event.target.value))}>{artifacts.map((item, index) => <option value={index} key={item.id}>v{item.version} · {new Date(item.created_at).toLocaleDateString()}</option>)}</select></label>}</header>
    {status?.status === "disabled" && <div className="ai-empty"><p>Generation is disabled.</p><a href="#settings/ai">Open AI Setup →</a></div>}
    {status?.status === "ready" && <div className="artifact-controls"><label>Optional instruction<input value={instruction} maxLength={2000} onChange={event => { setInstruction(event.target.value); pending.current = null; }} placeholder={kind === "lesson" ? "Emphasize recognition signals" : "Trace a small counterexample"} /></label><button className="button primary" disabled={busy} onClick={() => void generate()}>{busy ? "Generating…" : artifact ? "Regenerate" : "Generate"}</button></div>}
    {error && <div className="ai-error" role="alert"><p>{error}</p>{pending.current && <button className="button" onClick={() => void generate()}>Retry same generation</button>}</div>}
    {artifact && <><p className="artifact-meta">AI generated · v{artifact.version} · {artifact.provider}/{artifact.model} · prompt {artifact.prompt_version} · {new Date(artifact.created_at).toLocaleString()}</p>{kind === "lesson" ? <Lesson content={artifact.content as LessonArtifact} /> : <ArtifactVisualization artifact={artifact.content as VisualizationArtifact} />}</>}
    {status?.status === "ready" && !artifact && !busy && <div className="ai-empty">No generated {kind} yet. Existing curated material remains separate.</div>}
  </section>;
}

function Lesson({ content }: { content: LessonArtifact }) {
  if (content.schema_version !== "lesson@1" || !Array.isArray(content.sections)) return <div className="ai-error">Unsupported lesson schema.</div>;
  return <article className="generated-lesson"><h3>Objectives</h3><ul>{content.objectives.map((value, index) => <li key={index}>{value}</li>)}</ul><h3>Recognition signals</h3><ul>{content.recognition_signals.map((value, index) => <li key={index}>{value}</li>)}</ul>{content.sections.map((section, index) => <section key={index}><h3>{section.heading}</h3><p>{section.body}</p></section>)}<div className="complexity-card"><strong>Complexity</strong><span>Time · {content.complexity.time}</span><span>Space · {content.complexity.space}</span></div><h3>Failure modes</h3><ul>{content.failures.map((value, index) => <li key={index}>{value}</li>)}</ul>{content.provenance_notes.length > 0 && <p className="artifact-meta">Provenance notes: {content.provenance_notes.join(" · ")}</p>}</article>;
}
