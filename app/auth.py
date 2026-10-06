"""Role-based permissions for publish/rollback plus an audit trail.

Every permission decision, allowed or denied, is appended to the audit log
so unauthorized publish/rollback attempts are traceable.
"""
from __future__ import annotations

import threading
import time

from app.models import AuditRecord, Role

# action -> roles permitted to perform it
_ACTION_ROLES: dict[str, set[Role]] = {
    "save_draft": {Role.EDITOR, Role.PUBLISHER, Role.ADMIN},
    "publish": {Role.PUBLISHER, Role.ADMIN},
    "rollback": {Role.ADMIN},
}


class PermissionDenied(Exception):
    def __init__(self, actor: str, action: str):
        self.actor = actor
        self.action = action
        super().__init__(f"actor {actor!r} is not allowed to {action!r}")


class Authorizer:
    def __init__(self, roles: dict[str, Role] | None = None):
        self._roles: dict[str, Role] = dict(roles or {})
        self._log: list[AuditRecord] = []
        self._lock = threading.Lock()

    def set_role(self, actor: str, role: Role) -> None:
        self._roles[actor] = role

    def check(self, actor: str, action: str, graph_id: str) -> None:
        """Raise PermissionDenied (and record it) if the actor lacks the role."""
        role = self._roles.get(actor)
        allowed_roles = _ACTION_ROLES.get(action, set())
        allowed = role is not None and role in allowed_roles
        detail = (f"role {role.value} permitted" if allowed else
                  f"role {role.value if role else '<none>'} lacks {action} permission")
        record = AuditRecord(actor=actor, action=action, graph_id=graph_id,
                             allowed=allowed, detail=detail, timestamp=time.time())
        with self._lock:
            self._log.append(record)
        if not allowed:
            raise PermissionDenied(actor, action)

    def audit_log(self) -> list[AuditRecord]:
        with self._lock:
            return list(self._log)
