"""Publish/rollback permission separation with traceable audit records."""
import pytest

from app.auth import PermissionDenied
from app.models import BehaviorGraph, Node


def _publishable(service, graph_id="g"):
    g = BehaviorGraph(nodes=[Node(id="a", kind="action")], entry_node="a")
    service.save_draft(graph_id, g, 0, "alice")


def test_editor_cannot_publish_and_attempt_is_audited(service):
    _publishable(service)
    with pytest.raises(PermissionDenied):
        service.publish("g", "alice")  # alice is an EDITOR
    denied = [r for r in service.audit_log()
              if r.action == "publish" and not r.allowed]
    assert len(denied) == 1
    assert denied[0].actor == "alice" and denied[0].graph_id == "g"
    assert "lacks publish permission" in denied[0].detail
    # no version was created by the rejected attempt
    assert service.store.latest_version("g") is None


def test_publisher_cannot_rollback(service):
    _publishable(service)
    service.publish("g", "pub")
    with pytest.raises(PermissionDenied):
        service.rollback("g", 1, "pub")  # PUBLISHER is not ADMIN
    assert not service.store.get_version("g", 1).rolled_back
    denied = [r for r in service.audit_log()
              if r.action == "rollback" and not r.allowed]
    assert len(denied) == 1 and denied[0].actor == "pub"


def test_admin_rollback_and_allowed_actions_are_audited(service):
    _publishable(service)
    service.publish("g", "pub")
    service.rollback("g", 1, "root")
    allowed = [(r.actor, r.action) for r in service.audit_log() if r.allowed]
    assert ("pub", "publish") in allowed
    assert ("root", "rollback") in allowed


def test_anonymous_actor_cannot_even_save(service):
    with pytest.raises(PermissionDenied):
        service.save_draft("g", BehaviorGraph(), 0, "stranger")
