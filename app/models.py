"""Core domain models for behavior graph authoring and versioned publishing."""
from __future__ import annotations

import enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# Bump when the on-disk / on-wire structure of a BehaviorGraph changes.
SCHEMA_VERSION = 2


class NodeKind(str, enum.Enum):
    ACTION = "action"
    CONDITION = "condition"
    SEQUENCE = "sequence"
    SELECTOR = "selector"
    DECORATOR = "decorator"


class ParamRef(BaseModel):
    """A parameter value that references a blackboard key."""

    key: str


class Node(BaseModel):
    id: str
    kind: NodeKind
    name: str = ""
    # static params, or a ParamRef-as-dict {"key": "..."} referencing blackboard
    params: dict[str, Any] = Field(default_factory=dict)


class Edge(BaseModel):
    id: str
    source: str  # node id
    target: str  # node id
    # optional condition expression referencing blackboard keys
    guard: str | None = None


class BlackboardKey(BaseModel):
    name: str
    type: Literal["int", "float", "str", "bool"] = "str"
    required: bool = False
    default: Any | None = None


class BehaviorGraph(BaseModel):
    """A behavior graph definition (draft payload or published snapshot)."""

    schema_version: int = SCHEMA_VERSION
    name: str = "untitled"
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    blackboard: list[BlackboardKey] = Field(default_factory=list)
    entry_node: str | None = None


class IssueSeverity(str, enum.Enum):
    ERROR = "error"
    WARNING = "warning"


class ValidationIssue(BaseModel):
    """A single validation finding, located at a specific element."""

    severity: IssueSeverity
    code: str  # machine-readable, e.g. "EDGE_TARGET_MISSING"
    message: str  # human-readable reason
    element_kind: Literal["node", "edge", "blackboard", "graph", "param"]
    element_id: str  # node id / edge id / blackboard key name / "graph"
    field: str | None = None


class ValidationReport(BaseModel):
    ok: bool
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == IssueSeverity.ERROR]


class Draft(BaseModel):
    """A mutable working copy of a graph, guarded by optimistic concurrency."""

    graph_id: str
    revision: int  # incremented on every successful save; CAS token
    graph: BehaviorGraph
    updated_by: str = ""


class PublishedVersion(BaseModel):
    """An immutable published snapshot."""

    graph_id: str
    version: int
    schema_version: int
    # canonical JSON of the graph at publish time; the source of truth
    snapshot: str
    content_hash: str
    published_by: str
    published_at: float
    rolled_back: bool = False


class Role(str, enum.Enum):
    EDITOR = "editor"      # may save drafts
    PUBLISHER = "publisher"  # may publish
    ADMIN = "admin"        # may publish and rollback


class AuditRecord(BaseModel):
    actor: str
    action: str  # e.g. "publish", "rollback", "save_draft"
    graph_id: str
    allowed: bool
    detail: str = ""
    timestamp: float = 0.0
