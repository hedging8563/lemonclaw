"""Knowledge tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lemonclaw.agent.tools.base import Tool
from lemonclaw.knowledge import KnowledgeStore


class KnowledgeSearchTool(Tool):
    name = "search_knowledge"
    description = "Search registered knowledge sources that have been ingested."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "description": "Maximum results (1-8)", "minimum": 1, "maximum": 8},
            "source_type": {"type": "string", "description": "Optional filter: url | file | manual"},
            "result_type": {"type": "string", "description": "Optional filter: chunk | fact"},
        },
        "required": ["query"],
    }

    def __init__(self, workspace: str):
        self._store = KnowledgeStore(Path(workspace))

    async def execute(
        self,
        query: str,
        limit: int | None = None,
        source_type: str | None = None,
        result_type: str | None = None,
        **kwargs: Any,
    ) -> str:
        hits = self._store.search(
            query,
            limit=min(max(int(limit or 5), 1), 8),
            source_type=str(source_type or "").strip() or None,
            result_type=str(result_type or "").strip() or None,
        )
        if not hits:
            return f"No knowledge hits for: {query}"

        lines = [f"Knowledge hits for: {query}\n"]
        for idx, item in enumerate(hits, 1):
            lines.append(f"{idx}. {item.get('title') or item.get('doc_id')}")
            lines.append(f"   type={item.get('result_type') or 'chunk'} source={item.get('source') or '—'}")
            if item.get("snippet"):
                lines.append(f"   {item['snippet']}")
        return "\n".join(lines)

    def resolve_capability(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> str:
        return "tool.knowledge.read"
