"""Compile cache: reused when definition unchanged, deterministic results."""
from app.compiler import CompileCache, content_hash
from app.models import BehaviorGraph, BlackboardKey, Edge, Node


def _big_graph(n=500):
    nodes = [Node(id="root", kind="sequence")]
    edges = []
    for i in range(n):
        nodes.append(Node(id=f"a{i}", kind="action",
                          params={"target": {"key": "enemy"}, "idx": i}))
        edges.append(Edge(id=f"e{i}", source="root", target=f"a{i}",
                          guard="alerted" if i % 2 else None))
    return BehaviorGraph(nodes=nodes, edges=edges, entry_node="root",
                         blackboard=[BlackboardKey(name="enemy", type="str"),
                                     BlackboardKey(name="alerted", type="bool")])


def test_unchanged_definition_reuses_cache():
    cache = CompileCache()
    g = _big_graph()
    p1 = cache.compile(g)
    p2 = cache.compile(g)
    assert p1 is p2  # same cached object
    assert cache.hits == 1 and cache.misses == 1


def test_recompile_is_deterministic_regardless_of_input_order():
    g1 = _big_graph(50)
    # same definition, nodes/edges listed in reverse order
    g2 = g1.model_copy(update={"nodes": list(reversed(g1.nodes)),
                               "edges": list(reversed(g1.edges))})
    cache = CompileCache()
    assert cache.compile(g1) == cache.compile(g2)


def test_changed_definition_gets_new_hash_and_plan():
    cache = CompileCache()
    g = _big_graph(10)
    p1 = cache.compile(g)
    g2 = g.model_copy(update={"name": "renamed"})
    p2 = cache.compile(g2)
    assert content_hash(g) != content_hash(g2)
    assert p1["content_hash"] != p2["content_hash"]
    assert cache.misses == 2


def test_service_serves_identical_plan_for_same_version(service, simple_graph):
    service.save_draft("g", simple_graph, 0, "alice")
    service.publish("g", "pub")
    plan1 = service.compile_version("g", 1)
    plan2 = service.compile_version("g", 1)
    assert plan1 == plan2
    assert service.cache.hits >= 1
