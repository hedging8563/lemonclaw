"""Append-only local audit log for capability execution."""

from __future__ import annotations

import json
from pathlib import Path

from lemonclaw.governance.types import AuditRecord


def append_audit_record(path: Path, record: AuditRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")


def read_audit_records(path: Path, *, limit: int = 50) -> list[dict]:
    if limit <= 0 or not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    records: list[dict] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except Exception:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return list(reversed(records))
