"""多版本共存、按版本读取的可复现性、发布原子性。"""
import pytest

from behavior_authoring.models import NotFoundError, ParamRef
from tests.conftest import make_graph


def _publish(service, graph_id, graph, revision, actor="publisher"):
    service.save_draft(graph_id, graph, revision, "editor")
    return service.publish(graph_id, actor)


def test_multiple_versions_coexist(service, valid_graph):
    service.create_draft("g", "editor")
    v1 = _publish(service, "g", valid_graph, 0)
    v2 = _publish(service, "g", make_graph(suffix="_v2"), v1 and 1)
    v3 = _publish(service, "g", make_graph(suffix="_v3"), 2)

    versions = service.list_versions("g")
    assert [v.version for v in versions] == [1, 2, 3]
    # 每个版本内容独立且与发布时一致
    pv1, _ = service.read_version("g", 1)
    pv2, _ = service.read_version("g", 2)
    assert pv1.graph.nodes[2].id == "act"
    assert pv2.graph.nodes[2].id == "act_v2"
    # latest 指向最新完整版本
    pv_latest, _ = service.read_latest("g")
    assert pv_latest.version == 3


def test_read_is_reproducible(service, valid_graph):
    """同一版本重复读取，内容与编译产物哈希完全一致。"""
    service.create_draft("g", "editor")
    _publish(service, "g", valid_graph, 0)
    pv_a, compiled_a = service.read_version("g", 1)
    pv_b, compiled_b = service.read_version("g", 1)
    assert pv_a == pv_b
    assert compiled_a.content_hash == compiled_b.content_hash
    assert compiled_a.topo_order == compiled_b.topo_order


def test_failed_publish_leaves_no_partial_version(service):
    """校验失败的发布不得留下半个版本，latest 保持指向旧版本。"""
    service.create_draft("g", "editor")
    _publish(service, "g", make_graph(), 0)
    # 第二次保存为非法图，发布失败
    service.save_draft("g", make_graph(param_refs=[ParamRef("t", "nope")]),
                       1, "editor")
    with pytest.raises(Exception):
        service.publish("g", "publisher")
    assert [v.version for v in service.list_versions("g")] == [1]
    pv_latest, _ = service.read_latest("g")
    assert pv_latest.version == 1


def test_rollback_creates_new_version_without_touching_history(
        service, valid_graph):
    service.create_draft("g", "editor")
    _publish(service, "g", valid_graph, 0)
    _publish(service, "g", make_graph(suffix="_v2"), 1)

    rb = service.rollback("g", 1, "admin")
    assert rb.version == 3
    assert rb.rollback_of == 1
    # 回滚版本内容与 v1 一致（内容哈希相同）
    pv1, _ = service.read_version("g", 1)
    assert rb.compiled_hash == pv1.compiled_hash
    # 历史版本未被修改
    pv2, _ = service.read_version("g", 2)
    assert pv2.graph.nodes[2].id == "act_v2"
    # latest 现在指向回滚产生的新版本
    pv_latest, _ = service.read_latest("g")
    assert pv_latest.version == 3


def test_read_missing_version(service):
    with pytest.raises(NotFoundError):
        service.read_version("g", 99)
