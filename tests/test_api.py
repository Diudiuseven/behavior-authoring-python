"""HTTP 接口端到端：草稿、校验、发布、并发冲突、越权、按版本读取。"""
import pytest
from fastapi.testclient import TestClient

from behavior_authoring.api import create_app

ADMIN = {"X-User": "admin"}
PUBLISHER = {"X-User": "publisher"}
EDITOR = {"X-User": "editor"}

VALID_GRAPH = {
    "nodes": [{"id": "root", "kind": "root"},
              {"id": "act", "kind": "action"}],
    "edges": [{"id": "e1", "source": "root", "target": "act"}],
    "blackboard": [{"name": "hp", "type": "int", "default": 100}],
}

INVALID_GRAPH = {
    "nodes": [{"id": "root", "kind": "root"},
              {"id": "act", "kind": "action",
               "param_refs": [{"param": "t", "blackboard_key": "nope"}]}],
    "edges": [{"id": "e1", "source": "root", "target": "act"}],
    "blackboard": [],
}


@pytest.fixture
def client():
    return TestClient(create_app())


def _save(client, graph, revision, headers=EDITOR):
    return client.put("/graphs/g/draft",
                      json={"graph": graph, "expected_revision": revision},
                      headers=headers)


def test_full_authoring_flow(client):
    assert client.post("/graphs/g/draft", headers=EDITOR).status_code == 200
    r = _save(client, VALID_GRAPH, 0)
    assert r.status_code == 200 and r.json()["revision"] == 1

    r = client.post("/graphs/g/draft/validate")
    assert r.json()["ok"] is True

    r = client.post("/graphs/g/publish", headers=PUBLISHER)
    assert r.status_code == 200 and r.json()["version"] == 1

    r = client.get("/graphs/g/versions/1")
    assert r.status_code == 200
    assert r.json()["compiled"]["topo_order"] == ["root", "act"]


def test_validation_error_locates_element(client):
    client.post("/graphs/g/draft", headers=EDITOR)
    _save(client, INVALID_GRAPH, 0)
    r = client.post("/graphs/g/draft/validate")
    body = r.json()
    assert body["ok"] is False
    issue = body["issues"][0]
    assert issue["code"] == "PARAM_REF_UNKNOWN_KEY"
    assert issue["element_kind"] == "param_ref"
    assert issue["element_id"] == "act.t"


def test_publish_invalid_returns_422_with_issues(client):
    client.post("/graphs/g/draft", headers=EDITOR)
    _save(client, INVALID_GRAPH, 0)
    r = client.post("/graphs/g/publish", headers=PUBLISHER)
    assert r.status_code == 422
    assert r.json()["issues"][0]["code"] == "PARAM_REF_UNKNOWN_KEY"
    assert client.get("/graphs/g/versions").json() == []


def test_concurrent_save_conflict_returns_409(client):
    client.post("/graphs/g/draft", headers=EDITOR)
    assert _save(client, VALID_GRAPH, 0).status_code == 200
    r = _save(client, VALID_GRAPH, 0)  # 过期 revision
    assert r.status_code == 409
    body = r.json()
    assert body["expected_revision"] == 0
    assert body["actual_revision"] == 1
    assert "冲突" in body["error"]


def test_permission_denied_returns_403_and_audit(client):
    client.post("/graphs/g/draft", headers=EDITOR)
    _save(client, VALID_GRAPH, 0)
    r = client.post("/graphs/g/publish", headers=EDITOR)  # editor 无权发布
    assert r.status_code == 403
    r = client.post("/graphs/g/publish", headers=PUBLISHER)
    assert r.status_code == 200
    r = client.post("/graphs/g/rollback/1", headers=PUBLISHER)  # 无权回滚
    assert r.status_code == 403
    r = client.post("/graphs/g/rollback/1", headers=ADMIN)
    assert r.status_code == 200 and r.json()["rollback_of"] == 1

    audit = client.get("/audit").json()
    denied = [a for a in audit if not a["allowed"]]
    assert len(denied) == 2
    assert {a["action"] for a in denied} == {"publish", "rollback"}


def test_missing_user_header_returns_401(client):
    assert client.post("/graphs/g/draft").status_code == 401
