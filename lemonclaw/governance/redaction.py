"""Shared redaction helpers for governance and export surfaces."""

from __future__ import annotations

import re
from typing import Any, Iterable


_SENSITIVE_KEY_RE = re.compile(
    r"(^|[_-])(authorization|token|secret|password|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)($|[_-])",
    re.IGNORECASE,
)
_VISIBLE_REFERENCE_KEYS = {"secret_profile", "sandbox_profile", "approval_policy", "identity_mode"}


def redact_sensitive_value(
    value: Any,
    *,
    configured_secret_values: Iterable[str] | None = None,
) -> Any:
    """Recursively redact sensitive values by key name and exact configured secret match."""
    configured = tuple(v for v in (configured_secret_values or ()) if isinstance(v, str) and v)
    return _redact(value, configured)


def _redact(value: Any, configured_secret_values: tuple[str, ...]) -> Any:
    if isinstance(value, list):
        return [_redact(item, configured_secret_values) for item in value]
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, nested in value.items():
            if key in _VISIBLE_REFERENCE_KEYS:
                redacted[key] = nested
            elif _SENSITIVE_KEY_RE.search(str(key)):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = _redact(nested, configured_secret_values)
        return redacted
    if isinstance(value, str) and configured_secret_values and value in configured_secret_values:
        return "[redacted]"
    return value
