from __future__ import annotations

import sqlite3
import sys
import types

import pytest

from lemonclaw.agent.tools.db import DBTool


def _make_db(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("create table items (id integer primary key, name text)")
    conn.execute("insert into items (name) values ('alpha')")
    conn.execute("insert into items (name) values ('beta')")
    conn.commit()
    conn.close()
    return db_path


@pytest.mark.asyncio
async def test_db_tool_reads_sqlite_profile(tmp_path):
    db_path = _make_db(tmp_path)
    tool = DBTool(sqlite_profiles={"local": str(db_path)})
    result = await tool.execute("local", "select * from items order by id")
    assert result["ok"] is True
    assert result["raw"]["engine"] == "sqlite"
    assert result["raw"]["row_count"] == 2
    assert result["raw"]["rows"][0]["name"] == "alpha"


@pytest.mark.asyncio
async def test_db_tool_rejects_write_queries(tmp_path):
    db_path = _make_db(tmp_path)
    tool = DBTool(sqlite_profiles={"local": str(db_path)})
    result = await tool.execute("local", "delete from items")
    assert result["ok"] is False
    assert "read-only" in result["summary"]


def test_db_tool_resolves_capability():
    tool = DBTool()
    assert tool.resolve_capability({"connection_profile": "local", "query": "select 1"}) == "db.read"


@pytest.mark.asyncio
async def test_db_tool_reads_postgres_profile(monkeypatch: pytest.MonkeyPatch):
    class DummyCursor:
        description = [("id",), ("name",)]

        def fetchmany(self, limit):
            assert limit == 50
            return [{"id": 1, "name": "alpha"}]

    class DummyConnection:
        def __init__(self):
            self.closed = False
            self.executed = None

        def execute(self, query):
            self.executed = query
            return DummyCursor()

        def close(self):
            self.closed = True

    captured = {}
    dummy_connection = DummyConnection()

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return dummy_connection

    psycopg_module = types.SimpleNamespace(connect=fake_connect)
    rows_module = types.SimpleNamespace(dict_row=object())
    monkeypatch.setitem(sys.modules, "psycopg", psycopg_module)
    monkeypatch.setitem(sys.modules, "psycopg.rows", rows_module)

    tool = DBTool(postgres_profiles={
        "analytics": {
            "host": "db.example.internal",
            "port": 5432,
            "dbname": "analytics",
            "user": "reader",
            "password": "secret",
            "sslmode": "require",
        }
    })
    result = await tool.execute("analytics", "select * from events")

    assert result["ok"] is True
    assert result["raw"]["engine"] == "postgres"
    assert result["raw"]["rows"][0]["name"] == "alpha"
    assert captured["host"] == "db.example.internal"
    assert captured["sslmode"] == "require"
    assert dummy_connection.closed is True


@pytest.mark.asyncio
async def test_db_tool_returns_clear_error_when_psycopg_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delitem(sys.modules, "psycopg", raising=False)
    monkeypatch.delitem(sys.modules, "psycopg.rows", raising=False)

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "psycopg" or name == "psycopg.rows":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    tool = DBTool(postgres_profiles={"analytics": {"host": "db", "dbname": "x", "user": "u"}})
    result = await tool.execute("analytics", "select 1")

    assert result["ok"] is False
    assert "psycopg is not installed" in result["summary"]
