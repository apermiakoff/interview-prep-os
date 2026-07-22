import type {
  Bootstrap,
  HintRevealResponse,
  LearningProfile,
  LearningRoadmap,
  LearningToday,
  LessonDocument,
  ProblemDetail,
  ProblemListResponse,
  Result,
  SessionAttemptResponse,
  SessionEnvelope,
  AIArtifact, AIStatus, AIUsage, Conversation, AIRun,
} from "./types";

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); this.name = "ApiError"; }
}

export async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(payload.detail || "Request failed", response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  bootstrap: () => request<Bootstrap>("/api/bootstrap"),
  learningToday: () => request<LearningToday>("/api/learning/today"),
  learningProfile: () => request<LearningProfile>("/api/learning/profile"),
  learningRoadmap: () => request<LearningRoadmap>("/api/learning/roadmap"),
  problems: (params: Record<string, string | number | undefined>) => {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== "") search.set(key, String(value));
    });
    return request<ProblemListResponse>(`/api/problems?${search.toString()}`);
  },
  problem: (id: number) => request<ProblemDetail>(`/api/problems/${id}`),
  updateQueue: (problemIds: number[], state: string) =>
    request<{ updated: number; state: string }>("/api/queue", {
      method: "PUT",
      body: JSON.stringify({ problem_ids: problemIds, state }),
    }),
  revealHint: (assignmentId: string, level: string) =>
    request<{ level: string; text: string; highest_hint: string }>("/api/hints", {
      method: "POST",
      body: JSON.stringify({ assignment_id: assignmentId, level }),
    }),
  saveNotes: (assignmentId: string, content: string) =>
    request<{ saved: boolean }>(`/api/assignments/${encodeURIComponent(assignmentId)}/notes`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
  recordAttempt: (payload: {
    assignment_id: string;
    event_id: string;
    result: Result;
    accepted: boolean;
    independent: boolean;
    duration_minutes?: number;
    failure_tag: string;
    explanation_score?: number;
  }) => request<Bootstrap>("/api/attempts", { method: "POST", body: JSON.stringify(payload) }),
  startProblemSession: (problemId: number, requestId?: string) =>
    request<SessionEnvelope>(`/api/problems/${problemId}/practice-sessions`, {
      method: "POST",
      body: JSON.stringify(requestId ? { request_id: requestId } : {}),
    }),
  startAssignmentSession: (assignmentId: string) =>
    request<SessionEnvelope>(`/api/assignments/${encodeURIComponent(assignmentId)}/sessions`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  practiceSession: (sessionId: string) =>
    request<SessionEnvelope>(`/api/practice-sessions/${encodeURIComponent(sessionId)}`),
  revealSessionHint: (sessionId: string, level: string) =>
    request<HintRevealResponse>(
      `/api/practice-sessions/${encodeURIComponent(sessionId)}/hints/${level}/reveal`,
      { method: "POST", body: JSON.stringify({}) },
    ),
  recordSessionAttempt: (sessionId: string, payload: {
    event_id: string;
    result: Result;
    accepted: boolean;
    independent: boolean;
    duration_minutes?: number;
    failure_tag: string;
    explanation_score?: number;
  }) =>
    request<SessionAttemptResponse>(
      `/api/practice-sessions/${encodeURIComponent(sessionId)}/attempts`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  abandonSession: (sessionId: string) =>
    request<SessionEnvelope>(`/api/practice-sessions/${encodeURIComponent(sessionId)}/abandon`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  problemLesson: (problemId: number) =>
    request<LessonDocument>(`/api/problems/${problemId}/lesson`),
  aiStatus: () => request<AIStatus>("/api/ai/status"),
  aiUsage: () => request<AIUsage>("/api/ai/usage"),
  aiConversations: (scope: "problem" | "session", id: string | number) => request<Conversation[]>(`/api/ai/${scope}s/${encodeURIComponent(String(id))}/conversations`),
  aiCreateConversation: (scope: "problem" | "session", id: string | number, title = "") => request<Conversation>(`/api/ai/${scope}s/${encodeURIComponent(String(id))}/conversations`, { method: "POST", body: JSON.stringify({ title }) }),
  aiConversation: (id: string) => request<Conversation>(`/api/ai/conversations/${encodeURIComponent(id)}`),
  aiMessage: (id: string, content: string, idempotency_key: string) => request<{ run: AIRun; created: boolean }>(`/api/ai/conversations/${encodeURIComponent(id)}/messages`, { method: "POST", body: JSON.stringify({ content, idempotency_key }) }),
  aiGenerate: (scope: "problem" | "session" | "learning", id: string | number, kind: "lesson" | "visualization" | "diagnosis", instructions: string, idempotency_key: string) => request<{ run: AIRun; created: boolean }>(scope === "learning" ? "/api/ai/learning/diagnosis" : `/api/ai/${scope}s/${encodeURIComponent(String(id))}/${kind}`, { method: "POST", body: JSON.stringify({ instructions, idempotency_key }) }),
  aiRun: (id: string) => request<AIRun>(`/api/ai/runs/${encodeURIComponent(id)}`),
  aiCancel: (id: string) => request<{ id: string; status: string; cancel_requested: boolean }>(`/api/ai/runs/${encodeURIComponent(id)}/cancel`, { method: "POST", body: "{}" }),
  aiArtifacts: (scope: "problem" | "session", id: string | number, kind?: string) => request<AIArtifact[]>(`/api/ai/${scope}s/${encodeURIComponent(String(id))}/artifacts${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`),
  aiLatestArtifact: (scope: "problem" | "session", id: string | number, kind: string) => request<AIArtifact>(`/api/ai/${scope}s/${encodeURIComponent(String(id))}/artifacts/latest?kind=${encodeURIComponent(kind)}`),
  aiDiagnosisHistory: () => request<AIArtifact[]>("/api/ai/learning/diagnosis/history"),
};

export async function streamAIRunEvents(runId: string, onEvent: (event: import("./types").SSEEvent) => void, signal?: AbortSignal, lastEventId = "0"): Promise<string> {
  const response = await fetch(`/api/ai/runs/${encodeURIComponent(runId)}/events`, { headers: { Accept: "text/event-stream", "Last-Event-ID": lastEventId }, signal });
  if (!response.ok || !response.body) throw new ApiError("Could not open AI event stream", response.status);
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ""; let cursor = lastEventId;
  for (;;) {
    const { done, value } = await reader.read(); if (done) break;
    buffer += decoder.decode(value, { stream: true }); const blocks = buffer.split("\n\n"); buffer = blocks.pop() || "";
    for (const block of blocks) {
      let event = "message", data = "{}", id = cursor;
      for (const line of block.split("\n")) { if (line.startsWith("id:")) id = line.slice(3).trim(); else if (line.startsWith("event:")) event = line.slice(6).trim(); else if (line.startsWith("data:")) data = line.slice(5).trim(); }
      if (id !== cursor || event !== "message") { cursor = id; onEvent({ id, event, data: JSON.parse(data) as Record<string, unknown> }); }
    }
  }
  return cursor;
}

export async function waitForAIRun(runId: string, onUpdate?: (run: AIRun) => void, signal?: AbortSignal): Promise<AIRun> {
  let delay = 500;
  for (;;) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    const run = await api.aiRun(runId); onUpdate?.(run);
    if (["completed", "failed", "cancelled"].includes(run.status)) return run;
    await new Promise<void>((resolve, reject) => { const timer = window.setTimeout(resolve, delay); signal?.addEventListener("abort", () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); }, { once: true }); });
    delay = Math.min(2000, Math.round(delay * 1.4));
  }
}
