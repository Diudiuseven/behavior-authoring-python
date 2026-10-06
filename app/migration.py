"""Schema evolution: read/migrate graphs written under older schema versions.

Published snapshots are immutable, so migration never rewrites stored data;
it transforms a payload in memory at read time. Each step migrates exactly
one schema version, and steps chain (v1 -> v2 -> ...). A payload whose
version has no migration path raises MigrationError with a clear reason.
"""
from __future__ import annotations

import copy
from typing import Any, Callable

from app.models import SCHEMA_VERSION, BehaviorGraph


class MigrationError(Exception):
    """Raised when a stored definition cannot be migrated to the current schema."""


def _migrate_v1_to_v2(payload: dict) -> dict:
    """v1 -> v2:
    - node field "type" renamed to "kind"
    - edges gain stable ids ("e{index}") when missing
    - blackboard mapping {name: type} becomes a list of key objects
    - param references written as "@key" strings become {"key": key}
    """
    out = copy.deepcopy(payload)
    for node in out.get("nodes", []):
        if "type" in node:
            node["kind"] = node.pop("type")
        node["params"] = _convert_param_refs(node.get("params", {}))
    for i, edge in enumerate(out.get("edges", [])):
        edge.setdefault("id", f"e{i}")
    bb = out.get("blackboard", {})
    if isinstance(bb, dict):
        out["blackboard"] = [{"name": name, "type": t} for name, t in bb.items()]
    out["schema_version"] = 2
    return out


def _convert_param_refs(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("@"):
        return {"key": value[1:]}
    if isinstance(value, dict):
        return {k: _convert_param_refs(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_convert_param_refs(v) for v in value]
    return value


_MIGRATIONS: dict[int, Callable[[dict], dict]] = {
    1: _migrate_v1_to_v2,
}


def migrate_payload(payload: dict) -> BehaviorGraph:
    """Migrate a raw stored payload to the current schema and parse it.

    The input payload is never modified.
    """
    if not isinstance(payload, dict):
        raise MigrationError(f"payload must be a mapping, got {type(payload).__name__}")
    version = payload.get("schema_version")
    if version is None:
        raise MigrationError("payload has no schema_version; cannot determine migration path")
    if not isinstance(version, int) or version < 1:
        raise MigrationError(f"unsupported schema_version {version!r}")
    if version > SCHEMA_VERSION:
        raise MigrationError(
            f"payload schema_version {version} is newer than supported "
            f"{SCHEMA_VERSION}; upgrade the service to read it")

    current = copy.deepcopy(payload)
    while version < SCHEMA_VERSION:
        step = _MIGRATIONS.get(version)
        if step is None:
            raise MigrationError(
                f"no migration path from schema_version {version} to {version + 1}")
        current = step(current)
        version = current.get("schema_version", version + 1)
    return BehaviorGraph.model_validate(current)
