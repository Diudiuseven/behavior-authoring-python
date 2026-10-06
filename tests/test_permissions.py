"""发布与回滚的权限区分：越权必须被拒绝并留下可追溯记录。"""
import pytest

from behavior_authoring.models import PermissionDeniedError
from tests.conftest import make_graph


def _prepare_valid_draft(service, graph_id="g"):
    service.create_draft(graph_id, "editor")
    service.save_draft(graph_id, make_graph(), 0, "editor")


def test_editor_cannot_publish(service, authorizer):
    _prepare_valid_draft(service)
    with pytest.raises(PermissionDeniedError, match="无权执行 publish"):
        service.publish("g", "editor")
    # 拒绝留下了审计记录
    denied = [r for r in authorizer.audit_log()
              if r.action == "publish" and not r.allowed]
    assert len(denied) == 1
    assert denied[0].actor == "editor"
    assert denied[0].graph_id == "g"
    assert "editor" in denied[0].reason


def test_publisher_cannot_rollback(service, authorizer):
    _prepare_valid_draft(service)
    service.publish("g", "publisher")
    with pytest.raises(PermissionDeniedError, match="无权执行 rollback"):
        service.rollback("g", 1, "publisher")
    denied = [r for r in authorizer.audit_log()
              if r.action == "rollback" and not r.allowed]
    assert len(denied) == 1
    assert denied[0].version == 1  # 审计记录包含目标版本号


def test_admin_can_rollback(service, authorizer):
    _prepare_valid_draft(service)
    service.publish("g", "publisher")
    rb = service.rollback("g", 1, "admin")
    assert rb.rollback_of == 1
    allowed = [r for r in authorizer.audit_log()
               if r.action == "rollback" and r.allowed]
    assert len(allowed) == 1


def test_unknown_user_rejected(service, authorizer):
    with pytest.raises(PermissionDeniedError):
        service.create_draft("g2", "stranger")
    assert any(r.actor == "stranger" and not r.allowed
               for r in authorizer.audit_log())


def test_audit_log_records_allowed_and_denied_in_order(service, authorizer):
    _prepare_valid_draft(service)
    service.publish("g", "publisher")
    with pytest.raises(PermissionDeniedError):
        service.rollback("g", 1, "editor")
    actions = [(r.actor, r.action, r.allowed) for r in authorizer.audit_log()]
    assert ("editor", "edit", True) in actions
    assert ("publisher", "publish", True) in actions
    assert ("editor", "rollback", False) in actions
