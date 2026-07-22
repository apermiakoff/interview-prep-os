import { act, fireEvent, render, screen } from "@testing-library/react";
import { ArtifactVisualization } from "../src/components/ArtifactVisualization";
import type { VisualizationArtifact } from "../src/types";

const fixture: VisualizationArtifact = {
  schema_version: "visualization@1",
  renderer: "graph-trace@2",
  title: "#1489 Critical edges",
  entities: [
    { id: "a", label: "A", kind: "node", data: { x: 100, y: 50 } },
    { id: "b", label: "B", kind: "node", data: { x: 300, y: 50 } },
    { id: "c", label: "C", kind: "node", data: {} },
    { id: "e1", label: "A–B", kind: "edge", data: { from: "a", to: "b", weight: 1, index: 0 } },
    { id: "e2", label: "B–C", kind: "edge", data: { from: "b", to: "c", weight: 2, index: 1 } },
    { id: "e3", label: "A–C", kind: "edge", data: { from: "a", to: "c", weight: 3, index: 2 } },
    { id: "base", label: "Baseline MST", kind: "frame", data: { goal: "Build reference weight" } },
    { id: "exclude", label: "Exclude e1", kind: "frame", data: { goal: "Test criticality" } },
    { id: "cost", label: "MST weight", kind: "item", data: { value: 0 } },
  ],
  events: [
    { op: "phase", targets: ["base"], note: "Start baseline" },
    { op: "compare", targets: ["e1"], note: "Compare lightest edge" },
    { op: "accept", targets: ["e1"], note: "Accept A–B" },
    { op: "union", targets: ["a", "b"], note: "Merge A and B" },
    { op: "update", targets: ["cost"], value: 1, note: "Weight is one" },
    { op: "reject", targets: ["e2"], note: "Reject B–C" },
    { op: "hide", targets: ["e3"], note: "Exclude A–C" },
    { op: "phase", targets: ["exclude"], note: "Reset for exclusion phase" },
    { op: "complete", targets: ["exclude"], note: "Finish exclusion phase" },
  ],
};

function next(times = 1) {
  const button = screen.getByRole("button", { name: "Next visualization step" });
  for (let index = 0; index < times; index += 1) fireEvent.click(button);
}

test("renders a safe responsive SVG with weighted edges before nodes and deterministic fallback coordinates", () => {
  const { container } = render(<ArtifactVisualization artifact={fixture} />);
  const svg = screen.getByRole("img", { name: /critical edges, weighted graph/i });
  expect(svg).toHaveAttribute("viewBox", "0 0 720 420");
  expect(screen.getByText("1", { selector: ".edge-weight" })).toBeInTheDocument();
  const edge = container.querySelector('[data-entity-id="e1"]')!;
  const node = container.querySelector('[data-entity-id="a"]')!;
  expect(edge.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  const fallback = container.querySelector('[data-entity-id="c"]')!;
  expect(fallback.getAttribute("transform")).toMatch(/^translate\([\d.]+ [\d.]+\)$/);
});

test("replays persistent edge, metric, hidden and DSU state then resets it at a phase boundary", () => {
  const { container } = render(<ArtifactVisualization artifact={fixture} />);
  next(4);
  expect(container.querySelector('[data-entity-id="e1"]')).toHaveClass("is-accepted");
  expect(screen.getByLabelText("Disjoint set inspector")).toHaveTextContent("A · B");
  next();
  expect(screen.getByLabelText("Metrics")).toHaveTextContent("MST weight1");
  expect(container.querySelector('[data-entity-id="e1"]')).toHaveClass("is-accepted");
  next();
  expect(container.querySelector('[data-entity-id="e2"]')).toHaveClass("is-rejected");
  next();
  expect(container.querySelector('[data-entity-id="e3"]')).not.toBeInTheDocument();
  next();
  expect(container.querySelector('[data-entity-id="e1"]')).not.toHaveClass("is-accepted");
  expect(container.querySelector('[data-entity-id="e2"]')).not.toHaveClass("is-rejected");
  expect(container.querySelector('[data-entity-id="e3"]')).toBeInTheDocument();
  expect(screen.getByLabelText("Metrics")).toHaveTextContent("MST weight0");
  expect(screen.getByText("Exclude e1").closest("li")).toHaveAttribute("aria-current", "step");
  next();
  expect(screen.getByText("Exclude e1").closest("li")).toHaveClass("is-complete");
});

test("supports buttons, range seeking, playback, and graph keyboard shortcuts", () => {
  vi.useFakeTimers();
  render(<ArtifactVisualization artifact={fixture} />);
  next(2);
  expect(screen.getByText("Step 2 / 9")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("slider", { name: "Visualization step" }), { target: { value: "4" } });
  expect(screen.getByText("Step 4 / 9")).toBeInTheDocument();
  const runtime = screen.getByRole("region", { name: /critical edges visualization/i });
  runtime.focus();
  fireEvent.keyDown(runtime, { key: "Home" });
  expect(screen.getByText("Step 0 / 9")).toBeInTheDocument();
  fireEvent.keyDown(runtime, { key: "PageDown" });
  expect(screen.getByText("Step 5 / 9")).toBeInTheDocument();
  fireEvent.keyDown(runtime, { key: "ArrowLeft" });
  expect(screen.getByText("Step 4 / 9")).toBeInTheDocument();
  fireEvent.keyDown(runtime, { key: "End" });
  expect(screen.getByText("Step 9 / 9")).toBeInTheDocument();
  fireEvent.keyDown(runtime, { key: " " });
  expect(screen.getByRole("button", { name: "Pause visualization" })).toBeInTheDocument();
  fireEvent.keyDown(runtime, { key: "Home" });
  act(() => vi.advanceTimersByTime(850));
  expect(screen.getByText("Step 1 / 9")).toBeInTheDocument();
  vi.useRealTimers();
});

test("uses exact renderer lookup and provides a clear generic fallback", () => {
  render(<ArtifactVisualization artifact={{ ...fixture, renderer: "graph-trace@1-extra" }} />);
  expect(screen.getByText("Unsupported renderer")).toBeInTheDocument();
  expect(screen.getByText(/No registered renderer/)).toBeInTheDocument();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});

test("keeps graph-trace@1 DFS visit and select generic without invented MST or DSU state", () => {
  const artifact: VisualizationArtifact = {
    ...fixture,
    renderer: "graph-trace@1",
    entities: fixture.entities.filter((entity) => ["a", "b", "e1"].includes(entity.id)),
    events: [
      { op: "visit", targets: ["a", "e1"], note: "DFS reaches B" },
      { op: "select", targets: ["e1"], note: "Focus edge" },
    ],
  };
  const { container } = render(<ArtifactVisualization artifact={artifact} />);
  next();
  expect(container.querySelector('[data-entity-id="a"]')).toHaveClass("is-visited");
  expect(container.querySelector('[data-entity-id="e1"]')).toHaveClass("is-visited");
  next();
  expect(container.querySelector('[data-entity-id="e1"]')).toHaveClass("is-selected");
  expect(container.querySelector('[data-entity-id="e1"]')).not.toHaveClass("is-accepted", "is-rejected");
  expect(screen.queryByLabelText("Disjoint set inspector")).not.toBeInTheDocument();
  expect(screen.queryByText("Accepted")).not.toBeInTheDocument();
});

test("replays non-graph renderers with values, visibility, active state, controls, and keyboard", () => {
  const artifact: VisualizationArtifact = {
    schema_version: "visualization@1", renderer: "dp-table@1", title: "DP replay",
    entities: [
      { id: "cell", label: "dp[1]", kind: "cell", data: { value: 0 } },
      { id: "pointer", label: "cursor", kind: "pointer", data: {} },
    ],
    events: [
      { op: "update", targets: ["cell"], value: 7, note: "Set value" },
      { op: "hide", targets: ["pointer"], note: "Hide cursor" },
      { op: "show", targets: ["pointer"], note: "Show cursor" },
    ],
  };
  const { container } = render(<ArtifactVisualization artifact={artifact} />);
  expect(screen.getByText("Step 0 / 3")).toBeInTheDocument();
  next();
  expect(container.querySelector('[data-entity-id="cell"]')).toHaveClass("is-active");
  expect(screen.getByText("7", { selector: "output" })).toBeInTheDocument();
  next();
  expect(container.querySelector('[data-entity-id="pointer"]')).not.toBeInTheDocument();
  const runtime = screen.getByRole("region", { name: /DP replay visualization/i });
  runtime.focus();
  fireEvent.keyDown(runtime, { key: "End" });
  expect(screen.getByText("Step 3 / 3")).toBeInTheDocument();
  expect(container.querySelector('[data-entity-id="pointer"]')).toBeInTheDocument();
});

test("renders hostile labels as text without model-controlled markup or attributes", () => {
  const hostile = `<img src=x onerror=alert(1)><script>x</script><style>*{display:none}</style><a href=javascript:x>`;
  const artifact: VisualizationArtifact = {
    ...fixture,
    title: hostile,
    entities: fixture.entities.map((entity, index) => index === 0 ? { ...entity, label: hostile, data: { x: 0, y: 0, style: "display:none", href: "javascript:alert(1)" } } : entity),
  };
  const { container } = render(<ArtifactVisualization artifact={artifact} />);
  expect(screen.getAllByText(hostile).length).toBeGreaterThan(0);
  expect(container.querySelector("script, style, img, a")).toBeNull();
  expect(container.querySelector('[style], [href]')).toBeNull();
});
