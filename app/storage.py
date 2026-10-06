"""Storage: drafts with optimistic concurrency, atomic immutable version store.

In-memory reference implementation. All mutating operations take a single
lock so a publish is atomic: either the new immutable version is fully
committed and visible, or nothing changed at all.
"""
from __future__ import annotations

import threading

from app.models import BehaviorGraph, Draft, PublishedVersion


class ConflictError(Exception):
    """Raised when a draft save loses the optimistic-concurrency race."""

    def __init__(self, graph_id: str, expected: int, actual: int, holder: str):
        self.graph_id = graph_id
        self.expected = expected
        self.actual = actual
        self.holder = holder
        super().__init__(
            f"draft {graph_id!r} was modified by {holder!r}: "
            f"expected revision {expected}, current is {actual}; "
            "reload the draft and re-apply your changes"
        )


class NotFoundError(Exception):
    pass


class GraphStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._drafts: dict[str, Draft] = {}
        # graph_id -> {version_number: PublishedVersion}; versions are never
        # mutated or deleted after insert, only flagged (rolled_back).
        self._versions: dict[str, dict[int, PublishedVersion]] = {}

    # ---- drafts ----

    def save_draft(self, graph_id: str, graph: BehaviorGraph,
                   base_revision: int, actor: str) -> Draft:
        """Compare-and-swap save: succeeds only if base_revision is current."""
        with self._lock:
            current = self._drafts.get(graph_id)
            actual = current.revision if current else 0
            if base_revision != actual:
                raise ConflictError(graph_id, base_revision, actual,
                                    current.updated_by if current else "<none>")
            draft = Draft(graph_id=graph_id, revision=actual + 1,
                          graph=graph, updated_by=actor)
            self._drafts[graph_id] = draft
            return draft

    def get_draft(self, graph_id: str) -> Draft:
        with self._lock:
            try:
                return self._drafts[graph_id]
            except KeyError:
                raise NotFoundError(f"no draft for graph {graph_id!r}") from None

    # ---- published versions ----

    def publish(self, graph_id: str, snapshot: str, content_hash: str,
                schema_version: int, actor: str, timestamp: float) -> PublishedVersion:
        """Atomically commit a new immutable version.

        The version number is allocated and the record inserted under one
        lock; readers either see the previous latest version or the fully
        committed new one, never a partial state.
        """
        with self._lock:
            versions = self._versions.setdefault(graph_id, {})
            number = (max(versions) + 1) if versions else 1
            record = PublishedVersion(
                graph_id=graph_id, version=number,
                schema_version=schema_version, snapshot=snapshot,
                content_hash=content_hash, published_by=actor,
                published_at=timestamp)
            versions[number] = record
            return record

    def get_version(self, graph_id: str, version: int) -> PublishedVersion:
        with self._lock:
            try:
                return self._versions[graph_id][version]
            except KeyError:
                raise NotFoundError(
                    f"no version {version} for graph {graph_id!r}") from None

    def latest_version(self, graph_id: str) -> PublishedVersion | None:
        with self._lock:
            versions = self._versions.get(graph_id)
            if not versions:
                return None
            return versions[max(versions)]

    def list_versions(self, graph_id: str) -> list[PublishedVersion]:
        with self._lock:
            return [self._versions.get(graph_id, {})[n]
                    for n in sorted(self._versions.get(graph_id, {}))]

    def mark_rolled_back(self, graph_id: str, version: int) -> PublishedVersion:
        """Flag a version as rolled back. The snapshot itself is untouched."""
        with self._lock:
            record = self.get_version(graph_id, version)
            record.rolled_back = True
            return record
