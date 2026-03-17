from pathlib import Path
from types import SimpleNamespace

from starlette.testclient import TestClient

from lemonclaw.gateway.server import create_app
from lemonclaw.session.manager import SessionManager


def _make_client(tmp_path: Path) -> TestClient:
    app = create_app(
        auth_token=None,
        agent_loop=SimpleNamespace(workspace=tmp_path),
        session_manager=SessionManager(tmp_path),
        webui_enabled=True,
    )
    return TestClient(app)


def test_memory_create_entity_roundtrip(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    create_resp = client.post(
        "/api/memory/entities",
        json={
            "name": "research-notes",
            "type": "research",
            "keywords": ["retrieval", "kb"],
            "body": "# Research Notes\n\nKnowledge ingestion needs a product surface.",
        },
    )
    assert create_resp.status_code == 200
    entity = create_resp.json()["entity"]
    assert entity["name"] == "research-notes"
    assert entity["type"] == "research"
    assert "retrieval" in entity["keywords"]

    memory_resp = client.get("/api/memory")
    assert memory_resp.status_code == 200
    data = memory_resp.json()
    assert any(item["name"] == "research-notes" for item in data["entities"])


def test_memory_create_entity_rejects_invalid_name(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    create_resp = client.post(
        "/api/memory/entities",
        json={"name": "../bad-card", "type": "note", "body": "nope"},
    )
    assert create_resp.status_code == 400
    assert create_resp.json()["error"] == "invalid entity name"
