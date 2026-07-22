import type { VisualEntity, VisualEvent, VisualizationArtifact } from "../types";

export const GRAPH_RENDERER_V1 = "graph-trace@1";
export const GRAPH_RENDERER_V2 = "graph-trace@2";
export const GRAPH_WIDTH = 720;
export const GRAPH_HEIGHT = 420;
const PAD_X = 66;
const PAD_Y = 54;
const SAFE_ID = /^[A-Za-z0-9_.:-]{1,80}$/;
const EVENT_OPS = new Set(["show", "hide", "visit", "compare", "update", "push", "pop", "move", "select", "phase", "accept", "reject", "union", "complete"]);

export interface GraphNode extends VisualEntity { kind: "node"; x: number; y: number }
export interface GraphEdge extends VisualEntity { kind: "edge"; from: string; to: string; weight: string; index: number }
export interface GraphModel {
  renderer: string;
  entities: VisualEntity[];
  nodes: GraphNode[];
  edges: GraphEdge[];
  frames: VisualEntity[];
  items: VisualEntity[];
  events: VisualEvent[];
  labels: Map<string, string>;
}

export interface GraphSnapshot {
  hidden: Set<string>;
  visited: Set<string>;
  accepted: Set<string>;
  rejected: Set<string>;
  comparing: Set<string>;
  selected: Set<string>;
  metrics: Map<string, string>;
  parent: Map<string, string>;
  phase: string | null;
  completed: Set<string>;
  event: VisualEvent | null;
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function textValue(value: unknown, fallback = "—"): string {
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean" ? String(value) : fallback;
}

function normalize(value: number, min: number, max: number, start: number, span: number): number {
  return max === min ? start + span / 2 : start + ((value - min) / (max - min)) * span;
}

/** Parse only documented fields. Nothing supplied by the model is spread onto DOM/SVG nodes. */
export function createGraphModel(artifact: VisualizationArtifact): GraphModel {
  const seen = new Set<string>();
  const entities = artifact.entities.filter((entity) => {
    if (!SAFE_ID.test(entity.id) || seen.has(entity.id)) return false;
    seen.add(entity.id);
    return true;
  });
  const rawNodes = entities.filter((entity): entity is VisualEntity & { kind: "node" } => entity.kind === "node");
  const validCoordinates = rawNodes.map((node) => ({ x: finite(node.data.x), y: finite(node.data.y) }));
  const xs = validCoordinates.flatMap((point) => point.x === null ? [] : [point.x]);
  const ys = validCoordinates.flatMap((point) => point.y === null ? [] : [point.y]);
  const minX = xs.length ? Math.min(...xs) : 0;
  const maxX = xs.length ? Math.max(...xs) : 0;
  const minY = ys.length ? Math.min(...ys) : 0;
  const maxY = ys.length ? Math.max(...ys) : 0;
  const nodes: GraphNode[] = rawNodes.map((node, index) => {
    const angle = rawNodes.length === 1 ? -Math.PI / 2 : -Math.PI / 2 + (index * Math.PI * 2) / rawNodes.length;
    const fallbackX = GRAPH_WIDTH / 2 + Math.cos(angle) * Math.min(245, GRAPH_WIDTH * .32);
    const fallbackY = GRAPH_HEIGHT / 2 + Math.sin(angle) * Math.min(145, GRAPH_HEIGHT * .34);
    const point = validCoordinates[index];
    return {
      ...node,
      x: point.x === null ? fallbackX : normalize(point.x, minX, maxX, PAD_X, GRAPH_WIDTH - PAD_X * 2),
      y: point.y === null ? fallbackY : normalize(point.y, minY, maxY, PAD_Y, GRAPH_HEIGHT - PAD_Y * 2),
    };
  });
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges: GraphEdge[] = entities
    .filter((entity): entity is VisualEntity & { kind: "edge" } => entity.kind === "edge")
    .flatMap((edge, order) => {
      const from = typeof edge.data.from === "string" ? edge.data.from : "";
      const to = typeof edge.data.to === "string" ? edge.data.to : "";
      if (!nodeIds.has(from) || !nodeIds.has(to)) return [];
      return [{
        ...edge,
        from,
        to,
        weight: textValue(edge.data.weight, edge.label),
        index: finite(edge.data.index) ?? order,
      }];
    })
    .sort((a, b) => a.index - b.index || a.id.localeCompare(b.id));
  const ids = new Set(entities.map((entity) => entity.id));
  const events = artifact.events.filter((event) =>
    EVENT_OPS.has(event.op) && event.targets.length > 0 && event.targets.every((id) => ids.has(id)),
  );
  return {
    renderer: artifact.renderer,
    entities,
    nodes,
    edges,
    frames: entities.filter((entity) => entity.kind === "frame"),
    items: entities.filter((entity) => entity.kind === "item"),
    events,
    labels: new Map(entities.map((entity) => [entity.id, entity.label])),
  };
}

function initialSnapshot(model: GraphModel): GraphSnapshot {
  return {
    hidden: new Set(), visited: new Set(), accepted: new Set(), rejected: new Set(), comparing: new Set(), selected: new Set(),
    metrics: new Map(model.items.map((item) => [item.id, textValue(item.data.value)])),
    parent: new Map(model.nodes.map((node) => [node.id, node.id])), phase: null, completed: new Set(), event: null,
  };
}

function copy(previous: GraphSnapshot, event: VisualEvent): GraphSnapshot {
  return {
    hidden: new Set(previous.hidden), visited: new Set(previous.visited), accepted: new Set(previous.accepted), rejected: new Set(previous.rejected),
    comparing: new Set(), selected: new Set(previous.selected), metrics: new Map(previous.metrics),
    parent: new Map(previous.parent), phase: previous.phase, completed: new Set(previous.completed), event,
  };
}

function root(parent: Map<string, string>, id: string): string {
  let current = id;
  while (parent.has(current) && parent.get(current) !== current) current = parent.get(current)!;
  return current;
}

function union(parent: Map<string, string>, from: string, to: string): void {
  const a = root(parent, from);
  const b = root(parent, to);
  if (a !== b) parent.set(b, a);
}

/** Materialize every step so seeking backward never attempts to invert events. */
export function replayGraph(model: GraphModel): GraphSnapshot[] {
  const base = initialSnapshot(model);
  const snapshots = [base];
  const byId = new Map(model.entities.map((entity) => [entity.id, entity]));
  for (const event of model.events) {
    let next = copy(snapshots[snapshots.length - 1], event);
    const selectedFrame = model.renderer === GRAPH_RENDERER_V2 && event.op === "phase"
      ? event.targets.find((id) => byId.get(id)?.kind === "frame") : undefined;
    if (selectedFrame) {
      const reset = initialSnapshot(model);
      reset.phase = selectedFrame;
      reset.event = event;
      next = reset;
    }
    for (const id of event.targets) {
      const entity = byId.get(id)!;
      if (event.op === "show") next.hidden.delete(id);
      if (event.op === "hide") next.hidden.add(id);
      if (event.op === "compare" && entity.kind === "edge") next.comparing.add(id);
      if (event.op === "visit") next.visited.add(id);
      if (event.op === "select") next.selected.add(id);
      if (model.renderer === GRAPH_RENDERER_V2 && event.op === "accept" && entity.kind === "edge") {
        next.accepted.add(id);
        next.rejected.delete(id);
      }
      if (model.renderer === GRAPH_RENDERER_V2 && event.op === "reject" && entity.kind === "edge") {
        next.rejected.add(id);
        next.accepted.delete(id);
      }
      if (model.renderer === GRAPH_RENDERER_V2 && event.op === "complete" && entity.kind === "frame") next.completed.add(id);
      if (event.op === "update" && entity.kind === "item") next.metrics.set(id, textValue(event.value));
    }
    if (model.renderer === GRAPH_RENDERER_V2 && event.op === "union" && event.targets.length === 2) {
      union(next.parent, event.targets[0], event.targets[1]);
    }
    snapshots.push(next);
  }
  return snapshots;
}

export function dsuGroups(snapshot: GraphSnapshot, model: GraphModel): string[][] {
  const groups = new Map<string, string[]>();
  for (const node of model.nodes) {
    const group = root(snapshot.parent, node.id);
    groups.set(group, [...(groups.get(group) ?? []), node.label]);
  }
  return [...groups.values()];
}
