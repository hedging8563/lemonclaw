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


def test_knowledge_file_ingest_extracts_html_title_and_metadata(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    html_path = tmp_path / "guide.html"
    html_path.write_text(
        "<html><head><title>Deploy Guide</title></head><body><h1>Deploy Guide</h1><p>Retry queue jobs after rollout.</p></body></html>",
        encoding="utf-8",
    )

    create_resp = client.post(
        "/api/knowledge/documents",
        json={
            "title": "",
            "source": str(html_path),
            "source_type": "file",
        },
    )
    assert create_resp.status_code == 200
    doc_id = create_resp.json()["document"]["doc_id"]

    ingest_resp = client.post(f"/api/knowledge/documents/{doc_id}/ingest")
    assert ingest_resp.status_code == 200
    document = ingest_resp.json()["document"]
    assert document["title"] == "Deploy Guide"
    assert document["metadata"]["extractor"] == "html-file"
    assert document["chunk_count"] >= 1


def test_knowledge_search_filters_and_reingest_all(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    first = client.post(
        "/api/knowledge/documents",
        json={
            "title": "Manual Recovery",
            "source": "manual://recover",
            "source_type": "manual",
            "content": "Retry outbox first before manual resume.",
        },
    ).json()["document"]
    second = client.post(
        "/api/knowledge/documents",
        json={
            "title": "Ops File",
            "source": "manual://ops",
            "source_type": "manual",
            "content": "Trigger history can explain alert spikes.",
        },
    ).json()["document"]

    reingest_resp = client.post("/api/knowledge/reingest")
    assert reingest_resp.status_code == 200
    body = reingest_resp.json()
    assert body["updated"] == 2
    assert body["failed"] == 0

    fact_resp = client.get("/api/knowledge/search?q=retry outbox&result_type=fact")
    assert fact_resp.status_code == 200
    fact_results = fact_resp.json()["results"]
    assert len(fact_results) >= 1
    assert all(item["result_type"] == "fact" for item in fact_results)

    source_resp = client.get("/api/knowledge/search?q=trigger history&source_type=manual")
    assert source_resp.status_code == 200
    source_results = source_resp.json()["results"]
    assert len(source_results) >= 1
    assert all(item["source_type"] == "manual" for item in source_results)


def test_knowledge_refresh_due_only_updates_due_documents(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    due_doc = client.post(
        "/api/knowledge/documents",
        json={
            "title": "Due Doc",
            "source": "manual://due",
            "source_type": "manual",
            "content": "Retry jobs after deploy.",
            "refresh_interval_hours": 1,
        },
    ).json()["document"]
    not_due_doc = client.post(
        "/api/knowledge/documents",
        json={
            "title": "Fresh Doc",
            "source": "manual://fresh",
            "source_type": "manual",
            "content": "Fresh content.",
            "refresh_interval_hours": 24,
        },
    ).json()["document"]

    client.post(f"/api/knowledge/documents/{due_doc['doc_id']}/ingest")
    client.post(f"/api/knowledge/documents/{not_due_doc['doc_id']}/ingest")

    # Force one doc into due state.
    patch_resp = client.patch(
        f"/api/knowledge/documents/{due_doc['doc_id']}",
        json={"refresh_interval_hours": 1},
    )
    assert patch_resp.status_code == 200

    from lemonclaw.knowledge import KnowledgeStore

    store = KnowledgeStore(tmp_path)
    stored = store.read_document(due_doc["doc_id"])
    stored["next_refresh_at_ms"] = 1
    manifest = {"version": 1, "documents": [stored] + [item for item in store.list_documents() if item["doc_id"] != due_doc["doc_id"]]}
    store._write_manifest_unlocked(manifest)  # type: ignore[attr-defined]

    refresh_resp = client.post("/api/knowledge/refresh-due")
    assert refresh_resp.status_code == 200
    body = refresh_resp.json()
    assert body["updated"] == 1
    assert body["failed"] == 0
