"""Hybrid search — lancedb BM25 + vector + RRF reranking.

Optional dependency: falls back to keyword matching if lancedb is not installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
import time

from loguru import logger

if TYPE_CHECKING:
    from lemonclaw.providers.base import LLMProvider

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


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
        self._last_error: str = ""
        self._last_operation: str = ""
        self._last_updated_ms: int = 0
        self._last_indexed_docs: int = 0
        self._mode: str = "unavailable"

    @property
    def available(self) -> bool:
        return _lancedb_available()

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "mode": self._mode,
            "db_path": str(self._db_path),
            "db_exists": self._db_path.exists(),
            "last_operation": self._last_operation,
            "last_error": self._last_error,
            "last_updated_ms": self._last_updated_ms,
            "last_indexed_docs": self._last_indexed_docs,
        }

    def _record_status(self, *, operation: str, error: str = "", indexed_docs: int | None = None) -> None:
        self._last_operation = operation
        self._last_error = error[:500]
        self._last_updated_ms = int(time.time() * 1000)
        if indexed_docs is not None:
            self._last_indexed_docs = max(0, int(indexed_docs))

    def _set_mode(self, mode: str) -> None:
        self._mode = mode

    def _connect(self):
        """Lazy connect to lancedb."""
        if self._db is not None:
            return
        import lancedb
        self._db_path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(self._db_path))

    def _table_has_vector_column(self) -> bool:
        if self._table is None:
            return False
        try:
            return "vector" in list(self._table.schema.names)
        except Exception:
            return False

    def _get_or_create_table(self, data: list[dict] | None = None, *, with_vectors: bool = True, reset: bool = False):
        """Get existing table or create with initial data."""
        import pyarrow as pa

        self._connect()
        if reset:
            try:
                self._db.drop_table("memory")
            except Exception:
                pass
            self._table = None
        try:
            self._table = self._db.open_table("memory")
            if with_vectors and not self._table_has_vector_column():
                raise ValueError("memory table missing vector column for hybrid mode")
            if not with_vectors and self._table_has_vector_column():
                return
        except Exception:
            if not data:
                # Create empty table with schema
                fields = [
                    pa.field("id", pa.string()),
                    pa.field("source", pa.string()),
                    pa.field("name", pa.string()),
                    pa.field("text", pa.string()),
                ]
                if with_vectors:
                    fields.append(pa.field("vector", pa.list_(pa.float32(), self._embedding_dim)))
                schema = pa.schema(fields)
                self._table = self._db.create_table("memory", schema=schema)
            else:
                self._table = self._db.create_table("memory", data)

    async def _embed(self, texts: list[str], provider: LLMProvider, model: str | None = None) -> list[list[float]]:
        """Get embeddings via provider abstraction."""
        return await provider.embed(texts=texts, model=model or DEFAULT_EMBEDDING_MODEL)

    async def rebuild(self, provider: LLMProvider, model: str | None = None) -> int:
        """Rebuild the entire index from current memory files.

        Returns the number of documents indexed.
        """
        if not self.available:
            logger.debug("lancedb not available, skipping index rebuild")
            self._set_mode("keyword_only")
            self._record_status(operation="rebuild", error="lancedb_unavailable", indexed_docs=0)
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
            self._record_status(operation="rebuild", indexed_docs=0)
            return 0

        # Get embeddings
        texts = [d["text"] for d in docs]
        with_vectors = True
        try:
            vectors = await self._embed(texts, provider, model)
            for doc, vec in zip(docs, vectors):
                doc["vector"] = vec
            self._set_mode("hybrid")
        except Exception as e:
            logger.warning("Embedding failed, rebuilding FTS-only index: {}", e)
            with_vectors = False
            self._set_mode("fts_only")
            self._record_status(operation="rebuild", error=f"embed_failed:{type(e).__name__}", indexed_docs=0)

        # Recreate table
        self._connect()
        try:
            self._table = None
            self._get_or_create_table(docs, with_vectors=with_vectors, reset=True)
        except Exception as e:
            logger.warning("Failed to create memory table: {}", e)
            self._set_mode("keyword_only")
            self._record_status(operation="rebuild", error=f"table_create_failed:{type(e).__name__}", indexed_docs=0)
            return 0

        # Create FTS index for BM25
        try:
            self._table.create_fts_index("text", replace=True)
        except Exception as e:
            logger.warning("FTS index creation failed (BM25 disabled): {}", e)

        logger.info("Memory search index rebuilt: {} documents", len(docs))
        self._record_status(operation="rebuild", indexed_docs=len(docs))
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
            self._set_mode("keyword_only")
            self._record_status(operation="search", error="lancedb_unavailable")
            return []

        self._get_or_create_table()
        if self._table is None:
            self._record_status(operation="search", error="table_unavailable")
            return []

        # Check if table has data
        try:
            if self._table.count_rows() == 0:
                self._record_status(operation="search", indexed_docs=0)
                return []
        except Exception:
            self._record_status(operation="search", error="count_rows_failed")
            return []

        if self._mode == "hybrid":
            try:
                query_vec = (await self._embed([query], provider, model))[0]
                results = (
                    self._table.search(query_vec, query_type="hybrid")
                    .limit(limit)
                    .to_list()
                )
            except Exception as e:
                logger.debug("Hybrid search failed, falling back to FTS: {}", e)
                self._set_mode("fts_only")
                self._record_status(operation="search", error=f"hybrid_failed:{type(e).__name__}")
                results = (
                    self._table.search(query, query_type="fts")
                    .limit(limit)
                    .to_list()
                )
        else:
            try:
                results = (
                    self._table.search(query, query_type="fts")
                    .limit(limit)
                    .to_list()
                )
            except Exception as e:
                logger.debug("Search failed entirely: {}", e)
                self._record_status(operation="search", error=f"search_failed:{type(e).__name__}")
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
        self._record_status(operation="search", indexed_docs=len(output))
        return output

    async def upsert_entity(
        self, name: str, body: str, provider: LLMProvider, model: str | None = None,
    ) -> bool:
        """Incrementally update a single entity card in the index.

        Called when an entity card is created or updated, avoiding a full rebuild.
        Returns True on success, False on failure (non-fatal).
        """
        if not self.available:
            self._set_mode("keyword_only")
            self._record_status(operation="upsert_entity", error="lancedb_unavailable")
            return False

        try:
            self._get_or_create_table()
            if self._table is None:
                self._record_status(operation="upsert_entity", error="table_unavailable")
                return False

            text = f"{name}: {body.strip()}"
            doc = {
                "id": f"entity:{name}",
                "source": "entity",
                "name": name,
                "text": text,
            }
            if self._mode == "hybrid" and self._table_has_vector_column():
                try:
                    vectors = await self._embed([text], provider, model)
                    doc["vector"] = vectors[0]
                except Exception as e:
                    logger.debug("Entity embedding failed, downgrading to FTS-only: {}", e)
                    self._set_mode("fts_only")
                    self._get_or_create_table(with_vectors=False, reset=True)

            # Delete existing entry if present, then add new one
            try:
                self._table.delete(f'id = "entity:{name}"')
            except Exception:
                pass  # Table may be empty or entry may not exist
            self._table.add([doc])
            logger.debug("Search index updated for entity: {}", name)
            self._record_status(operation="upsert_entity", indexed_docs=1)
            return True
        except Exception as e:
            logger.debug("Failed to upsert entity in search index: {}", e)
            self._record_status(operation="upsert_entity", error=f"upsert_failed:{type(e).__name__}")
            return False

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
