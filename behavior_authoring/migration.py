"""结构演进：把旧 schema 版本的图定义迁移到当前版本。

历史版本说明：
- v1：节点没有显式 param_refs，参数值里用 "$bb:<key>" 字符串表示黑板引用；
      黑板键没有类型声明。
- v2（当前）：参数引用通过 ParamRef 显式表达；黑板键必须带类型。

迁移规则：
- 迁移只发生在读取路径的副本上，已发布的不可变版本内容绝不被修改；
- 无法识别或来自未来的 schema 版本会抛 MigrationError 并说明原因。
"""
from __future__ import annotations

from .models import (
    SCHEMA_VERSION,
    BehaviorGraph,
    BlackboardKey,
    BlackboardType,
    MigrationError,
    Node,
    ParamRef,
)

_REF_PREFIX = "$bb:"


def migrate_graph(graph: BehaviorGraph) -> BehaviorGraph:
    """把受支持的历史 schema 版本的图迁移到当前版本（返回新对象）。"""
    v = graph.schema_version
    if v == SCHEMA_VERSION:
        return graph
    if v > SCHEMA_VERSION:
        raise MigrationError(
            f"图的 schema 版本 v{v} 高于服务端支持的 v{SCHEMA_VERSION}，"
            f"请升级服务端后再读取")
    if v < 1:
        raise MigrationError(f"无法识别的 schema 版本: v{v}")
    if v == 1:
        return _migrate_v1_to_v2(graph)
    raise MigrationError(f"没有从 v{v} 到 v{SCHEMA_VERSION} 的迁移路径")


def _migrate_v1_to_v2(graph: BehaviorGraph) -> BehaviorGraph:
    migrated_nodes: list[Node] = []
    for node in graph.nodes:
        refs = list(node.param_refs)
        params = dict(node.params)
        for param, value in list(params.items()):
            if isinstance(value, str) and value.startswith(_REF_PREFIX):
                key = value[len(_REF_PREFIX):]
                refs.append(ParamRef(param=param, blackboard_key=key))
                del params[param]
        migrated_nodes.append(Node(
            id=node.id, kind=node.kind, name=node.name,
            params=params, param_refs=tuple(refs),
        ))
    migrated_bb = tuple(
        BlackboardKey(name=k.name, type=k.type, default=k.default)
        if isinstance(k.type, BlackboardType)
        else BlackboardKey(name=k.name, type=BlackboardType(k.type),
                           default=k.default)
        for k in graph.blackboard
    )
    return BehaviorGraph(
        nodes=tuple(migrated_nodes),
        edges=graph.edges,
        blackboard=migrated_bb,
        schema_version=SCHEMA_VERSION,
    )
