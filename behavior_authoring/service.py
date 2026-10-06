"""应用服务层：编排校验、存储、编译、迁移与权限。"""
from __future__ import annotations

from .auth import Authorizer
from .compiler import Compiler, content_hash
from .migration import migrate_graph
from .models import (
    BehaviorGraph,
    CompiledGraph,
    Draft,
    PublishedVersion,
    ValidationFailedError,
    ValidationResult,
)
from .storage import InMemoryStore
from .validation import validate_graph


class AuthoringService:
    """对外门面：草稿编辑、校验、发布、按版本读取、回滚。"""

    def __init__(self, store: InMemoryStore, compiler: Compiler,
                 authorizer: Authorizer) -> None:
        self._store = store
        self._compiler = compiler
        self._auth = authorizer

    # ---- 草稿 ----

    def create_draft(self, graph_id: str, author: str) -> Draft:
        self._auth.check(author, "edit", graph_id)
        return self._store.create_draft(graph_id, author)

    def save_draft(self, graph_id: str, graph: BehaviorGraph,
                   expected_revision: int, author: str) -> Draft:
        self._auth.check(author, "edit", graph_id)
        # 草稿允许保存非法中间状态（设计者可反复修改），校验在发布时强制。
        return self._store.save_draft(graph_id, graph, expected_revision, author)

    def get_draft(self, graph_id: str) -> Draft:
        return self._store.get_draft(graph_id)

    def validate_draft(self, graph_id: str) -> ValidationResult:
        draft = self._store.get_draft(graph_id)
        return validate_graph(migrate_graph(draft.graph))

    # ---- 发布 ----

    def publish(self, graph_id: str, actor: str) -> PublishedVersion:
        """把当前草稿发布为不可变版本。

        原子性：先完成校验与编译（任何失败都不会触碰存储），
        再由存储层在单把锁内完成版本写入与 latest 推进。
        """
        self._auth.check(actor, "publish", graph_id)
        draft = self._store.get_draft(graph_id)
        graph = migrate_graph(draft.graph)
        result = validate_graph(graph)
        if not result.ok:
            raise ValidationFailedError(result)
        compiled = self._compiler.compile(graph)
        return self._store.publish(
            graph_id=graph_id,
            graph=graph,
            published_by=actor,
            source_draft_revision=draft.revision,
            compiled_hash=compiled.content_hash,
        )

    # ---- 运行时读取 ----

    def read_version(self, graph_id: str,
                     version: int) -> tuple[PublishedVersion, CompiledGraph]:
        """按指定版本读取，结果与发布时完全一致且可复现。

        旧 schema 版本在读取副本上迁移，已发布内容本身不被修改。
        """
        pv = self._store.get_version(graph_id, version)
        graph = migrate_graph(pv.graph)
        compiled = self._compiler.compile(graph)
        return pv, compiled

    def read_latest(self, graph_id: str) -> tuple[PublishedVersion, CompiledGraph]:
        pv = self._store.get_latest(graph_id)
        return self.read_version(pv.graph_id, pv.version)

    def list_versions(self, graph_id: str) -> list[PublishedVersion]:
        return self._store.list_versions(graph_id)

    # ---- 回滚 ----

    def rollback(self, graph_id: str, to_version: int,
                 actor: str) -> PublishedVersion:
        """回滚：以历史版本内容发布一个新版本，历史版本保持不变。"""
        self._auth.check(actor, "rollback", graph_id, to_version)
        pv = self._store.get_version(graph_id, to_version)
        graph = migrate_graph(pv.graph)
        result = validate_graph(graph)
        if not result.ok:
            raise ValidationFailedError(result)
        compiled = self._compiler.compile(graph)
        draft = self._store.try_get_draft(graph_id)
        return self._store.publish(
            graph_id=graph_id,
            graph=graph,
            published_by=actor,
            source_draft_revision=draft.revision if draft else -1,
            compiled_hash=compiled.content_hash,
            rollback_of=to_version,
        )
