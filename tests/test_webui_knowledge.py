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


def test_knowledge_document_roundtrip(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    create_resp = client.post(
        "/api/knowledge/documents",
        json={
            "title": "API Error Playbook",
            "source": "https://docs.example.com/errors",
            "source_type": "url",
            "note": "Use this later for ingestion and retrieval checks.",
        },
    )
    assert create_resp.status_code == 200
    document = create_resp.json()["document"]
    assert document["source_type"] == "url"
    assert document["title"] == "API Error Playbook"

    list_resp = client.get("/api/knowledge")
    assert list_resp.status_code == 200
    payload = list_resp.json()
    assert payload["summary"]["total"] == 1
    assert payload["documents"][0]["doc_id"] == document["doc_id"]

    delete_resp = client.delete(f"/api/knowledge/documents/{document['doc_id']}")
    assert delete_resp.status_code == 200

    list_resp = client.get("/api/knowledge")
    assert list_resp.status_code == 200
    assert list_resp.json()["summary"]["total"] == 0


def test_knowledge_document_rejects_invalid_type(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    create_resp = client.post(
        "/api/knowledge/documents",
        json={"title": "bad", "source": "x", "source_type": "rss"},
    )
    assert create_resp.status_code == 400
    assert create_resp.json()["error"] == "invalid source_type"


def test_knowledge_manual_ingest_and_search(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    create_resp = client.post(
        "/api/knowledge/documents",
        json={
            "title": "Recovery Notes",
            "source": "manual://recovery-notes",
            "source_type": "manual",
            "content": "Retry outbox events before escalating to manual recovery.",
        },
    )
    assert create_resp.status_code == 200
    doc_id = create_resp.json()["document"]["doc_id"]

    ingest_resp = client.post(f"/api/knowledge/documents/{doc_id}/ingest")
    assert ingest_resp.status_code == 200
    ingested = ingest_resp.json()["document"]
    assert ingested["status"] == "ingested"
    assert ingested["chunk_count"] >= 1

    search_resp = client.get("/api/knowledge/search?q=retry outbox")
    assert search_resp.status_code == 200
    results = search_resp.json()["results"]
    assert len(results) >= 1
    assert results[0]["doc_id"] == doc_id
    assert results[0]["result_type"] in {"chunk", "fact"}

    detail_resp = client.get(f"/api/knowledge/documents/{doc_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["document"]["doc_id"] == doc_id
    assert len(detail["chunks"]) >= 1
    assert len(detail["facts"]) >= 1


def test_knowledge_document_patch_resets_ingest_state(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    create_resp = client.post(
        "/api/knowledge/documents",
        json={
            "title": "Initial Notes",
            "source": "manual://initial",
            "source_type": "manual",
            "content": "Original content for retrieval.",
        },
    )
    assert create_resp.status_code == 200
    doc_id = create_resp.json()["document"]["doc_id"]

    ingest_resp = client.post(f"/api/knowledge/documents/{doc_id}/ingest")
    assert ingest_resp.status_code == 200
    assert ingest_resp.json()["document"]["status"] == "ingested"

    patch_resp = client.patch(
        f"/api/knowledge/documents/{doc_id}",
        json={
            "title": "Updated Notes",
            "content": "Updated content with a different retrieval keyword.",
        },
    )
    assert patch_resp.status_code == 200
    patched = patch_resp.json()["document"]
    assert patched["title"] == "Updated Notes"
    assert patched["status"] == "registered"
    assert patched["chunk_count"] == 0

    detail_resp = client.get(f"/api/knowledge/documents/{doc_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["chunks"] == []
