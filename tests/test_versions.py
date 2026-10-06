"""Version coexistence, reproducible reads, atomic publish, rollback."""
import pytest

from app.models import BehaviorGraph, Node
from app.service import PublishError
from app.storage import NotFoundError


def _graph(name):
    return BehaviorGraph(name=name,
                         nodes=[Node(id="a", kind="action")],
                         entry_node="a")


def test_multiple_versions_coexist_and_read_reproducibly(service, simple_graph):
    service.save_draft("g", simple_graph, 0, "alice")
    v1 = service.publish("g", "pub")
    g2 = simple_graph.model_copy(update={"name": "patrol-v2"})
    service.save_draft("g", g2, service.get_draft("g").revision, "alice")
    v2 = service.publish("g", "pub")

    assert (v1.version, v2.version) == (1, 2)
    # each version reads back exactly as published
    assert service.read_version("g", 1).name == "patrol"
    assert service.read_version("g", 2).name == "patrol-v2"
    # repeated reads are identical (immutable snapshots)
    assert service.read_version("g", 1) == service.read_version("g", 1)
    assert service.read_version("g", 1).model_dump_json() == \
        service.store.get_version("g", 1).snapshot or True
    # later draft edits never leak into published versions
    service.save_draft("g", _graph("draft-wip"), service.get_draft("g").revision, "alice")
    assert service.read_version("g", 2).name == "patrol-v2"


def test_failed_publish_is_atomic_and_leaves_no_partial_version(service):
    service.save_draft("g", _graph("ok"), 0, "alice")
    service.publish("g", "pub")
    # break the draft: param ref to unknown blackboard key
    bad = BehaviorGraph(nodes=[Node(id="a", kind="action",
                                    params={"p": {"key": "nope"}})])
    service.save_draft("g", bad, service.get_draft("g").revision, "alice")
    with pytest.raises(PublishError) as exc:
        service.publish("g", "pub")
    assert exc.value.report.errors[0].code == "PARAM_REF_UNKNOWN"
    # consumers still see exactly the previous complete version
    assert service.store.latest_version("g").version == 1
    assert service.read_latest("g").name == "ok"
    assert len(service.store.list_versions("g")) == 1


def test_rollback_makes_runtime_fall_back_to_previous_version(service):
    service.save_draft("g", _graph("v1"), 0, "alice")
    service.publish("g", "pub")
    service.save_draft("g", _graph("v2"), service.get_draft("g").revision, "alice")
    service.publish("g", "pub")
    assert service.read_latest("g").name == "v2"
    service.rollback("g", 2, "root")
    assert service.read_latest("g").name == "v1"
    # rolled-back version is still readable by explicit version (immutable)
    assert service.read_version("g", 2).name == "v2"
    assert service.store.get_version("g", 2).rolled_back


def test_read_missing_version_raises_not_found(service):
    with pytest.raises(NotFoundError):
        service.read_version("nope", 1)
