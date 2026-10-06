"""权限与审计：区分编辑、发布与回滚权限，所有判定留痕。"""
from __future__ import annotations

import threading

from .models import AuditRecord, PermissionDeniedError


class Role:
    EDITOR = "editor"        # 可编辑草稿
    PUBLISHER = "publisher"  # 可编辑 + 发布
    ADMIN = "admin"          # 可编辑 + 发布 + 回滚


# action -> 允许的角色集合
_ACTION_ROLES: dict[str, frozenset[str]] = {
    "edit": frozenset({Role.EDITOR, Role.PUBLISHER, Role.ADMIN}),
    "publish": frozenset({Role.PUBLISHER, Role.ADMIN}),
    "rollback": frozenset({Role.ADMIN}),
}


class Authorizer:
    """基于角色的权限检查；允许与拒绝都会写入审计日志。"""

    def __init__(self, role_by_user: dict[str, str]) -> None:
        self._role_by_user = dict(role_by_user)
        self._lock = threading.Lock()
        self._audit: list[AuditRecord] = []

    def check(self, actor: str, action: str, graph_id: str,
              version: int | None = None) -> None:
        """无权限时抛 PermissionDeniedError，并留下审计记录。"""
        role = self._role_by_user.get(actor)
        allowed_roles = _ACTION_ROLES.get(action, frozenset())
        allowed = role in allowed_roles
        if allowed:
            reason = f"角色 {role} 允许执行 {action}"
        else:
            reason = (f"用户 {actor} 的角色 {role or '<未注册>'} "
                      f"无权执行 {action}（需要: "
                      f"{', '.join(sorted(allowed_roles)) or '无'}）")
        self._record(actor, action, graph_id, version, allowed, reason)
        if not allowed:
            raise PermissionDeniedError(reason)

    def _record(self, actor: str, action: str, graph_id: str,
                version: int | None, allowed: bool, reason: str) -> None:
        with self._lock:
            self._audit.append(AuditRecord(
                actor=actor, action=action, graph_id=graph_id,
                version=version, allowed=allowed, reason=reason,
            ))

    def audit_log(self) -> list[AuditRecord]:
        with self._lock:
            return list(self._audit)
