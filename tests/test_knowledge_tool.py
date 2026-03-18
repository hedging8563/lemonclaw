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
