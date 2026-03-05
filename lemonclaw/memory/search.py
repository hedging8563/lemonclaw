"""Hybrid search — lancedb BM25 + vector + RRF reranking.

Optional dependency: falls back to keyword matching if lancedb is not installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from lemonclaw.providers.base import LLMProvider

# Default embedding model (via LemonData gateway / LiteLLM)
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

# Schema fields
_SCHEMA_FIELDS = ["id", "source", "name", "text", "vector"]


def _lancedb_available() -> bool:
    try:
        import lancedb  # noqa: F401
        return True
    except ImportError:
        return False


class MemorySearchIndex:
    """Manages a lancedb hybrid search index over memory documents.

    Documents are indexed from:
    - LTM entity cards (memory/entities/*.md)
    - Procedural rules (memory/rules.md)
    - HISTORY.md entries

    Core memory and today.md are NOT indexed — they're always in prompt.
    """

    def __init__(self, memory_dir: Path, embedding_dim: int = 1536):
        self._db_path = memory_dir / ".vectordb"
        self._memory_dir = memory_dir
        self._embedding_dim = embedding_dim
        self._db = None
        self._table = None

    @property
    def available(self) -> bool:
        return _lancedb_available()

    def _connect(self):
        """Lazy connect to lancedb."""
        if self._db is not None:
            return
        import lancedb
        self._db_path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(self._db_path))

    def _get_or_create_table(self, data: list[dict] | None = None):
        """Get existing table or create with initial data."""
        import pyarrow as pa

        self._connect()
        try:
            self._table = self._db.open_table("memory")
        except Exception:
            if not data:
                # Create empty table with schema
                schema = pa.schema([
                    pa.field("id", pa.string()),
                    pa.field("source", pa.string()),
                    pa.field("name", pa.string()),
                    pa.field("text", pa.string()),
                    pa.field("vector", pa.list_(pa.float32(), self._embedding_dim)),
                ])
                self._table = self._db.create_table("memory", schema=schema)
            else:
                self._table = self._db.create_table("memory", data)

    async def _embed(self, texts: list[str], provider: LLMProvider, model: str | None = None) -> list[list[float]]:
        """Get embeddings via litellm (uses the same provider config)."""
        from litellm import aembedding

        model = model or DEFAULT_EMBEDDING_MODEL
        response = await aembedding(model=model, input=texts)
        return [item["embedding"] for item in response.data]

    async def rebuild(self, provider: LLMProvider, model: str | None = None) -> int:
        """Rebuild the entire index from current memory files.

        Returns the number of documents indexed.
        """
        if not self.available:
            logger.debug("lancedb not available, skipping index rebuild")
            return 0

        from lemonclaw.memory.entities import EntityStore
        from lemonclaw.memory.reflect import ProceduralMemory

        docs: list[dict[str, Any]] = []

        # Index entity cards
        store = EntityStore(self._memory_dir)
        for card in store.list_cards():
            text = f"{card.name}: {card.body.strip()}"
            docs.append({
                "id": f"entity:{card.name}",
                "source": "entity",
                "name": card.name,
                "text": text,
            })

        # Index procedural rules
        pm = ProceduralMemory(self._memory_dir)
        for rule in pm.list_rules():
            text = f"{rule.get('trigger', '')}: {rule.get('lesson', '')} → {rule.get('action', '')}"
            docs.append({
                "id": f"rule:{rule.get('header', '?')}",
                "source": "rule",
                "name": rule.get("trigger", "?"),
                "text": text,
            })

        # Index HISTORY.md entries
        history_file = self._memory_dir / "HISTORY.md"
        if history_file.exists():
            content = history_file.read_text(encoding="utf-8")
            entries = [e.strip() for e in content.split("\n\n") if e.strip()]
            for i, entry in enumerate(entries[-100:]):  # Last 100 entries
                docs.append({
                    "id": f"history:{i}",
                    "source": "history",
                    "name": entry[:50],
                    "text": entry,
                })

        if not docs:
            logger.debug("No documents to index")
            return 0

        # Get embeddings
        texts = [d["text"] for d in docs]
        try:
            vectors = await self._embed(texts, provider, model)
        except Exception as e:
            logger.warning("Embedding failed, index not rebuilt: {}", e)
            return 0

        for doc, vec in zip(docs, vectors):
            doc["vector"] = vec

        # Recreate table
        self._connect()
        try:
            self._db.drop_table("memory")
        except Exception:
            logger.warning("Failed to drop old memory table, rebuild may fail")
        self._table = self._db.create_table("memory", docs)

        # Create FTS index for BM25
        try:
            self._table.create_fts_index("text", replace=True)
        except Exception as e:
            logger.warning("FTS index creation failed (BM25 disabled): {}", e)

        logger.info("Memory search index rebuilt: {} documents", len(docs))
        return len(docs)

    async def search(
        self,
        query: str,
        provider: LLMProvider,
        *,
        limit: int = 5,
        model: str | None = None,
        source_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Hybrid search: BM25 + vector + RRF reranking.

        Falls back to BM25-only if embedding fails.
        Returns list of dicts with id, source, name, text, _relevance_score.
        """
        if not self.available:
            return []

        self._get_or_create_table()
        if self._table is None:
            return []

        # Check if table has data
        try:
            if self._table.count_rows() == 0:
                return []
        except Exception:
            return []

        # Try hybrid search (BM25 + vector)
        try:
            query_vec = (await self._embed([query], provider, model))[0]
            results = (
                self._table.search(query_vec, query_type="hybrid")
                .limit(limit)
                .to_list()
            )
        except Exception:
            # Fallback: BM25 only
            try:
                results = (
                    self._table.search(query, query_type="fts")
                    .limit(limit)
                    .to_list()
                )
            except Exception as e:
                logger.debug("Search failed entirely: {}", e)
                return []

        # Filter by source if requested
        if source_filter:
            results = [r for r in results if r.get("source") == source_filter]

        # Normalize output
        output = []
        for r in results[:limit]:
            output.append({
                "id": r.get("id", ""),
                "source": r.get("source", ""),
                "name": r.get("name", ""),
                "text": r.get("text", ""),
                "_relevance_score": r.get("_relevance_score", r.get("_distance", 0)),
            })
        return output

    async def search_entities(
        self, query: str, provider: LLMProvider, *, limit: int = 3, model: str | None = None
    ) -> list[dict[str, Any]]:
        """Search only entity cards."""
        return await self.search(query, provider, limit=limit, model=model, source_filter="entity")

    async def search_rules(
        self, query: str, provider: LLMProvider, *, limit: int = 2, model: str | None = None
    ) -> list[dict[str, Any]]:
        """Search only procedural rules."""
        return await self.search(query, provider, limit=limit, model=model, source_filter="rule")
