"""Mode inference and prompt overlays."""

from __future__ import annotations

from lemonclaw.bus.events import InboundMessage


def infer_mode(msg: InboundMessage) -> str:
    if msg.channel == "cron":
        return "cron"
    if msg.channel in {"system", "internal"}:
        return "operator"
    return "chat"


def build_mode_overlay(mode: str) -> str:
    overlays = {
        "chat": (
            "You are in chat mode.\n"
            "- Optimize for direct answers and interactive conversation.\n"
            "- Avoid high-risk side effects unless explicitly necessary."
        ),
        "operator": (
            "You are in operator mode.\n"
            "- Optimize for state inspection, execution, verification, and rollback awareness.\n"
            "- Prefer observable, auditable actions over clever shortcuts."
        ),
        "cron": (
            "You are in cron mode.\n"
            "- Prefer idempotent, low-side-effect behavior.\n"
            "- Keep outputs concise and execution conservative."
        ),
        "coding": (
            "You are in coding mode.\n"
            "- Optimize for reading code, making scoped changes, and verifying them.\n"
            "- Prefer structured edits and tests over ad-hoc shell work."
        ),
        "researcher": (
            "You are in researcher mode.\n"
            "- Optimize for exploration, synthesis, and evidence gathering.\n"
            "- Do not over-commit beyond the available evidence."
        ),
    }
    return overlays.get(mode, "")
