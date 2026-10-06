"""Application service orchestrating validation, storage, auth, migration, cache."""
from __future__ import annotations

import json
import time

from app.auth import Authorizer
from app.compiler import CompileCache, canonical_json, content_hash
from app.migration import migrate_payload
from app.models import (
    SCHEMA_VERSION,
    AuditRecord,
    BehaviorGraph,
    Draft,
    PublishedVersion,
    ValidationReport,
)
from app.storage import GraphStore
from app.validation import validate_graph


class PublishError(Exception):
    """Publishing aborted; the store is untouched, no partial version exists."""

    def __init__(self, graph_id: str, report: ValidationReport):
        self.graph_id = graph_id
        self.report = report
        super().__init__(
            f"cannot publish {graph_id!r}: {len(report.errors)} validation error(s)")


class BehaviorService:
    def __init__(self, store: GraphStore | None = None,
                 auth: Authorizer | None = None,
                 cache: CompileCache | None = None):
        self.store = store or GraphStore()
        self.auth = auth or Authorizer()
        self.cache = cache or CompileCache()

    # ---- drafts ----

    def save_draft(self, graph_id: str, graph: BehaviorGraph,
                   base_revision: int, actor: str) -> Draft:
        """Save a draft with optimistic concurrency (CAS on base_revision)."""
        self.auth.check(actor, "save_draft", graph_id)
        return self.store.save_draft(graph_id, graph, base_revision, actor)

    def get_draft(self, graph_id: str) -> Draft:
        return self.store.get_draft(graph_id)

    def validate_draft(self, graph_id: str) -> ValidationReport:
        return validate_graph(self.store.get_draft(graph_id).graph)

    # ---- publishing ----

    def publish(self, graph_id: str, actor: str) -> PublishedVersion:
        """Promote the current draft to an immutable version, atomically.

        Order: permission check -> validate -> compile -> single atomic
        store commit. Any failure before the commit leaves no trace of a
        new version; consumers keep seeing the previous complete version.
        """
        self.auth.check(actor, "publish", graph_id)
        draft = self.store.get_draft(graph_id)
        report = validate_graph(draft.graph)
        if not report.ok:
            raise PublishError(graph_id, report)
        plan = self.cache.compile(draft.graph)  # cached; result reproducible
        snapshot = canonical_json(draft.graph)
        return self.store.publish(graph_id, snapshot, plan["content_hash"],
                                  SCHEMA_VERSION, actor, time.time())

    def rollback(self, graph_id: str, version: int, actor: str) -> PublishedVersion:
        """Flag a published version as rolled back (admin only, audited)."""
        self.auth.check(actor, "rollback", graph_id)
        return self.store.mark_rolled_back(graph_id, version)

    # ---- runtime reads ----

    def read_version(self, graph_id: str, version: int) -> BehaviorGraph:
        """Read an exact published version; migrates old schemas in memory.

        The stored snapshot is never modified, so repeated reads are
        byte-identical and reproducible.
        """
        record = self.store.get_version(graph_id, version)
        return migrate_payload(json.loads(record.snapshot))

    def read_latest(self, graph_id: str) -> BehaviorGraph:
        """Read the newest non-rolled-back version (what runtime consumes)."""
        for record in reversed(self.store.list_versions(graph_id)):
            if not record.rolled_back:
                return migrate_payload(json.loads(record.snapshot))
        from app.storage import NotFoundError
        raise NotFoundError(f"no published version for graph {graph_id!r}")

    def compile_version(self, graph_id: str, version: int) -> dict:
        """Compiled runtime plan for a version, served from the cache."""
        return self.cache.compile(self.read_version(graph_id, version))

    def audit_log(self) -> list[AuditRecord]:
        return self.auth.audit_log()
