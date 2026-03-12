"""Append-only local audit log for capability execution."""

from __future__ import annotations

import json
from pathlib import Path

from lemonclaw.governance.types import AuditRecord


def append_audit_record(path: Path, record: AuditRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
