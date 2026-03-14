from __future__ import annotations

import threading
import time
from collections import OrderedDict


class InboundDedupeCache:
    """Thread-safe TTL cache for suppressing duplicate inbound events.

    Safe to call from both asyncio tasks and callback threads.
    The critical section is intentionally tiny: pure in-memory bookkeeping only.
    """

    def __init__(self, *, ttl_seconds: int = 300, max_entries: int = 2000) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._entries: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()

    def remember(self, key: str) -> bool:
        """Return True if this key is new within the TTL window, else False."""
        if not key:
            # Empty identifiers cannot be deduped safely; callers should prefer
            # namespaced non-empty keys (for example "telegram:update:123").
            return True

        now = time.monotonic()
        cutoff = now - self._ttl_seconds

        with self._lock:
            while self._entries:
                oldest_key, oldest_seen = next(iter(self._entries.items()))
                if oldest_seen >= cutoff:
                    break
                self._entries.pop(oldest_key, None)

            seen_at = self._entries.get(key)
            if seen_at is not None and seen_at >= cutoff:
                return False

            self._entries[key] = now
            self._entries.move_to_end(key)

            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

        return True
