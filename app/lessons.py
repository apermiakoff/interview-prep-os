from __future__ import annotations

LOW_LINK_PATTERN = {
    "id": "graph/low-link-bridges",
    "title": "Low-link bridges",
    "description": "Compress alternate-route reachability into one DFS invariant.",
    "recognition_signals": [
        "Removing one edge may disconnect an undirected graph",
        "Need all critical edges in linear time",
        "Subtree must report whether it can reach an ancestor",
    ],
    "invariant": (
        "low[u] is the earliest DFS entry reachable from u's subtree without using the parent edge."
    ),
    "failure_modes": [
        "Merging low[v] for a visited non-parent neighbor instead of tin[v]",
        "Using >= instead of > in the bridge condition",
        "Skipping every edge to parent in a multigraph rather than one parent edge",
    ],
}

LOW_LINK_TRACE = [
    {"type": "reset", "title": "Topology", "copy": "Cycles create alternate routes; tails do not."},
    {"type": "visit_node", "node": 0, "tin": 0, "low": 0, "copy": "Start DFS at node 0."},
    {"type": "tree_edge", "from": 0, "to": 1, "copy": "Edge 0–1 becomes a DFS-tree edge."},
    {
        "type": "visit_node",
        "node": 1,
        "tin": 1,
        "low": 1,
        "copy": "Node 1 starts with low[1] = tin[1].",
    },
    {"type": "tree_edge", "from": 1, "to": 2, "copy": "Continue into node 2."},
    {"type": "visit_node", "node": 2, "tin": 2, "low": 2, "copy": "Node 2 starts with low[2] = 2."},
    {
        "type": "back_edge",
        "from": 2,
        "to": 0,
        "copy": "Visited non-parent neighbor: merge tin[0], not low[0].",
    },
    {
        "type": "merge_low",
        "node": 2,
        "old": 2,
        "new": 0,
        "copy": "The cycle lets node 2 reach ancestor 0.",
    },
    {
        "type": "merge_low",
        "node": 1,
        "old": 1,
        "new": 0,
        "copy": "After child 2 returns, merge low[2] into low[1].",
    },
    {
        "type": "bridge_check",
        "from": 0,
        "to": 1,
        "bridge": False,
        "copy": "low[1] = 0 is not greater than tin[0] = 0.",
    },
    {"type": "tree_edge", "from": 1, "to": 3, "copy": "Explore the tail rooted at node 3."},
    {
        "type": "visit_node",
        "node": 3,
        "tin": 3,
        "low": 3,
        "copy": "No back edge leaves node 3's subtree.",
    },
    {
        "type": "bridge_check",
        "from": 1,
        "to": 3,
        "bridge": True,
        "copy": "low[3] = 3 > tin[1] = 1, so 1–3 is a bridge.",
    },
    {"type": "tree_edge", "from": 3, "to": 4, "copy": "The same logic continues down the tail."},
    {
        "type": "bridge_check",
        "from": 3,
        "to": 4,
        "bridge": True,
        "copy": "No alternate route bypasses 3–4.",
    },
]

GRAPH = {
    "nodes": [
        {"id": 0, "x": 130, "y": 150},
        {"id": 1, "x": 300, "y": 72},
        {"id": 2, "x": 300, "y": 228},
        {"id": 3, "x": 470, "y": 72},
        {"id": 4, "x": 630, "y": 72},
    ],
    "edges": [[0, 1], [1, 2], [2, 0], [1, 3], [3, 4]],
}

# Hand-authored hint ladder for the low-link pattern (originally written for the
# Critical Connections assignment). Curated content; never mixed with generated.
LOW_LINK_HINTS = {
    "H1": "Can one DFS summarize whether a child's subtree has any alternative route "
    "back to the already visited part of the graph?",
    "H2": "Track discovery time and the earliest discovery time reachable from each "
    "DFS subtree without using its parent edge.",
    "H3": "Use Tarjan-style low-link DFS. Compare the child's low value with the "
    "parent's discovery time.",
    "H4": "Set tin[u] and low[u] on entry. For a visited non-parent neighbor v, "
    "minimize low[u] with tin[v]. After an unvisited child v returns, minimize "
    "low[u] with low[v]. Edge (u,v) is a bridge exactly when low[v] > tin[u].",
}


def lesson_for(pattern_id: str | None) -> dict | None:
    if pattern_id == LOW_LINK_PATTERN["id"]:
        return {"pattern": LOW_LINK_PATTERN, "graph": GRAPH, "trace": LOW_LINK_TRACE}
    return None


def curated_hints_for(pattern_id: str | None) -> dict[str, str] | None:
    if pattern_id == LOW_LINK_PATTERN["id"]:
        return dict(LOW_LINK_HINTS)
    return None


def lesson_payload() -> dict:
    """Backward-compatible bootstrap lesson for the active low-link assignment."""
    return lesson_for(LOW_LINK_PATTERN["id"]) or {}
