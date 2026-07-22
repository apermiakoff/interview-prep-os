import { FormEvent, useEffect, useState } from "react";
import { api } from "../api";
import { aiErrorMessage, type AIScope, useAIState } from "./AIState";

const SHORTCUTS = ["Clarify the invariant without giving the solution.", "Help me inspect where my reasoning got stuck.", "Ask me one Socratic question about my approach."];
type PendingSend = { content: string; key: string; runId?: string; conversationId?: string };

function storageKey(scope: AIScope) { return `interview-prep-ai-pending:${scope.scope}:${scope.id}`; }
function readPending(scope: AIScope): PendingSend | null {
  try {
    const raw = sessionStorage.getItem(storageKey(scope));
    return raw ? JSON.parse(raw) as PendingSend : null;
  } catch { return null; }
}
function storePending(scope: AIScope, value: PendingSend | null) {
  try {
    if (value) sessionStorage.setItem(storageKey(scope), JSON.stringify(value));
    else sessionStorage.removeItem(storageKey(scope));
  } catch { /* a denied storage API still leaves in-memory retry safe */ }
}

interface Props {
  scope: AIScope;
  onClose?: () => void;
  onAccepted?: () => void;
}

export function CoachPanel({ scope, onClose, onAccepted }: Props) {
  const state = useAIState(scope);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [pending, setPending] = useState<PendingSend | null>(() => readPending(scope));

  useEffect(() => { storePending(scope, pending); }, [scope.scope, scope.id, pending]);

  const finishFollowing = async (run: Awaited<ReturnType<typeof api.aiRun>>) => {
    await state.follow(run);
    setPending(null);
  };

  const send = async (event?: FormEvent) => {
    event?.preventDefault();
    const content = pending?.content || draft.trim();
    if (!content || sending) return;
    const request = pending || { content, key: crypto.randomUUID() };
    setPending(request);
    setSending(true);
    state.setError("");
    try {
      if (request.runId) {
        const existing = await api.aiRun(request.runId);
        await finishFollowing(existing);
        return;
      }
      const thread = request.conversationId
        ? await state.open(request.conversationId)
        : state.conversation || await state.open();
      const withConversation = { ...request, conversationId: thread.id };
      setPending(withConversation);
      const result = await api.aiMessage(thread.id, request.content, request.key);
      const accepted = { ...withConversation, runId: result.run.id };
      // Persist the accepted run before polling. Finish-state honesty must not
      // depend on a subsequent run or conversation request succeeding.
      storePending(scope, accepted);
      setPending(accepted);
      setDraft("");
      onAccepted?.();
      await finishFollowing(result.run);
    } catch (reason) {
      state.setError(aiErrorMessage(reason));
    } finally {
      setSending(false);
    }
  };

  const discard = () => {
    setPending(null);
    state.setError("");
  };

  const warning = scope.scope === "session"
    ? "Using this session coach marks this attempt AI-assisted and non-independent. It does not reveal canonical hidden hints automatically."
    : "Problem-scoped coaching is study material and is not attached to a practice attempt. During an open attempt, use its session coach instead.";

  return <section className="coach-panel" aria-label="AI coach">
    <header><div><span className="eyebrow">Community AI · scoped coach</span><h2>Reasoning coach</h2></div>{onClose && <button className="coach-close" onClick={onClose} aria-label="Close coach">×</button>}</header>
    <p className="assistance-warning">{warning}</p>
    {state.loading && <div className="ai-skeleton" aria-label="Loading AI coach" />}
    {!state.loading && state.status?.status !== "ready" && <div className="ai-empty"><strong>Community AI is disabled.</strong><p>Configure a server-side provider to use the coach.</p><a href="#settings/ai">Open AI Setup →</a></div>}
    {state.status?.status === "ready" && <>
      {state.conversations.length > 1 && <label className="thread-picker">Thread<select value={state.conversation?.id || ""} onChange={event => void state.open(event.target.value)}>{state.conversations.map(item => <option key={item.id} value={item.id}>{item.title || "Coach thread"}</option>)}</select></label>}
      <div className="coach-messages" aria-live="polite">{!state.conversation?.messages?.length && <p className="quiet-note">Start from your reasoning. The coach receives this {scope.scope}'s bounded context.</p>}{state.conversation?.messages?.map(message => <article className={`coach-message ${message.role}`} key={message.id}><span>{message.role === "assistant" ? "AI coach" : "You"}</span><p>{message.content}</p></article>)}</div>
      <div className="prompt-shortcuts" aria-label="Prompt shortcuts">{SHORTCUTS.map(text => <button key={text} disabled={Boolean(pending)} onClick={() => setDraft(text)}>{text.split(" ").slice(0, 3).join(" ")}…</button>)}</div>
      <form className="coach-composer" onSubmit={send}><label htmlFor={`coach-${scope.scope}-${scope.id}`}>Your reasoning or question</label><textarea id={`coach-${scope.scope}-${scope.id}`} value={pending?.content ?? draft} disabled={Boolean(pending)} onChange={event => setDraft(event.target.value)} maxLength={12000} rows={3} /><button className="button primary" disabled={!draft.trim() || sending || Boolean(pending)}>{sending ? (state.run?.status === "queued" ? "Queued…" : "Generating…") : "Ask coach"}</button></form>
      {state.run && !["completed", "failed", "cancelled"].includes(state.run.status) && <button className="button subtle" onClick={() => void state.cancel()}>Cancel generation</button>}
      {(state.error || pending) && <div className={state.error ? "ai-error" : "ai-recovery"} role={state.error ? "alert" : "status"}>
        {state.error && <p>{state.error}</p>}
        {pending && <><p className="quiet-note">A request is pending. Resume it without creating another message, retry the same idempotent request, or discard it.</p><div className="recovery-actions"><button className="button" disabled={sending} onClick={() => void send()}>{pending.runId ? "Resume accepted request" : "Retry same request"}</button><button className="button subtle" disabled={sending} onClick={discard}>Discard request</button></div></>}
      </div>}
    </>}
  </section>;
}
