"""行为图成组校验：节点、连线、黑板键、参数引用整体校验。

设计要点：
- 一次校验收集全部问题，不遇到第一个错误就停止；
- 每个问题都定位到具体元素（element_kind + element_id）并给出原因；
- 节点、连线、黑板键、参数引用作为一组交叉校验（如连线端点必须存在、
  参数引用必须指向已声明的黑板键）。
"""
from __future__ import annotations

from .models import (
    BehaviorGraph,
    IssueSeverity,
    NodeKind,
    ValidationIssue,
    ValidationResult,
)

# 叶子节点类型：不允许有子节点。
_LEAF_KINDS = {NodeKind.ACTION, NodeKind.CONDITION}
# 有且仅有一个 root，且 root 不允许有入边。


def _err(code: str, message: str, kind: str, element_id: str) -> ValidationIssue:
    return ValidationIssue(IssueSeverity.ERROR, code, message, kind, element_id)


def validate_graph(graph: BehaviorGraph) -> ValidationResult:
    issues: list[ValidationIssue] = []

    # ---- 节点组内校验 ----
    node_ids: set[str] = set()
    root_count = 0
    for node in graph.nodes:
        if not node.id:
            issues.append(_err("NODE_ID_EMPTY", "节点 id 不能为空", "node", "<empty>"))
            continue
        if node.id in node_ids:
            issues.append(_err("NODE_ID_DUPLICATE", f"节点 id 重复: {node.id}", "node", node.id))
        node_ids.add(node.id)
        if node.kind == NodeKind.ROOT:
            root_count += 1

    if root_count == 0:
        issues.append(_err("ROOT_MISSING", "图中必须恰好有一个 root 节点", "graph", "<graph>"))
    elif root_count > 1:
        issues.append(_err("ROOT_MULTIPLE", f"root 节点过多: {root_count} 个", "graph", "<graph>"))

    # ---- 黑板键组内校验 ----
    bb_names: set[str] = set()
    for key in graph.blackboard:
        if not key.name:
            issues.append(_err("BB_NAME_EMPTY", "黑板键名不能为空", "blackboard", "<empty>"))
            continue
        if key.name in bb_names:
            issues.append(_err("BB_NAME_DUPLICATE", f"黑板键重复: {key.name}", "blackboard", key.name))
        bb_names.add(key.name)

    # ---- 参数引用 vs 黑板键 交叉校验 ----
    for node in graph.nodes:
        for ref in node.param_refs:
            if ref.blackboard_key not in bb_names:
                issues.append(_err(
                    "PARAM_REF_UNKNOWN_KEY",
                    f"节点 {node.id} 的参数 {ref.param} 引用了未声明的黑板键 "
                    f"{ref.blackboard_key}",
                    "param_ref",
                    f"{node.id}.{ref.param}",
                ))

    # ---- 连线 vs 节点 交叉校验 ----
    edge_ids: set[str] = set()
    child_of: dict[str, str] = {}   # target -> edge id（树结构：每个节点至多一个父）
    has_child: set[str] = set()     # 有出边的节点
    for edge in graph.edges:
        if edge.id in edge_ids:
            issues.append(_err("EDGE_ID_DUPLICATE", f"连线 id 重复: {edge.id}", "edge", edge.id))
        edge_ids.add(edge.id)
        if edge.source not in node_ids:
            issues.append(_err(
                "EDGE_SOURCE_MISSING",
                f"连线 {edge.id} 的源节点 {edge.source} 不存在",
                "edge", edge.id,
            ))
        if edge.target not in node_ids:
            issues.append(_err(
                "EDGE_TARGET_MISSING",
                f"连线 {edge.id} 的目标节点 {edge.target} 不存在",
                "edge", edge.id,
            ))
        if edge.target in child_of:
            issues.append(_err(
                "EDGE_MULTIPLE_PARENTS",
                f"节点 {edge.target} 被多条连线（{child_of[edge.target]}, {edge.id}）"
                f"指向，行为树中每个节点至多一个父节点",
                "edge", edge.id,
            ))
        child_of[edge.target] = edge.id
        has_child.add(edge.source)

    # ---- 结构约束：叶子不能有子节点，非叶子（root 除外）必须有 ----
    for node in graph.nodes:
        if node.kind in _LEAF_KINDS and node.id in has_child:
            issues.append(_err(
                "LEAF_HAS_CHILDREN",
                f"叶子节点 {node.id}（{node.kind.value}）不允许有子节点",
                "node", node.id,
            ))
        if node.kind in (NodeKind.SEQUENCE, NodeKind.SELECTOR) and node.id not in has_child:
            issues.append(_err(
                "COMPOSITE_NO_CHILDREN",
                f"组合节点 {node.id}（{node.kind.value}）至少需要一个子节点",
                "node", node.id,
            ))

    # ---- 连通性与环检测（从 root 出发应能到达所有节点，且无环）----
    adjacency: dict[str, list[str]] = {}
    for edge in graph.edges:
        if edge.source in node_ids and edge.target in node_ids:
            adjacency.setdefault(edge.source, []).append(edge.target)

    roots = [n.id for n in graph.nodes if n.kind == NodeKind.ROOT]
    visited: set[str] = set()
    if roots:
        # 迭代式 DFS，避免大图递归过深。
        stack = list(roots)
        on_stack: set[str] = set()
        while stack:
            nid = stack.pop()
            if nid in visited:
                continue
            visited.add(nid)
            for child in adjacency.get(nid, []):
                stack.append(child)
        # 环检测：树约束（单父）下，不可达且存在入边的子图即为环。
        for node in graph.nodes:
            if node.id not in visited and node.id in child_of:
                issues.append(_err(
                    "GRAPH_CYCLE",
                    f"节点 {node.id} 位于环中或与 root 断开的子图内",
                    "node", node.id,
                ))
    for node in graph.nodes:
        if roots and node.id not in visited and node.id not in child_of \
                and node.kind != NodeKind.ROOT:
            issues.append(_err(
                "NODE_UNREACHABLE",
                f"节点 {node.id} 从 root 不可达",
                "node", node.id,
            ))

    return ValidationResult(tuple(issues))
