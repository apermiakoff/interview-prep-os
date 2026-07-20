from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RoadmapEntry:
    title: str
    slug: str
    week: int
    position: int
    pattern_id: str


PATTERN_CATALOG = [
    {
        "id": "graph/low-link-bridges",
        "title": "Low-link bridges",
        "description": "Compress alternate-route reachability into one DFS invariant.",
        "recognition_signals": ["undirected cuts", "bridge edges", "alternate routes"],
    },
    {
        "id": "graph/traversal",
        "title": "Graph traversal",
        "description": "Model reachability, layers, components, and dependency order.",
        "recognition_signals": ["reachability", "shortest unweighted path", "components"],
    },
    {
        "id": "graph/connectivity-paths",
        "title": "Connectivity & shortest paths",
        "description": "Choose between union-find, Dijkstra, minimax paths, and spanning trees.",
        "recognition_signals": ["dynamic connectivity", "weighted path", "minimum connection cost"],
    },
    {
        "id": "graph/modeling",
        "title": "Advanced graph modeling",
        "description": (
            "Turn implicit states, equations, and itinerary constraints into graph structure."
        ),
        "recognition_signals": [
            "implicit transitions",
            "weighted relations",
            "specialized traversal",
        ],
    },
    {
        "id": "backtracking/decision-tree",
        "title": "Backtracking",
        "description": "Define choices, constraints, goals, and exact state restoration.",
        "recognition_signals": ["enumerate combinations", "undo a choice", "constraint search"],
    },
    {
        "id": "dp/one-dimensional",
        "title": "1D dynamic programming",
        "description": "Give every state a precise meaning before deriving transitions.",
        "recognition_signals": [
            "overlapping prefixes",
            "take or skip",
            "optimization over choices",
        ],
    },
    {
        "id": "dp/multidimensional",
        "title": "2D & state-machine DP",
        "description": "Derive dimensions from the minimum information defining a subproblem.",
        "recognition_signals": ["two sequence positions", "explicit modes", "richer memo state"],
    },
    {
        "id": "search/monotonic",
        "title": "Binary search & monotonic structures",
        "description": "Use monotonic feasibility, boundaries, stacks, and ordered processing.",
        "recognition_signals": ["monotonic predicate", "next greater", "ordered collapse"],
    },
    {
        "id": "greedy/heaps",
        "title": "Greedy, intervals & heaps",
        "description": "State the exchange argument or maintained top-k frontier.",
        "recognition_signals": ["interval choice", "local exchange", "streaming top-k"],
    },
    {
        "id": "mixed/design",
        "title": "Mixed interview set",
        "description": "High-frequency data-structure, window, and practical design exercises.",
        "recognition_signals": ["API design", "sliding window", "custom data structure"],
    },
    {
        "id": "trie/trees",
        "title": "Tries & trees",
        "description": "Build prefix structure and state recursive tree invariants precisely.",
        "recognition_signals": ["prefix lookup", "tree serialization", "ancestor/path invariant"],
    },
]

WEEK_PATTERNS = {
    0: "graph/connectivity-paths",
    1: "graph/traversal",
    2: "graph/connectivity-paths",
    3: "graph/modeling",
    4: "backtracking/decision-tree",
    5: "dp/one-dimensional",
    6: "dp/multidimensional",
    7: "search/monotonic",
    8: "greedy/heaps",
    9: "mixed/design",
    10: "trie/trees",
}


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def parse_roadmap(path: Path) -> list[RoadmapEntry]:
    """Extract real named problems from the user's twelve-week Markdown roadmap."""
    if not path.exists():
        return []
    current_week: int | None = None
    positions: dict[int, int] = {}
    entries: list[RoadmapEntry] = []
    seen: set[str] = set()
    non_problems = {"output", "exit condition", "dp rule", "september 15"}
    for line in path.read_text(encoding="utf-8").splitlines():
        week_match = re.match(r"^## Week (\d+)", line)
        if week_match:
            current_week = int(week_match.group(1))
            if current_week > 10:
                current_week = None
            continue
        if current_week is None:
            continue
        for title in re.findall(r"\*\*([^*]+)\*\*", line):
            title = title.strip()
            if title.rstrip(":").lower() in non_problems:
                continue
            slug = slugify(title)
            if not title or slug in seen:
                continue
            seen.add(slug)
            position = positions.get(current_week, 0)
            positions[current_week] = position + 1
            pattern_id = WEEK_PATTERNS[current_week]
            if slug == "critical-connections-in-a-network":
                pattern_id = "graph/low-link-bridges"
            entries.append(
                RoadmapEntry(
                    title=title,
                    slug=slug,
                    week=current_week,
                    position=position,
                    pattern_id=pattern_id,
                )
            )
    return entries
