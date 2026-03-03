"""Entity card management — LTM structured memory with Frontmatter + Markdown."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from loguru import logger

# Default entity card types
DEFAULT_CARDS: dict[str, dict[str, Any]] = {
    "user-profile": {"type": "person", "keywords": ["用户", "偏好", "习惯", "喜欢", "记住我"]},
    "project-tracker": {"type": "project", "keywords": ["项目", "进度", "deadline", "里程碑"]},
    "tech-stack": {"type": "tech", "keywords": ["技术", "版本", "框架", "工具链"]},
    "preferences": {"type": "preference", "keywords": ["总是", "不要", "习惯", "风格"]},
    "methodology": {"type": "process", "keywords": ["流程", "规范", "怎么做", "步骤"]},
    "contacts": {"type": "person", "keywords": ["谁是", "联系", "团队"]},
    "decisions": {"type": "decision", "keywords": ["决定", "选择", "为什么", "权衡"]},
    "issues": {"type": "issue", "keywords": ["bug", "问题", "踩坑", "错误"]},
    "goals": {"type": "goal", "keywords": ["目标", "计划", "下一步", "TODO"]},
}

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-like frontmatter from markdown text. Returns (meta, body)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip()
        # Parse simple lists: [a, b, c]
        if val.startswith("[") and val.endswith("]"):
            meta[key.strip()] = [v.strip() for v in val[1:-1].split(",") if v.strip()]
        # Parse integers
        elif val.isdigit():
            meta[key.strip()] = int(val)
        else:
            meta[key.strip()] = val
    return meta, text[m.end():]


def _render_frontmatter(meta: dict[str, Any]) -> str:
    """Render metadata dict as YAML-like frontmatter."""
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, list):
            lines.append(f"{k}: [{', '.join(str(i) for i in v)}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n"


class EntityCard:
    """A single LTM entity card (Frontmatter + Markdown)."""

    __slots__ = ("name", "meta", "body", "path")

    def __init__(self, name: str, meta: dict[str, Any], body: str, path: Path):
        self.name = name
        self.meta = meta
        self.body = body
        self.path = path

    @property
    def keywords(self) -> list[str]:
        return self.meta.get("keywords", [])

    @property
    def access_count(self) -> int:
        return self.meta.get("access_count", 0)

    def record_access(self) -> None:
        self.meta["access_count"] = self.access_count + 1
        self.meta["last_accessed"] = str(date.today())

    def save(self) -> None:
        text = _render_frontmatter(self.meta) + self.body
        self.path.write_text(text, encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> EntityCard:
        text = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(text)
        name = path.stem
        return cls(name=name, meta=meta, body=body, path=path)


class EntityStore:
    """Manages LTM entity cards in memory/entities/ directory."""

    def __init__(self, memory_dir: Path):
        self.entities_dir = memory_dir / "entities"
        self._cards: dict[str, EntityCard] | None = None  # lazy cache

    def _ensure_dir(self) -> None:
        self.entities_dir.mkdir(parents=True, exist_ok=True)

    def _load_all(self) -> dict[str, EntityCard]:
        """Load all entity cards from disk."""
        if self._cards is not None:
            return self._cards
        self._cards = {}
        if not self.entities_dir.exists():
            return self._cards
        for p in sorted(self.entities_dir.glob("*.md")):
            try:
                card = EntityCard.load(p)
                self._cards[card.name] = card
            except Exception as e:
                logger.warning("Failed to load entity card {}: {}", p.name, e)
        return self._cards

    def list_cards(self) -> list[EntityCard]:
        return list(self._load_all().values())

    def get_card(self, name: str) -> EntityCard | None:
        return self._load_all().get(name)

    def create_card(self, name: str, card_type: str, keywords: list[str], body: str = "") -> EntityCard:
        """Create a new entity card."""
        self._ensure_dir()
        meta = {
            "type": card_type,
            "keywords": keywords,
            "access_count": 0,
            "last_accessed": str(date.today()),
            "created": str(date.today()),
        }
        path = self.entities_dir / f"{name}.md"
        card = EntityCard(name=name, meta=meta, body=body, path=path)
        card.save()
        cards = self._load_all()
        cards[name] = card
        logger.debug("Created entity card: {}", name)
        return card

    def update_card(self, name: str, body: str) -> EntityCard | None:
        """Update card body content."""
        card = self.get_card(name)
        if card is None:
            return None
        card.body = body
        card.save()
        return card

    def init_defaults(self) -> int:
        """Create default entity cards if entities/ is empty. Returns count created."""
        self._ensure_dir()
        cards = self._load_all()
        if cards:
            return 0
        created = 0
        for name, info in DEFAULT_CARDS.items():
            if name not in cards:
                title = name.replace("-", " ").title()
                self.create_card(name, info["type"], info["keywords"], body=f"# {title}\n\n")
                created += 1
        logger.info("Initialized {} default entity cards", created)
        return created

    def invalidate_cache(self) -> None:
        self._cards = None
