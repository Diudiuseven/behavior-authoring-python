"""Schema evolution: old published definitions stay readable via migration."""
import json

import pytest

from app.migration import MigrationError, migrate_payload
from app.models import SCHEMA_VERSION

V1_PAYLOAD = {
    "schema_version": 1,
    "name": "legacy",
    "nodes": [{"id": "n1", "type": "action", "params": {"target": "@enemy"}}],
    "edges": [{"source": "n1", "target": "n1"}][:0],  # no edges
    "blackboard": {"enemy": "str"},
}


def test_v1_payload_migrates_to_current_schema():
    g = migrate_payload(V1_PAYLOAD)
    assert g.schema_version == SCHEMA_VERSION
    assert g.nodes[0].kind.value == "action"          # "type" renamed to "kind"
    assert g.nodes[0].params["target"] == {"key": "enemy"}  # "@k" -> {"key": k}
    assert g.blackboard[0].name == "enemy"            # mapping -> key objects


def test_migration_does_not_mutate_input():
    payload = json.loads(json.dumps(V1_PAYLOAD))
    migrate_payload(payload)
    assert payload == V1_PAYLOAD


def test_unmigratable_payloads_raise_clear_errors():
    with pytest.raises(MigrationError, match="no schema_version"):
        migrate_payload({"nodes": []})
    with pytest.raises(MigrationError, match="newer than supported"):
        migrate_payload({"schema_version": SCHEMA_VERSION + 1})
    with pytest.raises(MigrationError, match="unsupported schema_version"):
        migrate_payload({"schema_version": 0})


def test_published_v1_snapshot_stays_immutable_but_readable(service):
    """Simulate a version published under schema v1, read under current code."""
    snapshot = json.dumps(V1_PAYLOAD, sort_keys=True)
    service.store.publish("legacy", snapshot, "hash-v1",
                          schema_version=1, actor="pub", timestamp=1.0)
    g = service.read_version("legacy", 1)
    assert g.schema_version == SCHEMA_VERSION
    assert g.nodes[0].kind.value == "action"
    # stored snapshot untouched by the read-time migration
    assert json.loads(service.store.get_version("legacy", 1).snapshot) == \
        json.loads(snapshot)
