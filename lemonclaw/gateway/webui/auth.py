"""Stateless HMAC cookie authentication for WebUI.

Cookie format: base64(created_ts:last_ts:nonce:hmac_sha256)
- created_ts: absolute session start (epoch seconds)
- last_ts: last activity timestamp (epoch seconds)
- nonce: random 16-byte hex to prevent replay
- hmac: SHA-256 HMAC of "created_ts:last_ts:nonce" keyed by auth_token

Timeouts:
- Idle: 4 hours (no activity → re-login)
- Absolute: 7 days (hard session limit)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

IDLE_TIMEOUT = 4 * 60 * 60  # 4 hours
ABSOLUTE_TIMEOUT = 7 * 24 * 60 * 60  # 7 days
COOKIE_NAME = "lc_session"


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

        # Check absolute timeout
        created = int(created_ts)
        if now - created > ABSOLUTE_TIMEOUT:
            return False, None

        # Check idle timeout
        last = int(last_ts)
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
