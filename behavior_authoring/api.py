"""FastAPI HTTP 接口层：把领域对象与 JSON 互转，暴露 REST 接口。"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .auth import Authorizer, Role
from .compiler import Compiler
from .models import (
    AuthoringError,
    BehaviorGraph,
    BlackboardKey,
    BlackboardType,
    ConflictError,
    Edge,
    MigrationError,
    Node,
    NodeKind,
    NotFoundError,
    ParamRef,
    PermissionDeniedError,
    ValidationFailedError,
)
from .service import AuthoringService
from .storage import InMemoryStore


# ---- JSON <-> 领域对象 ----


def graph_from_dict(d: dict[str, Any]) -> BehaviorGraph:
    nodes = tuple(
        Node(
            id=n["id"],
            kind=NodeKind(n["kind"]),
            name=n.get("name", ""),
            params=n.get("params", {}),
            param_refs=tuple(
                ParamRef(param=r["param"], blackboard_key=r["blackboard_key"])
                for r in n.get("param_refs", [])
            ),
        )
        for n in d.get("nodes", [])
    )
    edges = tuple(
        Edge(id=e["id"], source=e["source"], target=e["target"])
        for e in d.get("edges", [])
    )
    blackboard = tuple(
        BlackboardKey(name=k["name"], type=BlackboardType(k["type"]),
                      default=k.get("default"))
        for k in d.get("blackboard", [])
    )
    return BehaviorGraph(nodes=nodes, edges=edges, blackboard=blackboard,
                         schema_version=d.get("schema_version", 2))


def _node_to_dict(n: Node) -> dict[str, Any]:
    return {
        "id": n.id, "kind": n.kind.value, "name": n.name,
        "params": n.params,
        "param_refs": [asdict(r) for r in n.param_refs],
    }


def graph_to_dict(g: BehaviorGraph) -> dict[str, Any]:
    return {
        "schema_version": g.schema_version,
        "nodes": [_node_to_dict(n) for n in g.nodes],
        "edges": [asdict(e) for e in g.edges],
        "blackboard": [
            {"name": k.name, "type": k.type.value, "default": k.default}
            for k in g.blackboard
        ],
    }


def draft_to_dict(d) -> dict[str, Any]:
    return {"graph_id": d.graph_id, "revision": d.revision,
            "updated_by": d.updated_by, "graph": graph_to_dict(d.graph)}


def version_to_dict(v) -> dict[str, Any]:
    return {
        "graph_id": v.graph_id, "version": v.version,
        "compiled_hash": v.compiled_hash, "published_by": v.published_by,
        "published_at": v.published_at,
        "source_draft_revision": v.source_draft_revision,
        "rollback_of": v.rollback_of,
        "graph": graph_to_dict(v.graph),
    }


# ---- 请求体 ----


class SaveDraftBody(BaseModel):
    graph: dict[str, Any]
    expected_revision: int


# ---- 应用工厂 ----


def create_app(role_by_user: dict[str, str] | None = None) -> FastAPI:
    authorizer = Authorizer(role_by_user or {
        "editor": Role.EDITOR,
        "publisher": Role.PUBLISHER,
        "admin": Role.ADMIN,
    })
    service = AuthoringService(InMemoryStore(), Compiler(), authorizer)

    app = FastAPI(title="Behavior Authoring Service")

    @app.exception_handler(NotFoundError)
    async def _not_found(_, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.exception_handler(ConflictError)
    async def _conflict(_, exc: ConflictError):
        return JSONResponse(status_code=409, content={
            "error": str(exc),
            "expected_revision": exc.expected_revision,
            "actual_revision": exc.actual_revision,
        })

    @app.exception_handler(ValidationFailedError)
    async def _invalid(_, exc: ValidationFailedError):
        return JSONResponse(status_code=422, content={
            "error": "validation failed",
            "issues": [asdict(i) for i in exc.result.issues],
        })

    @app.exception_handler(PermissionDeniedError)
    async def _forbidden(_, exc: PermissionDeniedError):
        return JSONResponse(status_code=403, content={"error": str(exc)})

    @app.exception_handler(MigrationError)
    async def _migration(_, exc: MigrationError):
        return JSONResponse(status_code=422, content={"error": str(exc)})

    @app.exception_handler(AuthoringError)
    async def _authoring(_, exc: AuthoringError):
        return JSONResponse(status_code=400, content={"error": str(exc)})

    def actor(x_user: str | None) -> str:
        if not x_user:
            raise HTTPException(status_code=401, detail="missing X-User header")
        return x_user

    @app.post("/graphs/{graph_id}/draft")
    def create_draft(graph_id: str, x_user: str | None = Header(None)):
        return draft_to_dict(service.create_draft(graph_id, actor(x_user)))

    @app.get("/graphs/{graph_id}/draft")
    def get_draft(graph_id: str):
        return draft_to_dict(service.get_draft(graph_id))

    @app.put("/graphs/{graph_id}/draft")
    def save_draft(graph_id: str, body: SaveDraftBody,
                     x_user: str | None = Header(None)):
        graph = graph_from_dict(body.graph)
        return draft_to_dict(service.save_draft(
            graph_id, graph, body.expected_revision, actor(x_user)))

    @app.post("/graphs/{graph_id}/draft/validate")
    def validate_draft(graph_id: str):
        result = service.validate_draft(graph_id)
        return {"ok": result.ok, "issues": [asdict(i) for i in result.issues]}

    @app.post("/graphs/{graph_id}/publish")
    def publish(graph_id: str, x_user: str | None = Header(None)):
        return version_to_dict(service.publish(graph_id, actor(x_user)))

    @app.get("/graphs/{graph_id}/versions")
    def list_versions(graph_id: str):
        return [version_to_dict(v) for v in service.list_versions(graph_id)]

    @app.get("/graphs/{graph_id}/versions/{version}")
    def read_version(graph_id: str, version: int):
        pv, compiled = service.read_version(graph_id, version)
        return {**version_to_dict(pv),
                "compiled": {"content_hash": compiled.content_hash,
                             "topo_order": list(compiled.topo_order)}}

    @app.get("/graphs/{graph_id}/latest")
    def read_latest(graph_id: str):
        pv, compiled = service.read_latest(graph_id)
        return {**version_to_dict(pv),
                "compiled": {"content_hash": compiled.content_hash,
                             "topo_order": list(compiled.topo_order)}}

    @app.post("/graphs/{graph_id}/rollback/{version}")
    def rollback(graph_id: str, version: int,
                 x_user: str | None = Header(None)):
        return version_to_dict(service.rollback(graph_id, version, actor(x_user)))

    @app.get("/audit")
    def audit():
        return [asdict(r) for r in authorizer.audit_log()]

    return app
