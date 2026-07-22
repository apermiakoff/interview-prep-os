import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CoachPanel } from "../src/components/CoachPanel";
import { ArtifactVisualization } from "../src/components/ArtifactVisualization";
import { DiagnosisPanel } from "../src/components/DiagnosisPanel";
import { AISetupView } from "../src/views/AISetupView";
import { ProblemDetailView } from "../src/views/ProblemDetailView";
import type { Bootstrap } from "../src/types";

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });

test("coach presents disabled setup path", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(() => json({ status: "disabled", enabled: false, provider: "ollama", model: "llama3.2" }));
  render(<CoachPanel scope={{ scope: "problem", id: 1 }} />);
  expect(await screen.findByText("Community AI is disabled.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /AI Setup/ })).toHaveAttribute("href", "#settings/ai");
  expect(screen.getByText(/Problem-scoped coaching is study material/)).toBeInTheDocument();
});

test("problem AI controls are unavailable during its open practice session", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(() => json({
    problem: { id: 9, slug: "locked", title: "Locked Problem", recognition_signals: [] },
    attempts: [], reviews: [], memory: null, active_assignment: null,
    content: { lesson: { provenance: "unavailable", label: "No lesson" }, hints: { provenance: "unavailable", label: "No hints" } },
    can_start_ad_hoc: true, scheduled_assignment: null,
    open_practice_session: { id: "session-exact", origin: "ad_hoc", started_at: "x" },
    skills: [], prerequisites: [], related_problems: [], placements: [],
  }));
  const navigate = vi.fn();
  render(<ProblemDetailView problemId={9} data={{ active_assignment: null } as unknown as Bootstrap} navigate={navigate} />);
  expect(await screen.findByRole("heading", { name: /Problem AI is locked/ })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "coach" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Generated lesson" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Use session Coach/ }));
  expect(navigate).toHaveBeenCalledWith("solve/session-exact");
});

test("enabled coach retries with the same idempotency key", async () => {
  const keys: string[] = []; let posts = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    if (url.endsWith("/status")) return json({ status: "ready", enabled: true, provider: "ollama", model: "m" });
    if (url.includes("/problems/1/conversations") && !init?.method) return json([]);
    if (url.includes("/problems/1/conversations") && init?.method === "POST") return json({ id: "c1", scope: "problem", scope_id: "1", title: "Coach", created_at: "x", updated_at: "x" }, 201);
    if (url.endsWith("/conversations/c1/messages")) { keys.push(JSON.parse(String(init?.body)).idempotency_key); posts++; return posts === 1 ? json({ detail: "temporary" }, 500) : json({ run: { id: "r1", kind: "chat", scope: "problem", scope_id: "1", status: "completed", attempts: 1, max_attempts: 2, created_at: "x", updated_at: "x" }, created: true }, 202); }
    if (url.endsWith("/runs/r1")) return json({ id: "r1", kind: "chat", scope: "problem", scope_id: "1", status: "completed", attempts: 1, max_attempts: 2, created_at: "x", updated_at: "x" });
    if (url.endsWith("/conversations/c1")) return json({ id: "c1", scope: "problem", scope_id: "1", title: "Coach", created_at: "x", updated_at: "x", messages: [{ id: "m1", role: "assistant", content: "Try naming the invariant.", created_at: "x" }] });
    throw new Error(`unexpected ${url}`);
  });
  render(<CoachPanel scope={{ scope: "problem", id: 1 }} />);
  const box = await screen.findByLabelText("Your reasoning or question"); fireEvent.change(box, { target: { value: "I am stuck" } }); fireEvent.click(screen.getByRole("button", { name: "Ask coach" }));
  fireEvent.click(await screen.findByRole("button", { name: "Retry same request" }));
  expect(await screen.findByText("Try naming the invariant.")).toBeInTheDocument(); expect(keys).toHaveLength(2); expect(keys[0]).toBe(keys[1]);
});

test("accepted coach run resumes after polling failure without a second logical message", async () => {
  const keys: string[] = [];
  let runGets = 0;
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    if (url.endsWith("/status")) return json({ status: "ready", enabled: true, provider: "ollama", model: "m" });
    if (url.includes("/sessions/s-retry/conversations") && !init?.method) return json([]);
    if (url.includes("/sessions/s-retry/conversations") && init?.method === "POST") return json({ id: "c-retry", scope: "session", scope_id: "s-retry", title: "Coach", created_at: "x", updated_at: "x" }, 201);
    if (url.endsWith("/conversations/c-retry/messages")) {
      keys.push(JSON.parse(String(init?.body)).idempotency_key);
      return json({ run: { id: "r-retry", conversation_id: "c-retry", kind: "chat", scope: "session", scope_id: "s-retry", status: "queued", attempts: 0, max_attempts: 2, created_at: "x", updated_at: "x" }, created: true }, 202);
    }
    if (url.endsWith("/runs/r-retry")) {
      runGets++;
      return runGets === 1 ? json({ detail: "poll unavailable" }, 500) : json({ id: "r-retry", conversation_id: "c-retry", kind: "chat", scope: "session", scope_id: "s-retry", status: "completed", attempts: 1, max_attempts: 2, created_at: "x", updated_at: "x" });
    }
    if (url.endsWith("/conversations/c-retry")) return json({ id: "c-retry", scope: "session", scope_id: "s-retry", title: "Coach", created_at: "x", updated_at: "x", messages: [{ id: "u1", role: "user", content: "One question", run_id: "r-retry", created_at: "x" }, { id: "a1", role: "assistant", content: "One answer", run_id: "r-retry", created_at: "x" }] });
    throw new Error(`unexpected ${url}`);
  });
  render(<CoachPanel scope={{ scope: "session", id: "s-retry" }} />);
  fireEvent.change(await screen.findByLabelText("Your reasoning or question"), { target: { value: "One question" } });
  fireEvent.click(screen.getByRole("button", { name: "Ask coach" }));
  fireEvent.click(await screen.findByRole("button", { name: "Resume accepted request" }));
  expect(await screen.findByText("One answer")).toBeInTheDocument();
  expect(keys).toHaveLength(1);
  expect(screen.getAllByText("One question")).toHaveLength(1);
});

test("semantic visualization renders model strings as text and rejects dangling events", () => {
  render(<ArtifactVisualization artifact={{ schema_version: "visualization@1", renderer: "state-trace@1", title: "<img src=x onerror=alert(1)>", entities: [{ id: "safe", label: "<script>alert(1)</script>", kind: "item", data: {} }], events: [{ op: "visit", targets: ["missing"], note: "unsafe" }] }} />);
  expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument(); expect(document.querySelector("script")).toBeNull(); expect(screen.getByText("Step 0 / 0")).toBeInTheDocument();
});

test("diagnosis labels hypotheses as unconfirmed and sparse evidence", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(input => String(input).endsWith("/status") ? json({ status: "ready", enabled: true, provider: "ollama", model: "m" }) : json([{ id: "a", scope: "learning", scope_id: "learner", kind: "diagnosis", version: 1, schema_version: "diagnosis@1", run_id: "r", context_snapshot_id: "s", prompt_version: "p", provider: "ollama", model: "m", created_at: "2026-01-01", content: { schema_version: "diagnosis@1", observations: [], hypotheses: [{ type: "brain_trap", status: "candidate", statement: "May rush", confidence: .3, evidence: [] }], interventions: [{ action: "Write an invariant", rationale: "Test the hypothesis", requires_user_action: true }] } }]));
  render(<DiagnosisPanel />); expect(await screen.findByText(/candidate · 30% confidence · unconfirmed/)).toBeInTheDocument(); expect(screen.getByText(/Sparse evidence — confidence is capped/)).toBeInTheDocument(); expect(screen.getByText("User action required")).toBeInTheDocument();
});

test("setup exposes guidance but no credential field or value", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation(() => json({ status: "disabled", enabled: false, provider: "ollama", model: "llama3.2" })); render(<AISetupView />);
  expect(await screen.findByText("Community AI is disabled.")).toBeInTheDocument(); expect(screen.getByText(/docker compose --profile ai up -d/)).toBeInTheDocument(); expect(document.querySelector('input[type="password"]')).toBeNull(); expect(screen.getByText(/cannot read or write provider keys/)).toBeInTheDocument();
});
