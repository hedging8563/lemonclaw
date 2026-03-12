"""Parse SOUL.md into lightweight sections."""

from __future__ import annotations


def parse_soul_markdown(content: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_key: str | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf, current_key
        if current_key is not None:
            text = "\n".join(buf).strip()
            if text:
                sections[current_key] = text
        buf = []

    for line in content.splitlines():
        if line.startswith("## "):
            flush()
            heading = line[3:].strip().lower()
            if heading in {"identity", "operating doctrine", "values"}:
                current_key = heading.replace(" ", "_")
            else:
                current_key = None
            continue
        buf.append(line)

    flush()
    if sections:
        return sections
    legacy = content.strip()
    return {"legacy": legacy} if legacy else {}
