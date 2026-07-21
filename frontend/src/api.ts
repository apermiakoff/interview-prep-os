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
} from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail || "Request failed");
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
};
