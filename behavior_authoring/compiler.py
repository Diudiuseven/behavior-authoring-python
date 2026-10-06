"""编译器：把行为图编译为运行时结构，并按内容哈希缓存。

关键语义：
- content_hash 对图内容做规范化（排序）后哈希，与输入中节点/连线的
  排列顺序无关，保证“定义未变则哈希不变”；
- 编译结果按内容哈希缓存，重复编译返回同一结果，不产生不一致；
- 编译过程确定性：同一内容永远得到同一 CompiledGraph。
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict

from .models import (
    BehaviorGraph,
    CompiledGraph,
    CyclicGraphError,
    Node,
    BlackboardKey,
)


def _canonical(graph: BehaviorGraph) -> dict:
    """把图规范化为与元素顺序无关的字典结构。"""
    nodes = sorted(
        (
            {
                "id": n.id,
                "kind": n.kind.value,
                "name": n.name,
                "params": n.params,
                "param_refs": sorted(
                    ({"param": r.param, "blackboard_key": r.blackboard_key}
                     for r in n.param_refs),
                    key=lambda r: (r["param"], r["blackboard_key"]),
                ),
            }
            for n in graph.nodes
        ),
        key=lambda n: n["id"],
    )
    edges = sorted(
        ({"id": e.id, "source": e.source, "target": e.target}
         for e in graph.edges),
        key=lambda e: e["id"],
    )
    blackboard = sorted(
        ({"name": k.name, "type": k.type.value, "default": k.default}
         for k in graph.blackboard),
        key=lambda k: k["name"],
    )
    return {
        "schema_version": graph.schema_version,
        "nodes": nodes,
        "edges": edges,
        "blackboard": blackboard,
    }


def content_hash(graph: BehaviorGraph) -> str:
    """计算图内容的确定性哈希。"""
    payload = json.dumps(_canonical(graph), sort_keys=True,
                         ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Compiler:
    """编译并缓存结果。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[str, CompiledGraph] = {}

    def compile(self, graph: BehaviorGraph) -> CompiledGraph:
        h = content_hash(graph)
        with self._lock:
            cached = self._cache.get(h)
            if cached is not None:
                return cached
        compiled = self._do_compile(graph, h)
        with self._lock:
            # 并发编译同一内容时，以先写入者为准，保证返回同一对象。
            return self._cache.setdefault(h, compiled)

    @property
    def cache_size(self) -> int:
        with self._lock:
            return len(self._cache)

    @staticmethod
    def _do_compile(graph: BehaviorGraph, h: str) -> CompiledGraph:
        node_index: dict[str, Node] = {n.id: n for n in graph.nodes}
        children_map: dict[str, list[str]] = {n.id: [] for n in graph.nodes}
        indegree: dict[str, int] = {n.id: 0 for n in graph.nodes}
        for edge in graph.edges:
            if edge.source in node_index and edge.target in node_index:
                children_map[edge.source].append(edge.target)
                indegree[edge.target] += 1
        # 子节点按 id 排序，保证编译结果确定。
        children = {k: tuple(sorted(v)) for k, v in children_map.items()}

        # Kahn 拓扑排序，同层按 id 排序保证确定性。
        ready = sorted(nid for nid, d in indegree.items() if d == 0)
        topo: list[str] = []
        indeg = dict(indegree)
        while ready:
            nid = ready.pop(0)
            topo.append(nid)
            for child in children.get(nid, ()):
                indeg[child] -= 1
                if indeg[child] == 0:
                    ready.append(child)
            ready.sort()
        if len(topo) != len(node_index):
            unresolved = sorted(set(node_index) - set(topo))
            raise CyclicGraphError(
                f"图存在环，无法编译，涉及节点: {', '.join(unresolved)}")

        blackboard_index: dict[str, BlackboardKey] = {
            k.name: k for k in graph.blackboard}
        return CompiledGraph(
            content_hash=h,
            topo_order=tuple(topo),
            children=children,
            node_index=node_index,
            blackboard_index=blackboard_index,
        )
