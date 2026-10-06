"""大图编译：缓存复用与结果一致性。"""
import threading

from behavior_authoring.compiler import Compiler, content_hash
from behavior_authoring.models import (
    BehaviorGraph,
    CyclicGraphError,
    Edge,
    Node,
    NodeKind,
)
import pytest


def make_large_graph(n: int, reverse: bool = False) -> BehaviorGraph:
    """构造 n 个动作节点的大图：root -> seq -> n 个 action。"""
    nodes = [Node("root", NodeKind.ROOT), Node("seq", NodeKind.SEQUENCE)]
    nodes += [Node(f"a{i}", NodeKind.ACTION) for i in range(n)]
    edges = [Edge("e0", "root", "seq")]
    edges += [Edge(f"e{i+1}", "seq", f"a{i}") for i in range(n)]
    if reverse:
        nodes.reverse()
        edges.reverse()
    return BehaviorGraph(nodes=tuple(nodes), edges=tuple(edges))


def test_hash_is_order_independent():
    g1 = make_large_graph(200)
    g2 = make_large_graph(200, reverse=True)
    assert content_hash(g1) == content_hash(g2)


def test_compile_cache_reused(compiler):
    g = make_large_graph(500)
    r1 = compiler.compile(g)
    assert compiler.cache_size == 1
    # 定义未变（即使元素顺序不同）时复用缓存
    r2 = compiler.compile(make_large_graph(500, reverse=True))
    assert r2 is r1
    assert compiler.cache_size == 1
    # 定义变化后产生新缓存项
    r3 = compiler.compile(make_large_graph(501))
    assert r3.content_hash != r1.content_hash
    assert compiler.cache_size == 2


def test_compile_deterministic(compiler):
    g = make_large_graph(300)
    r1 = compiler.compile(g)
    r2 = Compiler().compile(g)  # 全新编译器也得到相同结果
    assert r1.content_hash == r2.content_hash
    assert r1.topo_order == r2.topo_order
    assert r1.children == r2.children


def test_concurrent_compile_consistent(compiler):
    g = make_large_graph(300)
    results = []

    def work():
        results.append(compiler.compile(g))

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(r is results[0] for r in results)
    assert compiler.cache_size == 1


def test_cycle_raises(compiler):
    g = BehaviorGraph(
        nodes=(Node("a", NodeKind.SEQUENCE), Node("b", NodeKind.SEQUENCE)),
        edges=(Edge("e1", "a", "b"), Edge("e2", "b", "a")),
    )
    with pytest.raises(CyclicGraphError, match="环"):
        compiler.compile(g)
