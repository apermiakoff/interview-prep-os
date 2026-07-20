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
  status: "backlog",
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

test("large collections render a bounded server page and send filters", async () => {
  const problems = vi.spyOn(api, "problems").mockResolvedValue({
    items,
    total: 250,
    page: 1,
    page_size: 25,
    pages: 10,
    status_counts: { backlog: 250 },
  });

  render(<ProblemCollectionView data={data} navigate={() => {}} scope="queue" eyebrow="Queue" title="Scale" description="Test" allowBulk />);

  await waitFor(() => expect(screen.getByText(/1–25 of 250/)).toBeInTheDocument());
  expect(screen.getAllByRole("button", { name: /Scale Problem/ })).toHaveLength(25);
  expect(screen.getByText(/maximum 25 rendered/)).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("Search problems"), { target: { value: "149" } });
  await waitFor(() => expect(problems).toHaveBeenLastCalledWith(expect.objectContaining({ search: "149" })));
  problems.mockRestore();
});
