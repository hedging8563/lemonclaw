"""Structured database inspection tool (SQLite-first)."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lemonclaw.agent.tools.base import Tool


def _is_safe_read_query(query: str) -> bool:
    stripped = query.strip().lower()
    if not stripped:
        return False
    allowed_starts = ("select", "pragma", "explain", "with")
    blocked = (
        "insert ",
        "update ",
        "delete ",
        "drop ",
        "alter ",
        "create ",
        "replace ",
        "truncate ",
        "attach ",
        "detach ",
        "vacuum",
    )
    return stripped.startswith(allowed_starts) and not any(token in stripped for token in blocked)


class DBTool(Tool):
    """Read-only database inspection tool."""

    def __init__(
        self,
        *,
        timeout: int = 15,
        sqlite_profiles: dict[str, str] | None = None,
        postgres_profiles: dict[str, dict[str, Any]] | None = None,
    ):
        self._timeout = timeout
        self._sqlite_profiles = sqlite_profiles or {}
        self._postgres_profiles = postgres_profiles or {}

    @property
    def name(self) -> str:
        return "db"

    @property
    def description(self) -> str:
        return (
            "Inspect database state with a read-only query. "
            "Currently supports configured SQLite and PostgreSQL profiles. "
            "Use this instead of shell database CLIs for structured inspection."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "connection_profile": {
                    "type": "string",
                    "description": "Configured database profile name.",
                },
                "query": {
                    "type": "string",
                    "description": "Read-only SQL query.",
                    "minLength": 1,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Maximum rows to return.",
                },
            },
            "required": ["connection_profile", "query"],
        }

    def resolve_capability(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> str:
        return "db.read"

    async def execute(self, connection_profile: str, query: str, limit: int | None = None, **kwargs: Any) -> dict[str, Any]:
        if not _is_safe_read_query(query):
            return {"ok": False, "summary": "Only read-only SELECT/PRAGMA/EXPLAIN/WITH queries are allowed", "raw": {"query": query}}

        row_limit = limit or 50
        if connection_profile in self._sqlite_profiles:
            return self._query_sqlite(connection_profile, query, row_limit)
        if connection_profile in self._postgres_profiles:
            return self._query_postgres(connection_profile, query, row_limit)
        return {
            "ok": False,
            "summary": f"Unknown database profile '{connection_profile}'",
            "raw": {"connection_profile": connection_profile},
        }

    def _query_sqlite(self, connection_profile: str, query: str, row_limit: int) -> dict[str, Any]:
        db_path = self._sqlite_profiles.get(connection_profile, "")
        path = Path(db_path).expanduser()
        if not path.exists():
            return {"ok": False, "summary": f"SQLite database not found for profile '{connection_profile}'", "raw": {"path": str(path)}}

        try:
            conn = sqlite3.connect(str(path), timeout=self._timeout)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute(query)
                rows = cursor.fetchmany(row_limit)
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
            finally:
                conn.close()
        except Exception as e:
            return {"ok": False, "summary": f"DB query failed: {e}", "raw": {"profile": connection_profile}}

        result_rows = [dict(row) for row in rows]
        return {
            "ok": True,
            "summary": f"SQLite query returned {len(result_rows)} row(s)",
            "raw": {
                "connection_profile": connection_profile,
                "engine": "sqlite",
                "path": str(path),
                "columns": columns,
                "rows": result_rows,
                "row_count": len(result_rows),
            },
        }

    def _query_postgres(self, connection_profile: str, query: str, row_limit: int) -> dict[str, Any]:
        profile = dict(self._postgres_profiles.get(connection_profile) or {})
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            return {
                "ok": False,
                "summary": "psycopg is not installed; PostgreSQL profiles are unavailable in this runtime",
                "raw": {"profile": connection_profile},
            }

        connect_kwargs = {
            "host": str(profile.get("host", "")),
            "port": int(profile.get("port", 5432)),
            "dbname": str(profile.get("dbname", "")),
            "user": str(profile.get("user", "")),
            "password": str(profile.get("password", "")),
            "sslmode": str(profile.get("sslmode", "prefer")),
            "connect_timeout": self._timeout,
            "row_factory": dict_row,
            "autocommit": True,
        }
        try:
            conn = psycopg.connect(**connect_kwargs)
            try:
                cursor = conn.execute(query)
                rows = cursor.fetchmany(row_limit)
                columns = [self._column_name(desc) for desc in (cursor.description or [])]
            finally:
                conn.close()
        except Exception as e:
            return {"ok": False, "summary": f"DB query failed: {e}", "raw": {"profile": connection_profile}}

        result_rows = [self._normalize_row(row) for row in rows]
        return {
            "ok": True,
            "summary": f"PostgreSQL query returned {len(result_rows)} row(s)",
            "raw": {
                "connection_profile": connection_profile,
                "engine": "postgres",
                "host": connect_kwargs["host"],
                "port": connect_kwargs["port"],
                "dbname": connect_kwargs["dbname"],
                "columns": columns,
                "rows": result_rows,
                "row_count": len(result_rows),
            },
        }

    @staticmethod
    def _normalize_row(row: Any) -> dict[str, Any]:
        if isinstance(row, Mapping):
            return dict(row)
        if hasattr(row, "_asdict"):
            return dict(row._asdict())
        return dict(row)

    @staticmethod
    def _column_name(description: Any) -> str:
        if hasattr(description, "name"):
            return str(description.name)
        if isinstance(description, (list, tuple)) and description:
            return str(description[0])
        return str(description)
