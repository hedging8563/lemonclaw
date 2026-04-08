"""Shared redaction helpers for governance, logging, and export surfaces."""

from __future__ import annotations

import re
from typing import Any, Iterable


_SENSITIVE_KEY_RE = re.compile(
    r"(^|[_-])(authorization|token|secret|password|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)($|[_-])",
    re.IGNORECASE,
)
_VISIBLE_REFERENCE_KEYS = {"secret_profile", "sandbox_profile", "approval_policy", "identity_mode"}

_TOKEN_ASSIGNMENT_RE = re.compile(
    r"(?P<prefix>\b[A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|ACCESS_TOKEN|REFRESH_TOKEN)\s*=\s*)(?P<secret>[^\s\"'`;]+)"
)
_STRUCTURED_SECRET_RE = re.compile(
    r"(?P<prefix>(?i:(?:authorization|token|secret|password|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret))[\"']?\s*[:=]\s*[\"']?)(?P<secret>[^\"'\s,;]+)"
)
_BEARER_TOKEN_RE = re.compile(r"(?P<prefix>\bBearer\s+)(?P<secret>[^\s,;]+)", re.IGNORECASE)
_BASIC_TOKEN_RE = re.compile(r"(?P<prefix>\bBasic\s+)(?P<secret>[^\s,;]+)", re.IGNORECASE)
_CREDENTIAL_URL_RE = re.compile(r"(?P<prefix>https?://[^/\s:@]+:)(?P<secret>[^@\s]+)(?P<suffix>@)")
_JWT_TOKEN_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9._-]+\.[A-Za-z0-9._-]+\b")
_DIRECT_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")

_KNOWN_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|key|api)-[A-Za-z0-9._-]{8,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\b(?:xoxb|xapp|xoxa|xoxp)-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9._-]{16,}\b"),
    re.compile(r"\b(?:rk|pk|whsec)_[A-Za-z0-9._-]{16,}\b"),
)
_AGGRESSIVE_SECRET_PATTERNS = (
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
)


def _looks_like_generic_token(candidate: str) -> bool:
    if not isinstance(candidate, str):
        return False
    stripped = candidate.strip()
    if len(stripped) < 32 or stripped == "[REDACTED]":
        return False
    if stripped.startswith(("http://", "https://", "file://", "/")):
        return False
    has_lower = any(ch.islower() for ch in stripped)
    has_upper = any(ch.isupper() for ch in stripped)
    has_digit = any(ch.isdigit() for ch in stripped)
    return has_lower and has_upper and has_digit


def _replace_secret_match(match: re.Match[str]) -> str:
    return f"{match.group('prefix')}[REDACTED]"


def redact_sensitive_text(
    text: str,
    *,
    configured_secret_values: Iterable[str] | None = None,
    aggressive: bool = False,
) -> str:
    """Redact likely secret values embedded in free-form text.

    ``aggressive=True`` enables broader fallback patterns intended for logs,
    where false positives are preferable to secret leakage.
    """
    if not isinstance(text, str) or not text:
        return text

    redacted = text
    configured = tuple(
        sorted(
            (v for v in (configured_secret_values or ()) if isinstance(v, str) and v),
            key=len,
            reverse=True,
        )
    )
    for secret in configured:
        if secret and secret in redacted:
            redacted = redacted.replace(secret, "[REDACTED]")

    redacted = _TOKEN_ASSIGNMENT_RE.sub(_replace_secret_match, redacted)
    redacted = _STRUCTURED_SECRET_RE.sub(_replace_secret_match, redacted)
    redacted = _BEARER_TOKEN_RE.sub(_replace_secret_match, redacted)
    redacted = _BASIC_TOKEN_RE.sub(_replace_secret_match, redacted)
    redacted = _CREDENTIAL_URL_RE.sub(r"\g<prefix>[REDACTED]\g<suffix>", redacted)
    redacted = _JWT_TOKEN_RE.sub("[REDACTED]", redacted)

    for pattern in _KNOWN_SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)

    if aggressive:
        for pattern in _AGGRESSIVE_SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)

    def _direct_token_replacer(match: re.Match[str]) -> str:
        candidate = match.group(0)
        return "[REDACTED]" if _looks_like_generic_token(candidate) else candidate

    return _DIRECT_TOKEN_RE.sub(_direct_token_replacer, redacted)


def contains_sensitive_credential(text: str) -> bool:
    """Best-effort detector for credentials pasted into free-form chat text."""
    if not isinstance(text, str) or not text.strip():
        return False
    stripped = text.strip()
    if _looks_like_generic_token(stripped):
        return True
    if (
        _TOKEN_ASSIGNMENT_RE.search(text)
        or _STRUCTURED_SECRET_RE.search(text)
        or _BEARER_TOKEN_RE.search(text)
        or _BASIC_TOKEN_RE.search(text)
        or _CREDENTIAL_URL_RE.search(text)
        or _JWT_TOKEN_RE.search(text)
    ):
        return True
    if any(pattern.search(text) for pattern in _KNOWN_SECRET_PATTERNS):
        return True
    return any(_looks_like_generic_token(match.group(0)) for match in _DIRECT_TOKEN_RE.finditer(text))


def redact_sensitive_value(
    value: Any,
    *,
    configured_secret_values: Iterable[str] | None = None,
) -> Any:
    """Recursively redact sensitive values by key name and configured secret values.

    For configured secrets we intentionally use exact known values and direct
    substring replacement, not generic regex guessing. That keeps redaction
    predictable while still catching common wrappers like ``Bearer <token>``.
    """
    configured = tuple(
        sorted(
            (v for v in (configured_secret_values or ()) if isinstance(v, str) and v),
            key=len,
            reverse=True,
        )
    )
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
    if isinstance(value, str):
        redacted = redact_sensitive_text(value, configured_secret_values=configured_secret_values)
        if redacted != value:
            return redacted.replace("[REDACTED]", "[redacted]")
    return value
