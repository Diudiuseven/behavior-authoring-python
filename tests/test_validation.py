"""Validation failures must be located at concrete elements with reasons."""
from app.models import BehaviorGraph, BlackboardKey, Edge, Node
from app.validation import validate_graph


def codes(report):
    return {i.code for i in report.issues}


def test_unknown_param_ref_located_at_node_and_field():
    g = BehaviorGraph(
        nodes=[Node(id="attack", kind="action",
                    params={"target": {"key": "enemy"}})],
        blackboard=[])
    r = validate_graph(g)
    assert not r.ok
    issue = next(i for i in r.issues if i.code == "PARAM_REF_UNKNOWN")
    assert issue.element_kind == "param"
    assert issue.element_id == "attack"
    assert issue.field == "target"
    assert "enemy" in issue.message


def test_edge_to_missing_node_and_guard_ref():
    g = BehaviorGraph(
        nodes=[Node(id="a", kind="sequence"), Node(id="b", kind="action")],
        edges=[Edge(id="e1", source="a", target="b"),
               Edge(id="e2", source="a", target="ghost", guard="hp > 3")],
        blackboard=[])
    r = validate_graph(g)
    assert "EDGE_TARGET_MISSING" in codes(r)
    assert "GUARD_REF_UNKNOWN" in codes(r)
    e = next(i for i in r.issues if i.code == "EDGE_TARGET_MISSING")
    assert e.element_id == "e2" and e.field == "target"


def test_group_validation_reports_all_problems_at_once():
    g = BehaviorGraph(
        nodes=[Node(id="a", kind="action"),
               Node(id="a", kind="action"),
               Node(id="orphan", kind="action")],
        edges=[Edge(id="e1", source="a", target="orphan")],
        blackboard=[BlackboardKey(name="k"), BlackboardKey(name="k")],
        entry_node="missing")
    r = validate_graph(g)
    assert not r.ok
    assert {"NODE_DUPLICATE", "BLACKBOARD_DUPLICATE", "ENTRY_MISSING",
            "LEAF_HAS_CHILDREN"} <= codes(r)


def test_unreachable_and_cycle_detected():
    g = BehaviorGraph(
        nodes=[Node(id="a", kind="sequence"), Node(id="b", kind="sequence"),
               Node(id="far", kind="action")],
        edges=[Edge(id="e1", source="a", target="b"),
               Edge(id="e2", source="b", target="a")],
        entry_node="a")
    r = validate_graph(g)
    assert "GRAPH_CYCLE" in codes(r)
    assert "NODE_UNREACHABLE" in codes(r)


def test_valid_graph_passes():
    g = BehaviorGraph(
        nodes=[Node(id="root", kind="sequence"),
               Node(id="chk", kind="condition",
                    params={"target": {"key": "enemy"}})],
        edges=[Edge(id="e1", source="root", target="chk", guard="alerted")],
        blackboard=[BlackboardKey(name="enemy", type="str"),
                    BlackboardKey(name="alerted", type="bool", default=False)],
        entry_node="root")
    r = validate_graph(g)
    assert r.ok, r.issues
