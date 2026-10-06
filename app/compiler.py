"""Deterministic compile of graphs into a runtime plan, with content-hash cache.

Compilation is a pure function of the graph's canonical form, so results are
cached by content hash: unchanged definitions reuse the cached plan, and
recompiling the same definition always yields an identical plan.
"""
from __future__ import annotations

import hashlib
import json
import threading

from app.models import BehaviorGraph


def canonical_json(graph: BehaviorGraph) -> str:
    """Canonical serialization of the graph as published (order-preserving).

    Used for published snapshots, where byte-exact reproduction matters.
    """
    return graph.model_dump_json()


def _normalized(graph: BehaviorGraph) -> dict:
    """Order-insensitive normal form: two graphs with the same nodes, edges
    and blackboard keys normalize identically regardless of list order."""
    data = graph.model_dump()
    data["nodes"] = sorted(data["nodes"], key=lambda n: n["id"])
    data["edges"] = sorted(data["edges"], key=lambda e: e["id"])
    data["blackboard"] = sorted(data["blackboard"], key=lambda k: k["name"])
    return data


def content_hash(graph: BehaviorGraph) -> str:
    """Stable hash of the graph's normal form; same definition -> same hash,
    independent of node/edge listing order."""
    blob = json.dumps(_normalized(graph), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _compile(graph: BehaviorGraph) -> dict:
    """Build the runtime plan: adjacency, topological order, key requirements."""
    children: dict[str, list[str]] = {}
    for edge in graph.edges:
        children.setdefault(edge.source, []).append(edge.target)
    for lst in children.values():
        lst.sort()  # deterministic child order regardless of edge order

    entry = graph.entry_node
    if entry is None and graph.nodes:
        targets = {e.target for e in graph.edges}
        roots = sorted(n.id for n in graph.nodes if n.id not in targets)
        entry = roots[0] if roots else sorted(n.id for n in graph.nodes)[0]

    order: list[str] = []
    seen: set[str] = set()
    def visit(nid: str) -> None:
        if nid in seen:
            return
        seen.add(nid)
        order.append(nid)
        for c in children.get(nid, []):
            visit(c)
    if entry:
        visit(entry)

    return {
        "entry": entry,
        "order": order,
        "children": {k: v for k, v in sorted(children.items())},
        "guards": {e.id: e.guard for e in sorted(graph.edges, key=lambda e: e.id)
                   if e.guard},
        "blackboard": {k.name: {"type": k.type, "required": k.required,
                                "default": k.default}
                       for k in sorted(graph.blackboard, key=lambda k: k.name)},
        "node_kinds": {n.id: n.kind.value for n in sorted(graph.nodes, key=lambda n: n.id)},
    }


class CompileCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, dict] = {}
        self.hits = 0
        self.misses = 0

    def compile(self, graph: BehaviorGraph) -> dict:
        """Compile graph to a runtime plan; cached by content hash, deterministic."""
        key = content_hash(graph)
        with self._lock:
            plan = self._cache.get(key)
            if plan is not None:
                self.hits += 1
                return plan
        plan = _compile(graph)
        plan["content_hash"] = key
        with self._lock:
            self._cache[key] = plan
            self.misses += 1
        return plan
