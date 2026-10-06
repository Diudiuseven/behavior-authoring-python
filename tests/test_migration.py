"""结构演进：旧 schema 版本在新结构下可读/可迁移，已发布版本不被改动。"""
import pytest

from behavior_authoring.migration import migrate_graph
from behavior_authoring.models import (
    SCHEMA_VERSION,
    BehaviorGraph,
    BlackboardKey,
    BlackboardType,
    Edge,
    MigrationError,
    Node,
    NodeKind,
    ParamRef,
)


def _v1_graph() -> BehaviorGraph:
    """v1 结构：用 "$bb:<key>" 字符串参数表示黑板引用。"""
    return BehaviorGraph(
        nodes=(
            Node("root", NodeKind.ROOT),
            Node("act", NodeKind.ACTION,
                 params={"target": "$bb:enemy", "speed": 3}),
        ),
        edges=(Edge("e1", "root", "act"),),
        blackboard=(BlackboardKey("enemy", BlackboardType.STRING),),
        schema_version=1,
    )


def test_v1_graph_migrates_to_current():
    new = migrate_graph(_v1_graph())
    assert new.schema_version == SCHEMA_VERSION
    assert new.nodes[1].param_refs == (ParamRef("target", "enemy"),)
    assert new.nodes[1].params == {"speed": 3}  # 非引用参数保留


def test_migration_does_not_mutate_original():
    old = _v1_graph()
    migrate_graph(old)
    assert old.schema_version == 1
    assert old.nodes[1].params["target"] == "$bb:enemy"


def test_unmigratable_future_version_raises():
    with pytest.raises(MigrationError, match="高于服务端支持"):
        migrate_graph(BehaviorGraph(schema_version=SCHEMA_VERSION + 1))


def test_unmigratable_unknown_version_raises():
    with pytest.raises(MigrationError, match="无法识别"):
        migrate_graph(BehaviorGraph(schema_version=0))


def test_publish_normalizes_to_current_schema(service):
    """发布会把草稿迁移到当前 schema 后再固化。"""
    service.create_draft("g", "editor")
    service.save_draft("g", _v1_graph(), 0, "editor")
    pv = service.publish("g", "publisher")
    assert pv.graph.schema_version == SCHEMA_VERSION


def test_old_published_version_readable_after_evolution(service):
    """旧服务端以 v1 结构发布的版本，升级到 v2 后仍可按版本读取。"""
    # 模拟旧服务端留下的 v1 版本（直接写入存储层）
    service._store.publish("g", _v1_graph(), published_by="old-server",
                           source_draft_revision=0, compiled_hash="legacy")
    pv_read, compiled = service.read_version("g", 1)
    # 存储内容保持 v1 原样（不可变）
    assert pv_read.graph.schema_version == 1
    # 读取时在副本上迁移，编译产物基于新结构
    assert compiled.node_index["act"].param_refs == (ParamRef("target", "enemy"),)
    # 再次读取结果一致（可复现）
    _, compiled2 = service.read_version("g", 1)
    assert compiled2.content_hash == compiled.content_hash
