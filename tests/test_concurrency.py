"""草稿并发编辑：乐观并发策略，冲突方可解释，不静默覆盖。"""
import threading

import pytest

from behavior_authoring.models import ConflictError
from tests.conftest import make_graph


def test_stale_revision_rejected_with_explanation(service):
    service.create_draft("g", "editor")
    d0 = service.get_draft("g")
    # 两个编辑者都基于 revision 0 编辑
    service.save_draft("g", make_graph(), d0.revision, "editor")
    with pytest.raises(ConflictError) as exc_info:
        service.save_draft("g", make_graph(suffix="_x"), d0.revision, "publisher")
    err = exc_info.value
    # 冲突信息可解释：说明谁把草稿推进到了哪个 revision
    assert err.expected_revision == 0
    assert err.actual_revision == 1
    assert "editor" in str(err)
    # 先保存者的内容未被静默覆盖
    assert service.get_draft("g").graph.nodes[2].id == "act"


def test_retry_with_fresh_revision_succeeds(service):
    service.create_draft("g", "editor")
    service.save_draft("g", make_graph(), 0, "editor")
    fresh = service.get_draft("g")
    saved = service.save_draft("g", make_graph(suffix="_y"),
                               fresh.revision, "publisher")
    assert saved.revision == 2
    assert saved.graph.nodes[2].id == "act_y"


def test_concurrent_saves_exactly_one_winner(service):
    """多线程同时保存同一 revision：只有一个成功，其余收到冲突。"""
    service.create_draft("g", "editor")
    results, errors = [], []

    def save(i):
        try:
            results.append(service.save_draft(
                "g", make_graph(suffix=f"_{i}"), 0, "editor"))
        except ConflictError as e:
            errors.append(e)

    threads = [threading.Thread(target=save, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 1
    assert len(errors) == 7
    assert all(e.actual_revision == 1 for e in errors)
    assert service.get_draft("g").revision == 1
