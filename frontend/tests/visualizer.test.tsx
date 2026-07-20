import { fireEvent, render, screen } from "@testing-library/react";
import { AlgorithmVisualizer } from "../src/components/AlgorithmVisualizer";
import type { Lesson } from "../src/types";

const lesson: Lesson = {
  pattern: { title: "Low-link", invariant: "low", failure_modes: [] },
  graph: { nodes: [{ id: 0, x: 10, y: 10 }, { id: 1, x: 50, y: 50 }], edges: [[0, 1]] },
  trace: [
    { type: "reset", copy: "Topology first" },
    { type: "tree_edge", from: 0, to: 1, copy: "Explore edge" },
  ],
};

test("visualizer advances semantic events", () => {
  render(<AlgorithmVisualizer lesson={lesson} />);
  expect(screen.getByText("Topology first")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Next event" }));
  expect(screen.getByText("Explore edge")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: /low-link/i })).toBeInTheDocument();
});
