import pytest

from app.auth import Authorizer
from app.compiler import CompileCache
from app.models import BehaviorGraph, Edge, Node, Role
from app.service import BehaviorService
from app.storage import GraphStore


@pytest.fixture
def service() -> BehaviorService:
    auth = Authorizer({
        "alice": Role.EDITOR,
        "bob": Role.EDITOR,
        "pub": Role.PUBLISHER,
        "root": Role.ADMIN,
    })
    return BehaviorService(store=GraphStore(), auth=auth, cache=CompileCache())


@pytest.fixture
def simple_graph() -> BehaviorGraph:
    return BehaviorGraph(
        name="patrol",
        nodes=[Node(id="root", kind="sequence"),
               Node(id="move", kind="action", params={"speed": 1.5})],
        edges=[Edge(id="e1", source="root", target="move")],
        entry_node="root",
    )
