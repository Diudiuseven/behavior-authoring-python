import pytest

from behavior_authoring.auth import Authorizer, Role
from behavior_authoring.compiler import Compiler
from behavior_authoring.models import (
    BehaviorGraph,
    BlackboardKey,
    BlackboardType,
    Edge,
    Node,
    NodeKind,
    ParamRef,
)
from behavior_authoring.service import AuthoringService
from behavior_authoring.storage import InMemoryStore


@pytest.fixture
def authorizer():
    return Authorizer({
        "editor": Role.EDITOR,
        "publisher": Role.PUBLISHER,
        "admin": Role.ADMIN,
    })


@pytest.fixture
def compiler():
    return Compiler()


@pytest.fixture
def service(authorizer, compiler):
    return AuthoringService(InMemoryStore(), compiler, authorizer)


def make_graph(suffix: str = "", extra_nodes=(), extra_edges=(),
               blackboard=None, param_refs=()) -> BehaviorGraph:
    """构造一个合法的小图：root -> sequence -> action。"""
    nodes = [
        Node("root", NodeKind.ROOT),
        Node("seq", NodeKind.SEQUENCE),
        Node(f"act{suffix}", NodeKind.ACTION, param_refs=tuple(param_refs)),
        *extra_nodes,
    ]
    edges = [
        Edge("e1", "root", "seq"),
        Edge("e2", "seq", f"act{suffix}"),
        *extra_edges,
    ]
    return BehaviorGraph(
        nodes=tuple(nodes),
        edges=tuple(edges),
        blackboard=tuple(blackboard or []),
    )


@pytest.fixture
def valid_graph():
    return make_graph()
