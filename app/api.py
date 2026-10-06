"""FastAPI HTTP layer exposing the authoring service."""
from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from app.auth import PermissionDenied
from app.models import BehaviorGraph, Role
from app.service import BehaviorService, PublishError
from app.storage import ConflictError, NotFoundError


class SaveDraftRequest(BaseModel):
    graph: BehaviorGraph
    base_revision: int


class RollbackRequest(BaseModel):
    version: int


def create_app(service: BehaviorService | None = None) -> FastAPI:
    svc = service or BehaviorService()
    app = FastAPI(title="behavior-authoring")
    app.state.service = svc

    @app.exception_handler(ConflictError)
    async def _conflict(_, exc: ConflictError):
        raise HTTPException(status_code=409, detail={
            "error": "revision_conflict", "graph_id": exc.graph_id,
            "expected_revision": exc.expected, "current_revision": exc.actual,
            "last_modified_by": exc.holder, "message": str(exc)})

    @app.exception_handler(PermissionDenied)
    async def _denied(_, exc: PermissionDenied):
        raise HTTPException(status_code=403, detail={
            "error": "permission_denied", "actor": exc.actor, "action": exc.action})

    @app.exception_handler(NotFoundError)
    async def _not_found(_, exc: NotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))

    @app.exception_handler(PublishError)
    async def _publish_error(_, exc: PublishError):
        raise HTTPException(status_code=422, detail={
            "error": "validation_failed", "graph_id": exc.graph_id,
            "issues": [i.model_dump() for i in exc.report.issues]})

    @app.put("/graphs/{graph_id}/draft", status_code=200)
    def save_draft(graph_id: str, req: SaveDraftRequest,
                   x_actor: str = Header(default="anonymous")):
        draft = svc.save_draft(graph_id, req.graph, req.base_revision, x_actor)
        return {"graph_id": draft.graph_id, "revision": draft.revision}

    @app.get("/graphs/{graph_id}/draft")
    def get_draft(graph_id: str):
        return svc.get_draft(graph_id)

    @app.post("/graphs/{graph_id}/draft/validate")
    def validate_draft(graph_id: str):
        return svc.validate_draft(graph_id)

    @app.post("/graphs/{graph_id}/publish", status_code=201)
    def publish(graph_id: str, x_actor: str = Header(default="anonymous")):
        v = svc.publish(graph_id, x_actor)
        return v

    @app.post("/graphs/{graph_id}/rollback")
    def rollback(graph_id: str, req: RollbackRequest,
                 x_actor: str = Header(default="anonymous")):
        return svc.rollback(graph_id, req.version, x_actor)

    @app.get("/graphs/{graph_id}/versions")
    def list_versions(graph_id: str):
        return svc.store.list_versions(graph_id)

    @app.get("/graphs/{graph_id}/versions/{version}")
    def read_version(graph_id: str, version: int):
        return svc.read_version(graph_id, version)

    @app.get("/graphs/{graph_id}/latest")
    def read_latest(graph_id: str):
        return svc.read_latest(graph_id)

    @app.get("/graphs/{graph_id}/versions/{version}/plan")
    def compiled_plan(graph_id: str, version: int):
        return svc.compile_version(graph_id, version)

    @app.get("/audit")
    def audit():
        return svc.audit_log()

    return app


# default app with a demo role assignment; tests build their own service
def default_app() -> FastAPI:
    service = BehaviorService()
    service.auth.set_role("editor", Role.EDITOR)
    service.auth.set_role("publisher", Role.PUBLISHER)
    service.auth.set_role("admin", Role.ADMIN)
    return create_app(service)


app = default_app()
