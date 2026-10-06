"""Optimistic concurrency: simultaneous saves must not silently overwrite."""
import threading

import pytest

from app.models import BehaviorGraph, Node
from app.storage import ConflictError


def test_concurrent_save_loser_gets_explainable_conflict(service):
    service.save_draft("g", BehaviorGraph(name="v0"), base_revision=0, actor="alice")
    # both editors fetched revision 1 and now save concurrently
    service.save_draft("g", BehaviorGraph(name="bob-wins"), base_revision=1, actor="bob")
    with pytest.raises(ConflictError) as exc:
        service.save_draft("g", BehaviorGraph(name="alice-loses"),
                           base_revision=1, actor="alice")
    err = exc.value
    assert err.expected == 1 and err.actual == 2
    assert err.holder == "bob"  # who won the race is explained
    assert "reload" in str(err)
    # the winner's data is intact, not silently overwritten
    assert service.get_draft("g").graph.name == "bob-wins"


def test_loser_can_retry_after_reload(service):
    service.save_draft("g", BehaviorGraph(name="a"), base_revision=0, actor="alice")
    service.save_draft("g", BehaviorGraph(name="b"), base_revision=1, actor="bob")
    with pytest.raises(ConflictError):
        service.save_draft("g", BehaviorGraph(name="a2"), base_revision=1, actor="alice")
    current = service.get_draft("g").revision
    draft = service.save_draft("g", BehaviorGraph(name="a2"),
                               base_revision=current, actor="alice")
    assert draft.graph.name == "a2"


def test_parallel_threads_exactly_one_winner_per_revision(service):
    service.save_draft("g", BehaviorGraph(), base_revision=0, actor="alice")
    results = []

    def save(i):
        name = f"edit-{i}"
        try:
            service.save_draft("g", BehaviorGraph(name=name), base_revision=1,
                               actor="alice" if i % 2 else "bob")
            results.append(("ok", name))
        except ConflictError:
            results.append(("conflict", name))

    threads = [threading.Thread(target=save, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    winners = [n for status, n in results if status == "ok"]
    assert len(winners) == 1
    assert service.get_draft("g").revision == 2
