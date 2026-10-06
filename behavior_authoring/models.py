"""领域模型：行为图、草稿、发布版本、校验问题等类型定义。

本模块只包含数据结构定义，不包含业务逻辑。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# 当前服务端支持的行为图结构（schema）版本。
SCHEMA_VERSION = 2


class NodeKind(str, Enum):
    """行为图节点类型。"""

    ROOT = "root"
    SEQUENCE = "sequence"
    SELECTOR = "selector"
    ACTION = "action"
    CONDITION = "condition"


@dataclass(frozen=True)
class ParamRef:
    """节点参数对黑板键的引用。"""

    param: str          # 节点上的参数名
    blackboard_key: str # 引用的黑板键名


@dataclass(frozen=True)
class Node:
    """行为图节点。"""

    id: str
    kind: NodeKind
    name: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    param_refs: tuple[ParamRef, ...] = ()


@dataclass(frozen=True)
class Edge:
    """行为图连线（父 -> 子）。"""

    id: str
    source: str  # 源节点 id
    target: str  # 目标节点 id


class BlackboardType(str, Enum):
    """黑板键的类型。"""

    INT = "int"
    FLOAT = "float"
    STRING = "string"
    BOOL = "bool"


@dataclass(frozen=True)
class BlackboardKey:
    """黑板键定义。"""

    name: str
    type: BlackboardType
    default: Any = None


@dataclass(frozen=True)
class BehaviorGraph:
    """行为图定义：节点、连线、黑板键成组出现。"""

    nodes: tuple[Node, ...] = ()
    edges: tuple[Edge, ...] = ()
    blackboard: tuple[BlackboardKey, ...] = ()
    schema_version: int = SCHEMA_VERSION


@dataclass(frozen=True)
class Draft:
    """可反复编辑的草稿。revision 用于乐观并发控制。"""

    graph_id: str
    revision: int
    graph: BehaviorGraph
    updated_by: str
    updated_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class PublishedVersion:
    """不可变的发布版本。发布后内容（含编译产物哈希）不再变化。"""

    graph_id: str
    version: int
    graph: BehaviorGraph
    compiled_hash: str
    published_by: str
    published_at: float
    source_draft_revision: int
    rollback_of: Optional[int] = None  # 若该版本由回滚产生，记录回滚到的版本号


class IssueSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ValidationIssue:
    """校验问题：定位到具体元素并给出原因。"""

    severity: IssueSeverity
    code: str                 # 机器可读的稳定错误码，如 EDGE_TARGET_MISSING
    message: str              # 人类可读的原因说明
    element_kind: str         # 元素类别：node / edge / blackboard / param_ref / graph
    element_id: str           # 具体元素标识（节点 id、连线 id、键名等）


@dataclass(frozen=True)
class ValidationResult:
    """成组校验的结果。"""

    issues: tuple[ValidationIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not any(i.severity == IssueSeverity.ERROR for i in self.issues)


@dataclass(frozen=True)
class CompiledGraph:
    """编译产物：拓扑序、邻接表等运行时结构。"""

    content_hash: str
    topo_order: tuple[str, ...]
    children: dict[str, tuple[str, ...]]
    node_index: dict[str, Node]
    blackboard_index: dict[str, BlackboardKey]


@dataclass(frozen=True)
class AuditRecord:
    """权限敏感操作（发布/回滚/越权尝试）的可追溯记录。"""

    actor: str
    action: str          # publish / rollback
    graph_id: str
    version: Optional[int]
    allowed: bool
    reason: str
    at: float = field(default_factory=time.time)


# ---- 服务层异常 ----


class AuthoringError(Exception):
    """服务层错误基类。"""


class NotFoundError(AuthoringError):
    """草稿或版本不存在。"""


class ConflictError(AuthoringError):
    """乐观并发冲突：携带可解释的冲突信息。"""

    def __init__(self, message: str, expected_revision: int, actual_revision: int):
        super().__init__(message)
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision


class ValidationFailedError(AuthoringError):
    """校验失败：携带成组校验问题列表。"""

    def __init__(self, result: ValidationResult):
        super().__init__("validation failed")
        self.result = result


class PermissionDeniedError(AuthoringError):
    """越权操作。"""


class MigrationError(AuthoringError):
    """旧结构版本无法迁移。"""


class CyclicGraphError(AuthoringError):
    """图存在环，无法编译。"""
