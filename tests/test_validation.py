"""校验失败场景：错误必须定位到具体元素与原因。"""
import pytest

from behavior_authoring.models import (
    BehaviorGraph,
    BlackboardKey,
    BlackboardType,
    Edge,
    Node,
    NodeKind,
    ParamRef,
    ValidationFailedError,
)
from behavior_authoring.validation import validate_graph
from tests.conftest import make_graph


def test_valid_graph_passes(valid_graph):
    assert validate_graph(valid_graph).ok


def test_param_ref_to_unknown_blackboard_key():
    graph = make_graph(param_refs=[ParamRef("target", "missing_key")])
    result = validate_graph(graph)
    assert not result.ok
    issue = next(i for i in result.issues if i.code == "PARAM_REF_UNKNOWN_KEY")
    assert issue.element_kind == "param_ref"
    assert issue.element_id == "act.target"
    assert "missing_key" in issue.message


def test_edge_to_missing_node():
    graph = make_graph(extra_edges=[Edge("e9", "root", "ghost")])
    result = validate_graph(graph)
    issue = next(i for i in result.issues if i.code == "EDGE_TARGET_MISSING")
    assert issue.element_kind == "edge"
    assert issue.element_id == "e9"
    assert "ghost" in issue.message


def test_multiple_errors_reported_together():
    """成组校验：一次返回全部问题，而不是只报第一个。"""
    graph = BehaviorGraph(
        nodes=(Node("a", NodeKind.ACTION), Node("a", NodeKind.ACTION)),
        edges=(Edge("e1", "a", "ghost"),),
        blackboard=(BlackboardKey("k", BlackboardType.INT),
                    BlackboardKey("k", BlackboardType.INT)),
    )
    result = validate_graph(graph)
    codes = {i.code for i in result.issues}
    assert {"NODE_ID_DUPLICATE", "EDGE_TARGET_MISSING",
            "BB_NAME_DUPLICATE", "ROOT_MISSING"} <= codes


def test_cycle_detected():
    """s1 <-> s2 构成与 root 断开的环。"""
    graph = BehaviorGraph(
        nodes=(Node("root", NodeKind.ROOT),
               Node("a", NodeKind.ACTION),
               Node("s1", NodeKind.SEQUENCE), Node("s2", NodeKind.SEQUENCE)),
        edges=(Edge("e1", "root", "a"),
               Edge("e3", "s1", "s2"), Edge("e4", "s2", "s1")),
    )
    result = validate_graph(graph)
    cycle_nodes = {i.element_id for i in result.issues
                   if i.code == "GRAPH_CYCLE"}
    assert cycle_nodes == {"s1", "s2"}


def test_publish_rejected_when_invalid(service):
    """发布前强制校验：非法草稿不得发布，且不留下半个版本。"""
    service.create_draft("g", "editor")
    bad = make_graph(param_refs=[ParamRef("t", "nope")])
    service.save_draft("g", bad, 0, "editor")
    with pytest.raises(ValidationFailedError) as exc_info:
        service.publish("g", "publisher")
    assert any(i.code == "PARAM_REF_UNKNOWN_KEY"
               for i in exc_info.value.result.issues)
    assert service.list_versions("g") == []  # 原子性：没有残留版本
