#!/usr/bin/env python3
"""Migrate legacy JSON ledger state into SQLite."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lemonclaw.ledger.migrate import migrate_json_to_sqlite


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", nargs="?", default=".", help="Workspace path")
    parser.add_argument("--force", action="store_true", help="Overwrite existing SQLite ledger data")
    parser.add_argument("--dry-run", action="store_true", help="Report migration counts without writing SQLite data")
    args = parser.parse_args()

    result = migrate_json_to_sqlite(
        Path(args.workspace).expanduser().resolve(),
        force=args.force,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
