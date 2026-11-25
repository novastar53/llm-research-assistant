"""Pure graph algorithms: assembly validation and traversal.

No Git I/O happens here; the repository layer supplies validated nodes and
edges. All results are deterministic: nodes sorted by ID, edges by
(source, target), traversal results sorted by ID with no duplicates and the
starting node excluded.
"""

from __future__ import annotations

from collections import deque

from .errors import GraphError
from .models import Edge, Experiment, ExperimentGraph


def assemble_graph(nodes: list[Experiment], edges: list[Edge]) -> ExperimentGraph:
    """Validate structure (duplicate IDs, edge endpoints, cycles) and sort.

    Parent existence and pin validity are the repository layer's job; this
    function assumes edges only reference known nodes.
    """
    ids: list[str] = []
    for node in nodes:
        ids.append(node.manifest.id)
    duplicates = sorted({exp_id for exp_id in ids if ids.count(exp_id) > 1})
    if duplicates:
        raise GraphError(f"duplicate experiment ID(s): {', '.join(duplicates)}")

    known = set(ids)
    for edge in edges:
        if edge.source not in known or edge.target not in known:
            raise GraphError(
                f"edge {edge.source!r} -> {edge.target!r} references an unknown experiment"
            )

    _reject_cycles(ids, edges)

    return ExperimentGraph(
        nodes=sorted(nodes, key=lambda n: n.manifest.id),
        edges=sorted(edges, key=lambda e: (e.source, e.target)),
    )


def _reject_cycles(ids: list[str], edges: list[Edge]) -> None:
    """Kahn's algorithm; any leftover nodes participate in a cycle."""
    indegree = {exp_id: 0 for exp_id in ids}
    children: dict[str, list[str]] = {}
    for edge in edges:
        indegree[edge.target] += 1
        children.setdefault(edge.source, []).append(edge.target)

    queue: deque[str] = deque(sorted(exp_id for exp_id, d in indegree.items() if d == 0))
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for child in children.get(node, []):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    if visited < len(ids):
        cyclic = sorted(exp_id for exp_id, d in indegree.items() if d > 0)
        raise GraphError("experiment graph contains a cycle involving: " + ", ".join(cyclic))


def ancestors(experiment_id: str, edges: list[Edge]) -> list[str]:
    """All transitive parents of *experiment_id*, sorted, excluding itself."""
    return _traverse(experiment_id, edges, forward=False)


def descendants(experiment_id: str, edges: list[Edge]) -> list[str]:
    """All transitive children of *experiment_id*, sorted, excluding itself."""
    return _traverse(experiment_id, edges, forward=True)


def _traverse(experiment_id: str, edges: list[Edge], *, forward: bool) -> list[str]:
    # forward=True walks parent -> child (descendants); key is the node we
    # index adjacency by, neighbour is where an edge leads from that node.
    key = (lambda e: e.source) if forward else (lambda e: e.target)
    neighbour = (lambda e: e.target) if forward else (lambda e: e.source)
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        adjacency.setdefault(key(edge), []).append(neighbour(edge))

    seen: set[str] = set()
    stack = list(adjacency.get(experiment_id, []))
    while stack:
        node = stack.pop()
        if node == experiment_id or node in seen:
            continue
        seen.add(node)
        stack.extend(adjacency.get(node, []))
    return sorted(seen)
