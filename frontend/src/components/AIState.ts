import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, waitForAIRun } from "../api";
import type { AIRun, AIStatus, Conversation } from "../types";

export type AIScope = { scope: "problem" | "session"; id: string | number };
export function aiErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 402) return "Monthly AI budget reached. Existing material remains available.";
    if (error.status === 409) return "A generation is already active for this scope. Wait or cancel it.";
    if (error.status === 503) return "Community AI is unavailable. Open AI Setup to configure the server.";
  }
  return error instanceof Error ? error.message : "AI request failed.";
}

export function useAIState({ scope, id }: AIScope) {
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [run, setRun] = useState<AIRun | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const abort = useRef<AbortController | null>(null);

  const refreshConversation = useCallback(async (conversationId: string) => {
    const next = await api.aiConversation(conversationId); setConversation(next); return next;
  }, []);
  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const configured = await api.aiStatus(); setStatus(configured);
      if (configured.status === "ready") {
        const threads = await api.aiConversations(scope, id); setConversations(threads);
        if (threads[0]) await refreshConversation(threads[0].id);
      }
    } catch (reason) { setError(aiErrorMessage(reason)); }
    finally { setLoading(false); }
  }, [scope, id, refreshConversation]);
  useEffect(() => { void load(); return () => abort.current?.abort(); }, [load]);

  const open = async (conversationId?: string) => {
    setError("");
    try {
      if (conversationId) return await refreshConversation(conversationId);
      const created = await api.aiCreateConversation(scope, id, scope === "session" ? "Solve-room coach" : "Problem coach");
      setConversations(value => [created, ...value]); setConversation({ ...created, messages: [] }); return created;
    } catch (reason) { setError(aiErrorMessage(reason)); throw reason; }
  };
  const follow = async (nextRun: AIRun) => {
    setRun(nextRun); abort.current?.abort(); abort.current = new AbortController();
    try {
      const terminal = await waitForAIRun(nextRun.id, setRun, abort.current.signal);
      const conversationId = nextRun.conversation_id || conversation?.id;
      if (conversationId) await refreshConversation(conversationId);
      if (terminal.status === "failed") setError(terminal.error_message || "Generation failed.");
      if (terminal.status === "cancelled") setError("Generation cancelled.");
      return terminal;
    } catch (reason) { if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(aiErrorMessage(reason)); throw reason; }
  };
  const cancel = async () => { if (run) { await api.aiCancel(run.id); setRun({ ...run, status: "cancelled" }); } };
  return { status, conversations, conversation, run, error, loading, setError, open, follow, cancel, refreshConversation, reload: load };
}
