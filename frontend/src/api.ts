import type {
  Bootstrap,
  LearningProfile,
  LearningRoadmap,
  LearningToday,
  ProblemDetail,
  ProblemListResponse,
  Result,
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
};
