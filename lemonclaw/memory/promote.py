"""Core memory promotion/demotion — LTM <-> Core lifecycle."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from loguru import logger

from lemonclaw.memory.entities import EntityCard, EntityStore

# Thresholds
PROMOTE_ACCESS_THRESHOLD = 15  # weekly access count to promote to Core
DEMOTE_DAYS_INACTIVE = 30     # days without access to demote from Core
CORE_MAX_TOKENS_APPROX = 2000  # rough token limit for core.md (~8000 chars)
CORE_MAX_CHARS = 8000


class CorePromoter:
    """Manages promotion from LTM to Core and demotion back.

    Core memory (core.md) is always loaded into system prompt.
    Only the most frequently accessed facts live here.
    """

    def __init__(self, memory_dir: Path, entity_store: EntityStore):
        self._core_file = memory_dir / "core.md"
        self._entities = entity_store
        self._memory_dir = memory_dir

    def read_core(self) -> str:
        if self._core_file.exists():
            return self._core_file.read_text(encoding="utf-8")
        return ""

    def write_core(self, content: str) -> None:
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._core_file.write_text(content, encoding="utf-8")

    def add_to_core(self, text: str) -> bool:
        """Add a fact to core.md if within size limit. Returns True if added."""
        current = self.read_core()
        new_content = (current.rstrip() + "\n" + text.strip() + "\n") if current.strip() else text.strip() + "\n"
        if len(new_content) > CORE_MAX_CHARS:
            logger.warning("Core memory full ({} chars), cannot add", len(new_content))
            return False
        self.write_core(new_content)
        return True

    def remove_from_core(self, fragment: str) -> bool:
        """Remove lines containing fragment from core.md. Returns True if removed."""
        current = self.read_core()
        if not current:
            return False
        lines = current.splitlines()
        filtered = [l for l in lines if fragment.lower() not in l.lower()]
        if len(filtered) == len(lines):
            return False
        self.write_core("\n".join(filtered) + "\n" if filtered else "")
        return True

    def run_promotion(self) -> list[str]:
        """Check LTM cards and promote high-access ones to Core.

        Returns list of promoted card names.
        """
        promoted: list[str] = []
        for card in self._entities.list_cards():
            if card.access_count >= PROMOTE_ACCESS_THRESHOLD:
                # Extract first meaningful line as summary
                summary = self._extract_summary(card)
                if summary and self.add_to_core(f"- [{card.name}] {summary}"):
                    promoted.append(card.name)
                    # Reset access count after promotion
                    card.meta["access_count"] = 0
                    card.save()
                    logger.info("Promoted '{}' to Core memory", card.name)
        return promoted

    def run_demotion(self) -> list[str]:
        """Check Core entries and demote inactive ones back to LTM.

        Returns list of demoted fragments.
        """
        current = self.read_core()
        if not current:
            return []

        today = date.today()
        demoted: list[str] = []
        lines_to_keep: list[str] = []

        for line in current.splitlines():
            # Check if any LTM card references this line and was recently accessed
            keep = False
            for card in self._entities.list_cards():
                if card.name in line:
                    last = card.meta.get("last_accessed", "")
                    if last:
                        try:
                            last_date = date.fromisoformat(last)
                            if (today - last_date).days < DEMOTE_DAYS_INACTIVE:
                                keep = True
                                break
                        except ValueError:
                            keep = True  # Can't parse date, keep it safe
                            break
                    else:
                        keep = True
                        break

            if not line.strip():
                lines_to_keep.append(line)
            elif keep or not line.strip().startswith("- ["):
                lines_to_keep.append(line)
            else:
                demoted.append(line.strip())
                logger.info("Demoted from Core: {}", line.strip()[:60])

        if demoted:
            self.write_core("\n".join(lines_to_keep) + "\n" if lines_to_keep else "")
        return demoted

    @staticmethod
    def _extract_summary(card: EntityCard) -> str:
        """Extract first non-header, non-empty line from card body."""
        for line in card.body.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line[:120]
        return ""
