import type { Bootstrap, Result } from "./types";

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
