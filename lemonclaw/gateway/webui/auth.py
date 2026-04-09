"""HMAC cookie authentication and mutable gateway auth state helpers for WebUI.

Cookie format: base64(created_ts:last_ts:nonce:hmac_sha256)
- created_ts: absolute session start (epoch seconds)
- last_ts: last activity timestamp (epoch seconds)
- nonce: random 16-byte hex to prevent replay
- hmac: SHA-256 HMAC of "created_ts:last_ts:nonce" keyed by auth_token

Timeouts:
- Idle: 4 hours (no activity -> re-login)
- Absolute: 7 days (hard session limit)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

IDLE_TIMEOUT = 4 * 60 * 60  # 4 hours
ABSOLUTE_TIMEOUT = 7 * 24 * 60 * 60  # 7 days
FUTURE_SKEW_TOLERANCE = 5 * 60  # 5 minutes
COOKIE_NAME = "lc_session"
_GATEWAY_AUTH_STATE_FILE = ".gateway-auth.json"
_GATEWAY_RECOVERY_MIN_TTL_S = 60
_GATEWAY_RECOVERY_MAX_TTL_S = 3600


@dataclass
class GatewayAuthState:
    """Mutable gateway auth state shared across gateway route surfaces."""

    token: str | None
    config_path: Path | None = None
    rotation_count: int = 0
    last_rotated_at_ms: int | None = None
    last_rotation_reason: str | None = None
    recovery_code_hash: str | None = None
    recovery_issued_at_ms: int | None = None
    recovery_expires_at_ms: int | None = None
    audit: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, config_path: Path | None, *, fallback_token: str | None = None) -> "GatewayAuthState":
        """Load auth state from disk, seeding from the fallback token when needed."""
        state_path = _gateway_auth_state_path(config_path) if config_path else None
        raw = _read_json(state_path) if state_path else {}
        token = str(raw.get("current_token") or "") or fallback_token
        state = cls(
            token=token,
            config_path=config_path,
            rotation_count=_coerce_int(raw.get("rotation_count")) or 0,
            last_rotated_at_ms=_coerce_int(raw.get("last_rotated_at_ms")),
            last_rotation_reason=str(raw.get("last_rotation_reason") or "") or None,
            recovery_code_hash=str((raw.get("recovery") or {}).get("code_hash") or "") or None,
            recovery_issued_at_ms=_coerce_int((raw.get("recovery") or {}).get("issued_at_ms")),
            recovery_expires_at_ms=_coerce_int((raw.get("recovery") or {}).get("expires_at_ms")),
            audit=[item for item in raw.get("audit", []) if isinstance(item, dict)],
        )
        if token and state_path and not raw:
            state.persist()
        return state

    def persist(self) -> None:
        """Persist auth state to the sidecar JSON file."""
        if not self.config_path:
            return
        state_path = _gateway_auth_state_path(self.config_path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "current_token": self.token,
            "current_token_fingerprint": _token_fingerprint(self.token),
            "rotation_count": self.rotation_count,
            "last_rotated_at_ms": self.last_rotated_at_ms,
            "last_rotation_reason": self.last_rotation_reason,
            "recovery": {
                "code_hash": self.recovery_code_hash,
                "issued_at_ms": self.recovery_issued_at_ms,
                "expires_at_ms": self.recovery_expires_at_ms,
            },
            "audit": self.audit[-20:],
        }
        tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        tmp_path.rename(state_path)
        try:
            state_path.chmod(0o600)
        except OSError:
            pass

    def rotate(self, new_token: str, *, reason: str = "manual-rotate") -> None:
        """Rotate to a new live token and record the change."""
        now_ms = _now_ms()
        old_fp = _token_fingerprint(self.token)
        new_fp = _token_fingerprint(new_token)
        had_recovery = bool(self.recovery_code_hash)
        self.token = new_token
        self.rotation_count += 1
        self.last_rotated_at_ms = now_ms
        self.last_rotation_reason = reason
        self.recovery_code_hash = None
        self.recovery_issued_at_ms = None
        self.recovery_expires_at_ms = None
        self._append_audit({
            "event": "rotate",
            "at_ms": now_ms,
            "reason": reason,
            "old_fingerprint": old_fp,
            "new_fingerprint": new_fp,
        })
        if had_recovery:
            self._append_audit({
                "event": "recovery_code_invalidated",
                "at_ms": now_ms,
                "reason": "token-rotated",
            })
        self.persist()

    def issue_recovery_code(self, *, ttl_s: int = 600, purpose: str = "gateway-token-recovery") -> dict[str, Any]:
        """Issue a one-time recovery code and persist the hash only."""
        ttl = max(_GATEWAY_RECOVERY_MIN_TTL_S, min(int(ttl_s), _GATEWAY_RECOVERY_MAX_TTL_S))
        code = f"lc_recovery_{_random_token(18)}"
        now_ms = _now_ms()
        self.recovery_code_hash = _hash_recovery_code(code)
        self.recovery_issued_at_ms = now_ms
        self.recovery_expires_at_ms = now_ms + ttl * 1000
        self._append_audit({
            "event": "recovery_code_issued",
            "at_ms": now_ms,
            "ttl_s": ttl,
            "purpose": purpose,
        })
        self.persist()
        return {
            "code": code,
            "issued_at_ms": now_ms,
            "expires_at_ms": self.recovery_expires_at_ms,
            "ttl_s": ttl,
            "purpose": purpose,
        }

    def consume_recovery_code(self, code: str) -> bool:
        """Consume a recovery code if it is active and valid."""
        if not self.recovery_code_hash or not self.recovery_expires_at_ms:
            return False
        now_ms = _now_ms()
        if self.recovery_expires_at_ms < now_ms:
            self.clear_recovery_code()
            return False
        if _hash_recovery_code(code) != self.recovery_code_hash:
            return False
        self._append_audit({
            "event": "recovery_code_consumed",
            "at_ms": now_ms,
            "expires_at_ms": self.recovery_expires_at_ms,
        })
        self.clear_recovery_code()
        return True

    def clear_recovery_code(self) -> None:
        """Clear any active recovery code and persist the change."""
        self.recovery_code_hash = None
        self.recovery_issued_at_ms = None
        self.recovery_expires_at_ms = None
        self.persist()

    def snapshot(self) -> dict[str, Any]:
        """Return a redacted status view for audit and UI surfaces."""
        return {
            "enabled": bool(self.token),
            "token_fingerprint": _token_fingerprint(self.token) if self.token else None,
            "rotation_count": self.rotation_count,
            "last_rotated_at_ms": self.last_rotated_at_ms,
            "last_rotation_reason": self.last_rotation_reason,
            "recovery": self.recovery_metadata(),
            "source": "state-file" if self.config_path else "memory",
        }

    def recovery_metadata(self) -> dict[str, Any]:
        """Return current recovery-code state without revealing the code itself."""
        ttl_remaining_s = None
        if self.recovery_expires_at_ms:
            ttl_remaining_s = max(0, (self.recovery_expires_at_ms - _now_ms()) // 1000)
        active = bool(self.recovery_code_hash) and bool(self.recovery_expires_at_ms) and ttl_remaining_s is not None and ttl_remaining_s > 0
        return {
            "active": active,
            "issued_at_ms": self.recovery_issued_at_ms,
            "expires_at_ms": self.recovery_expires_at_ms if active else None,
            "ttl_remaining_s": ttl_remaining_s if active else None,
        }

    def _append_audit(self, event: dict[str, Any]) -> None:
        self.audit.append(event)
        self.audit = self.audit[-20:]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _random_token(size: int) -> str:
    return os.urandom(size).hex()


def _token_fingerprint(token: str | None) -> str | None:
    if not token:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def _hash_recovery_code(code: str) -> str:
    return hashlib.sha256(str(code).encode("utf-8")).hexdigest()


def _gateway_auth_state_path(config_path: Path | None) -> Path:
    if config_path is None:
        raise ValueError("config_path is required")
    return Path(config_path).with_suffix(_GATEWAY_AUTH_STATE_FILE)


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def verify_token(provided: str, expected: str) -> bool:
    """Timing-safe token comparison."""
    return hmac.compare_digest(provided.encode(), expected.encode())


def _compute_hmac(payload: str, key: str) -> str:
    return hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_session_cookie(auth_token: str) -> str:
    """Create a new session cookie value."""
    now = str(int(time.time()))
    nonce = os.urandom(16).hex()
    payload = f"{now}:{now}:{nonce}"
    sig = _compute_hmac(payload, auth_token)
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def verify_session_cookie(
    cookie: str, auth_token: str
) -> tuple[bool, str | None]:
    """Verify a session cookie.

    Returns (valid, refreshed_cookie_or_none).
    If valid, refreshed_cookie has updated last_ts.
    """
    try:
        raw = base64.urlsafe_b64decode(cookie.encode()).decode()

        parts = raw.split(":")
        if len(parts) != 4:
            return False, None

        created_ts, last_ts, nonce, sig = parts

        # Verify HMAC integrity
        payload = f"{created_ts}:{last_ts}:{nonce}"
        expected_sig = _compute_hmac(payload, auth_token)
        if not hmac.compare_digest(sig, expected_sig):
            return False, None

        now = int(time.time())

        # Check timestamp sanity
        created = int(created_ts)
        last = int(last_ts)
        if created > now + FUTURE_SKEW_TOLERANCE:
            return False, None
        if last > now + FUTURE_SKEW_TOLERANCE:
            return False, None
        if last < created:
            return False, None

        # Check absolute timeout
        if now - created > ABSOLUTE_TIMEOUT:
            return False, None

        # Check idle timeout
        if now - last > IDLE_TIMEOUT:
            return False, None

        # Refresh: update last_ts, keep created_ts and nonce
        new_last = str(now)
        new_payload = f"{created_ts}:{new_last}:{nonce}"
        new_sig = _compute_hmac(new_payload, auth_token)
        refreshed = base64.urlsafe_b64encode(
            f"{new_payload}:{new_sig}".encode()
        ).decode()

        return True, refreshed
    except Exception:
        return False, None
