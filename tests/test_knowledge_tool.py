from pathlib import Path

import pytest

from lemonclaw.agent.tools.knowledge import KnowledgeSearchTool
from lemonclaw.knowledge import KnowledgeStore


@pytest.mark.asyncio
async def test_knowledge_search_tool_returns_ranked_hits(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path)
    doc = store.create_document(
        source_type="manual",
        source="manual://ops",
        title="Ops Notes",
        content="Retry failed outbox events before triggering manual recovery.",
    )
    store.ingest_document(doc["doc_id"])

    tool = KnowledgeSearchTool(workspace=str(tmp_path))
    result = await tool.execute("retry outbox")

    assert "Knowledge hits for: retry outbox" in result
    assert "Ops Notes" in result
    assert "manual://ops" in result


def test_knowledge_search_skips_archived_documents(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path)
    doc = store.create_document(
        source_type="manual",
        source="manual://archive-me",
        title="Archive Candidate",
        content="Retry outbox events before triggering manual recovery.",
    )
    store.ingest_document(doc["doc_id"])

    assert store.list_chunks(doc["doc_id"])

    archived = store.archive_document(doc["doc_id"])
    assert archived["archived"] is True
    assert store.list_chunks(doc["doc_id"])
    assert store.search("retry outbox") == []


def test_knowledge_ingest_error_clears_stale_search_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = KnowledgeStore(tmp_path)
    doc = store.create_document(
        source_type="manual",
        source="manual://broken-refresh",
        title="Broken Refresh",
        content="Retry outbox events before triggering manual recovery.",
    )
    store.ingest_document(doc["doc_id"])
    assert store.search("retry outbox")

    def fail(_document: dict[str, object]) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(store, "_load_document_content", fail)

    with pytest.raises(RuntimeError, match="boom"):
        store.ingest_document(doc["doc_id"])

    refreshed = store.read_document(doc["doc_id"])
    assert refreshed is not None
    assert refreshed["status"] == "error"
    assert store.list_chunks(doc["doc_id"]) == []
    assert store.list_facts(doc["doc_id"]) == []
    assert store.search("retry outbox") == []


def test_knowledge_url_sources_reject_non_http_schemes(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path)

    with pytest.raises(ValueError, match="http or https"):
        store.create_document(
            source_type="url",
            source="file:///etc/passwd",
            title="Nope",
        )
