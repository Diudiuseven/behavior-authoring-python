"""Group validation of behavior graphs: nodes, edges, blackboard, param refs.

All rules run together and every finding is reported as a ValidationIssue
located at a concrete element (node id / edge id / blackboard key / graph),
so callers never get a single opaque error.
"""
from __future__ import annotations

import re
from typing import Any

from app.models import (
    BehaviorGraph,
    IssueSeverity,
    NodeKind,
    ParamRef,
    ValidationIssue,
    ValidationReport,
)

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_GUARD_TOKENS = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# words allowed in guard expressions that are not blackboard references
_GUARD_KEYWORDS = {"and", "or", "not", "true", "false", "none", "in"}


def _issue(code: str, message: str, kind: str, element_id: str,
           field: str | None = None,
           severity: IssueSeverity = IssueSeverity.ERROR) -> ValidationIssue:
    return ValidationIssue(severity=severity, code=code, message=message,
                           element_kind=kind, element_id=element_id, field=field)


def _param_refs(value: Any, path: str):
    """Yield (path, key) for every ParamRef-shaped value in a param tree."""
    if isinstance(value, dict):
        if set(value.keys()) == {"key"} and isinstance(value["key"], str):
            yield path, value["key"]
        else:
            for k, v in value.items():
                yield from _param_refs(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _param_refs(v, f"{path}[{i}]")


def validate_graph(graph: BehaviorGraph) -> ValidationReport:
    issues: list[ValidationIssue] = []

    # ---- blackboard group ----
    bb_names: set[str] = set()
    for key in graph.blackboard:
        if not _IDENT.fullmatch(key.name):
            issues.append(_issue("BLACKBOARD_NAME_INVALID",
                                 f"blackboard key {key.name!r} is not a valid identifier",
                                 "blackboard", key.name or "<empty>", "name"))
        if key.name in bb_names:
            issues.append(_issue("BLACKBOARD_DUPLICATE",
                                 f"duplicate blackboard key {key.name!r}",
                                 "blackboard", key.name, "name"))
        bb_names.add(key.name)
        if key.default is not None and not _type_matches(key.default, key.type):
            issues.append(_issue("BLACKBOARD_DEFAULT_TYPE",
                                 f"default {key.default!r} does not match type {key.type!r}",
                                 "blackboard", key.name, "default"))
        if key.required and key.default is None:
            issues.append(_issue("BLACKBOARD_REQUIRED_NO_DEFAULT",
                                 f"required key {key.name!r} has no default; "
                                 "runtime must supply it", "blackboard", key.name,
                                 "default", IssueSeverity.WARNING))

    # ---- node group ----
    node_ids: set[str] = set()
    for node in graph.nodes:
        if not node.id:
            issues.append(_issue("NODE_ID_EMPTY", "node id must not be empty",
                                 "node", "<empty>", "id"))
        if node.id in node_ids:
            issues.append(_issue("NODE_DUPLICATE", f"duplicate node id {node.id!r}",
                                 "node", node.id, "id"))
        node_ids.add(node.id)
        # param references must point at declared blackboard keys
        for pname, pval in node.params.items():
            for path, ref_key in _param_refs(pval, pname):
                if ref_key not in bb_names:
                    issues.append(_issue(
                        "PARAM_REF_UNKNOWN",
                        f"param {path!r} references unknown blackboard key {ref_key!r}",
                        "param", node.id, path))

    # ---- edge group ----
    edge_ids: set[str] = set()
    children: dict[str, list[str]] = {}
    for edge in graph.edges:
        if edge.id in edge_ids:
            issues.append(_issue("EDGE_DUPLICATE", f"duplicate edge id {edge.id!r}",
                                 "edge", edge.id, "id"))
        edge_ids.add(edge.id)
        for field, ref in (("source", edge.source), ("target", edge.target)):
            if ref not in node_ids:
                issues.append(_issue(
                    f"EDGE_{field.upper()}_MISSING",
                    f"edge {edge.id!r} {field} references unknown node {ref!r}",
                    "edge", edge.id, field))
        if edge.source == edge.target:
            issues.append(_issue("EDGE_SELF_LOOP",
                                 f"edge {edge.id!r} connects node {edge.source!r} to itself",
                                 "edge", edge.id))
        children.setdefault(edge.source, []).append(edge.target)
        if edge.guard:
            for tok in _GUARD_TOKENS.findall(edge.guard):
                if tok.lower() in _GUARD_KEYWORDS or tok.isdigit():
                    continue
                if tok not in bb_names:
                    issues.append(_issue(
                        "GUARD_REF_UNKNOWN",
                        f"guard references unknown blackboard key {tok!r}",
                        "edge", edge.id, "guard"))

    # ---- structural rules per node kind ----
    kind_by_id = {n.id: n.kind for n in graph.nodes}
    for node in graph.nodes:
        out = children.get(node.id, [])
        if node.kind in (NodeKind.ACTION, NodeKind.CONDITION) and out:
            issues.append(_issue(
                "LEAF_HAS_CHILDREN",
                f"{node.kind.value} node {node.id!r} must be a leaf but has "
                f"{len(out)} outgoing edge(s)", "node", node.id))
        if node.kind == NodeKind.DECORATOR and len(out) > 1:
            issues.append(_issue(
                "DECORATOR_ARITY",
                f"decorator node {node.id!r} must have at most 1 child, has {len(out)}",
                "node", node.id))

    # ---- graph-level: entry, reachability, cycles ----
    if graph.nodes:
        entry = graph.entry_node
        if entry is None:
            roots = [n.id for n in graph.nodes
                     if n.id not in {e.target for e in graph.edges}]
            if len(roots) == 1:
                entry = roots[0]
            else:
                issues.append(_issue(
                    "ENTRY_AMBIGUOUS",
                    f"no entry_node set and {len(roots)} root candidates exist",
                    "graph", "graph", "entry_node"))
        elif entry not in node_ids:
            issues.append(_issue("ENTRY_MISSING",
                                 f"entry_node {entry!r} is not a node in the graph",
                                 "graph", "graph", "entry_node"))
        if entry and entry in node_ids:
            reachable = _reachable(entry, children)
            for nid in sorted(node_ids - reachable):
                issues.append(_issue("NODE_UNREACHABLE",
                                     f"node {nid!r} is not reachable from entry {entry!r}",
                                     "node", nid))
            cycle = _find_cycle(entry, children)
            if cycle:
                issues.append(_issue("GRAPH_CYCLE",
                                     "cycle detected: " + " -> ".join(cycle),
                                     "graph", "graph"))

    return ValidationReport(ok=not any(i.severity == IssueSeverity.ERROR for i in issues),
                            issues=issues)


def _type_matches(value: Any, type_name: str) -> bool:
    return {"int": lambda v: isinstance(v, int) and not isinstance(v, bool),
            "float": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
            "str": lambda v: isinstance(v, str),
            "bool": lambda v: isinstance(v, bool)}[type_name](value)


def _reachable(entry: str, children: dict[str, list[str]]) -> set[str]:
    seen, stack = set(), [entry]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(children.get(cur, []))
    return seen


def _find_cycle(entry: str, children: dict[str, list[str]]) -> list[str] | None:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {entry: WHITE}
    stack: list[tuple[str, list[str]]] = [(entry, [])]
    while stack:
        node, path = stack[-1]
        if color.get(node, WHITE) == WHITE:
            color[node] = GRAY
            path = path + [node]
            stack[-1] = (node, path)
            for nxt in children.get(node, []):
                if color.get(nxt, WHITE) == GRAY:
                    i = path.index(nxt)
                    return path[i:] + [nxt]
                if color.get(nxt, WHITE) == WHITE:
                    stack.append((nxt, path))
        else:
            color[node] = BLACK
            stack.pop()
    return None
