import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { api } from "../src/api";
import type { Bootstrap, ProblemSummary } from "../src/types";
import { ProblemCollectionView } from "../src/views/ProblemCollectionView";

const items: ProblemSummary[] = Array.from({ length: 25 }, (_, index) => ({
  id: index + 1,
  slug: `scale-problem-${index}`,
  title: `Scale Problem ${index}`,
  pattern_id: "graph/traversal",
  pattern_title: "Graph traversal",
  queue_state: "backlog",
  status: index === 0 ? "active" : "backlog",
  roadmap_week: Math.floor(index / 5),
  evidence_count: 0,
  independent_count: 0,
}));

const data = {
  patterns: [{
    id: "graph/traversal",
    title: "Graph traversal",
    description: "Traversal",
    recognition_signals: [],
    evidence_count: 0,
    independent_count: 0,
    confidence: "no private evidence",
  }],
} as unknown as Bootstrap;

function mockProblems() {
  return vi.spyOn(api, "problems").mockResolvedValue({
    items,
    total: 250,
    page: 1,
    page_size: 25,
    pages: 10,
    status_counts: { backlog: 250 },
    tracks: [
      { id: "outtalent", title: "Outtalent — Algorithms core program", kind: "formal", priority: 0 },
      { id: "deep-supplemental", title: "Deep supplemental roadmap", kind: "supplemental", priority: 100 },
    ],
  });
}

test("large collections render a bounded server page and send filters", async () => {
  const problems = mockProblems();

  render(<ProblemCollectionView data={data} navigate={() => {}} scope="queue" eyebrow="Queue" title="Scale" description="Test" allowBulk />);

  await waitFor(() => expect(screen.getByText(/1–25 of 250/)).toBeInTheDocument());
  expect(screen.getAllByRole("button", { name: /Scale Problem/ })).toHaveLength(25);
  expect(screen.getByText(/maximum 25 rendered/)).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Search problems"), { target: { value: "149" } });
  await waitFor(() => expect(problems).toHaveBeenLastCalledWith(expect.objectContaining({ search: "149" })));
  problems.mockRestore();
});

test("every rendered row carries a Practice action and an external link", async () => {
  const problems = mockProblems();
  const start = vi.spyOn(api, "startProblemSession").mockResolvedValue({
    session: { id: "ps-test-1", problem_id: 1, assignment_id: null, origin: "ad_hoc", status: "active", mode: "paper practice", goal: "", timebox_minutes: 35, highest_hint: null, started_at: "", updated_at: "" },
    problem: null,
    scheduled: null,
    hints: { availability: "available", provenance: "generated", scope: "skill", generator: "deterministic-skill-scaffold/1.0", label: "Generated hint ladder", levels: [] },
    lesson: { availability: "available", provenance: "generated", scope: "skill", generator: "deterministic-skill-scaffold/1.0", label: "Generated practice scaffold" },
  });
  const navigate = vi.fn();

  render(<ProblemCollectionView data={data} navigate={navigate} scope="all" eyebrow="Library" title="Practice any problem." description="Test" />);
  await waitFor(() => expect(screen.getAllByRole("button", { name: "Practice" })).toHaveLength(25));
  expect(screen.getAllByRole("link", { name: /Open .* on LeetCode/ })).toHaveLength(25);
  // The search field and filters come before the status strip in the DOM.
  const main = screen.getByRole("main");
  const toolbarIndex = Array.from(main.children).findIndex(el => el.classList.contains("collection-toolbar"));
  const stripIndex = Array.from(main.children).findIndex(el => el.classList.contains("status-strip"));
  expect(toolbarIndex).toBeGreaterThan(-1);
  expect(stripIndex).toBeGreaterThan(toolbarIndex);

  // Practice starts an ad hoc session and routes to that session's solve room.
  fireEvent.click(screen.getAllByRole("button", { name: "Practice" })[0]);
  await waitFor(() => expect(start).toHaveBeenCalledWith(1));
  expect(navigate).toHaveBeenCalledWith("solve/ps-test-1");

  start.mockRestore();
  problems.mockRestore();
});
