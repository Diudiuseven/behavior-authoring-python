"""存储层：草稿与发布版本的持久化（内存实现）。

关键语义：
- 乐观并发：草稿保存必须携带期望的 revision，不匹配则拒绝并报冲突；
- 原子发布：版本号分配、版本写入、latest 指针推进在同一把锁内完成，
  消费者在发布完成前只能读到上一个完整版本；
- 发布版本不可变：写入后不提供任何修改接口。
"""
from __future__ import annotations

import threading
import time

from .models import (
    BehaviorGraph,
    ConflictError,
    Draft,
    NotFoundError,
    PublishedVersion,
)


class InMemoryStore:
    """线程安全的内存存储。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._drafts: dict[str, Draft] = {}
        # graph_id -> {version -> PublishedVersion}，只增不改。
        self._versions: dict[str, dict[int, PublishedVersion]] = {}
        # graph_id -> 当前对消费者可见的最新完整版本号。
        self._latest: dict[str, int] = {}

    # ---- 草稿 ----

    def create_draft(self, graph_id: str, author: str) -> Draft:
        with self._lock:
            if graph_id in self._drafts:
                raise ConflictError(
                    f"草稿 {graph_id} 已存在",
                    expected_revision=-1,
                    actual_revision=self._drafts[graph_id].revision,
                )
            draft = Draft(graph_id=graph_id, revision=0,
                          graph=BehaviorGraph(), updated_by=author)
            self._drafts[graph_id] = draft
            return draft

    def get_draft(self, graph_id: str) -> Draft:
        with self._lock:
            try:
                return self._drafts[graph_id]
            except KeyError:
                raise NotFoundError(f"草稿不存在: {graph_id}") from None

    def try_get_draft(self, graph_id: str) -> Draft | None:
        """草稿不存在时返回 None 而不是抛异常。"""
        with self._lock:
            return self._drafts.get(graph_id)

    def save_draft(self, graph_id: str, graph: BehaviorGraph,
                   expected_revision: int, author: str) -> Draft:
        """按乐观并发保存草稿；revision 不匹配时抛 ConflictError。"""
        with self._lock:
            current = self._drafts.get(graph_id)
            if current is None:
                raise NotFoundError(f"草稿不存在: {graph_id}")
            if current.revision != expected_revision:
                raise ConflictError(
                    f"保存冲突：你基于 revision {expected_revision} 编辑，"
                    f"但草稿已被 {current.updated_by} 推进到 revision "
                    f"{current.revision}。请拉取最新草稿后合并修改再保存。",
                    expected_revision=expected_revision,
                    actual_revision=current.revision,
                )
            draft = Draft(graph_id=graph_id, revision=current.revision + 1,
                          graph=graph, updated_by=author)
            self._drafts[graph_id] = draft
            return draft

    # ---- 发布版本 ----

    def publish(self, graph_id: str, graph: BehaviorGraph, published_by: str,
                source_draft_revision: int, compiled_hash: str,
                rollback_of: int | None = None) -> PublishedVersion:
        """原子地写入一个不可变版本并推进 latest 指针。

        版本号分配、写入与 latest 推进都在同一把锁内完成；若写入过程中
        发生异常，latest 不会被推进，消费者仍只能看到上一个完整版本。
        """
        with self._lock:
            versions = self._versions.setdefault(graph_id, {})
            next_version = (max(versions) + 1) if versions else 1
            pv = PublishedVersion(
                graph_id=graph_id,
                version=next_version,
                graph=graph,
                compiled_hash=compiled_hash,
                published_by=published_by,
                published_at=time.time(),
                source_draft_revision=source_draft_revision,
                rollback_of=rollback_of,
            )
            versions[next_version] = pv
            # 只有版本完整写入后才对消费者可见。
            self._latest[graph_id] = next_version
            return pv

    def get_version(self, graph_id: str, version: int) -> PublishedVersion:
        with self._lock:
            try:
                return self._versions[graph_id][version]
            except KeyError:
                raise NotFoundError(
                    f"版本不存在: {graph_id}@v{version}") from None

    def get_latest(self, graph_id: str) -> PublishedVersion:
        with self._lock:
            latest = self._latest.get(graph_id)
            if latest is None:
                raise NotFoundError(f"图 {graph_id} 尚无已发布版本")
            return self._versions[graph_id][latest]

    def list_versions(self, graph_id: str) -> list[PublishedVersion]:
        with self._lock:
            versions = self._versions.get(graph_id, {})
            return [versions[v] for v in sorted(versions)]
