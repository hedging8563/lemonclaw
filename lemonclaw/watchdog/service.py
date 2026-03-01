"""In-process watchdog — Layer 1 of the dual-layer self-healing architecture.

Layer 1 (this module): asyncio-based, runs inside the gateway process.
  - 4 health checks: HTTP self-check, session stuck, memory pressure, error rate
  - Soft recovery: clear stuck session
  - Hard recovery: os._exit(1) → K8s/launchd/systemd restarts the process
  - 10-minute cooldown prevents restart storms
  - Limitation: cannot detect event loop blocking (that's Layer 2's job)

Layer 2 (external): K8s liveness probe / launchd watchdog.sh / systemd timer.
  - Detects event loop blocking (Starlette can't respond → probe timeout)
  - Already implemented in Step 5 (K8s Dockerfile) and Step 6 (install.sh)
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger


# ============================================================================
# Configuration
# ============================================================================

DEFAULT_CHECK_INTERVAL = 60       # seconds between health checks
SESSION_STUCK_THRESHOLD = 120     # seconds: session with no progress
MEMORY_LIMIT_MB = 900             # soft limit before triggering action
COOLDOWN_SECONDS = 600            # 10 minutes between hard restarts
ERROR_RATE_WINDOW = 300           # 5-minute sliding window for error tracking
ERROR_RATE_THRESHOLD = 20         # errors in window before triggering action
ALARM_TIMEOUT = 150               # seconds: must be > CHECK_INTERVAL + tick duration


# ============================================================================
# Health check results
# ============================================================================


@dataclass
class HealthCheck:
    name: str
    healthy: bool
    detail: str = ""


@dataclass
class WatchdogState:
    """Tracks watchdog internal state."""

    last_check_time: float = 0.0
    last_hard_restart_time: float = 0.0
    consecutive_failures: int = 0
    total_checks: int = 0
    total_soft_recoveries: int = 0
    total_hard_restarts: int = 0
    recent_errors: list[float] = field(default_factory=list)  # timestamps


# ============================================================================
# WatchdogService
# ============================================================================


class WatchdogService:
    """In-process health monitor with soft/hard recovery.

    Usage:
        watchdog = WatchdogService(port=18789)
        await watchdog.start()
        # ... later ...
        watchdog.stop()
    """

    def __init__(
        self,
        port: int = 18789,
        check_interval: int = DEFAULT_CHECK_INTERVAL,
        memory_limit_mb: int = MEMORY_LIMIT_MB,
        session_manager: object | None = None,
    ) -> None:
        self._port = port
        self._interval = check_interval
        self._memory_limit_mb = memory_limit_mb
        self._session_manager = session_manager
        self._state = WatchdogState()
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def state(self) -> WatchdogState:
        return self._state

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the watchdog background loop."""
        if self._running:
            return
        self._running = True
        self._setup_alarm()
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"watchdog: started (interval={self._interval}s, memory_limit={self._memory_limit_mb}MB)")

    def stop(self) -> None:
        """Stop the watchdog."""
        self._running = False
        # Cancel alarm
        if hasattr(signal, "alarm"):
            signal.alarm(0)
        if self._task:
            self._task.cancel()
            self._task = None

    # ------------------------------------------------------------------
    # Event loop blocking detection (signal.alarm)
    # ------------------------------------------------------------------

    def _setup_alarm(self) -> None:
        """Set up SIGALRM-based event loop blocking detection (POSIX only).

        signal.alarm fires independently of the event loop. If the loop is
        blocked (e.g. a synchronous call hangs), the alarm will still fire
        and log a critical warning. Each _tick() resets the alarm, so it
        only fires if the loop is stuck for > ALARM_TIMEOUT seconds.
        """
        if not hasattr(signal, "alarm"):
            return  # Windows: no signal.alarm

        def _on_alarm(signum, frame):
            logger.critical(
                f"watchdog: SIGALRM — event loop blocked for >{ALARM_TIMEOUT}s! "
                "This indicates a synchronous call is blocking the asyncio loop."
            )
            # Don't exit here — just log. The external watchdog (Layer 2)
            # will handle restart if /health stops responding.

        signal.signal(signal.SIGALRM, _on_alarm)
        signal.alarm(ALARM_TIMEOUT)

    def _reset_alarm(self) -> None:
        """Reset the alarm timer (called each tick to prove the loop is alive)."""
        if hasattr(signal, "alarm"):
            signal.alarm(ALARM_TIMEOUT)

    # ------------------------------------------------------------------
    # Error tracking (called externally by loguru sink)
    # ------------------------------------------------------------------

    def record_error(self) -> None:
        """Record an error event for rate tracking."""
        self._state.recent_errors.append(time.monotonic())
        self._trim_errors()

    def _trim_errors(self) -> None:
        """Remove error timestamps outside the sliding window."""
        cutoff = time.monotonic() - ERROR_RATE_WINDOW
        self._state.recent_errors = [t for t in self._state.recent_errors if t > cutoff]

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Background loop: sleep → check → recover if needed."""
        # Wait a bit before first check to let the gateway fully start
        await asyncio.sleep(30)

        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"watchdog: tick error: {e}")

            self._reset_alarm()  # Reset before sleep so alarm doesn't fire during interval
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                break

    async def _tick(self) -> None:
        """Run all health checks and take recovery action if needed."""
        self._reset_alarm()  # Prove the event loop is alive
        self._state.total_checks += 1
        self._state.last_check_time = time.monotonic()

        checks = await self._run_checks()
        unhealthy = [c for c in checks if not c.healthy]

        if not unhealthy:
            self._state.consecutive_failures = 0
            return

        # Log unhealthy checks
        for c in unhealthy:
            logger.warning(f"watchdog: UNHEALTHY [{c.name}] {c.detail}")

        self._state.consecutive_failures += 1

        # Decide recovery action
        if self._state.consecutive_failures >= 3:
            await self._hard_recovery(unhealthy)
        else:
            await self._soft_recovery(unhealthy)

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    async def _run_checks(self) -> list[HealthCheck]:
        """Run all 4 health checks."""
        results: list[HealthCheck] = []

        # 1. HTTP self-check
        results.append(await self._check_http())

        # 2. Session stuck detection
        results.append(self._check_session_stuck())

        # 3. Memory pressure
        results.append(self._check_memory())

        # 4. Error rate
        results.append(self._check_error_rate())

        return results

    async def _check_http(self) -> HealthCheck:
        """Check that our own /health endpoint responds."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"http://127.0.0.1:{self._port}/health")
                if resp.status_code == 200:
                    return HealthCheck("http", True)
                return HealthCheck("http", False, f"status={resp.status_code}")
        except Exception as e:
            return HealthCheck("http", False, str(e))

    def _check_session_stuck(self) -> HealthCheck:
        """Detect sessions that haven't progressed."""
        if self._session_manager is None:
            return HealthCheck("session_stuck", True, "no session manager")

        try:
            sessions = self._session_manager.list_sessions()
            now = time.time()
            stuck_count = 0

            for info in sessions:
                updated_at = info.get("updated_at", 0)
                is_active = info.get("active", False)
                if is_active and updated_at and (now - updated_at) > SESSION_STUCK_THRESHOLD:
                    stuck_count += 1

            if stuck_count > 0:
                return HealthCheck("session_stuck", False, f"{stuck_count} stuck session(s)")
            return HealthCheck("session_stuck", True)
        except Exception as e:
            return HealthCheck("session_stuck", True, f"check error: {e}")

    def _check_memory(self) -> HealthCheck:
        """Check process RSS memory usage."""
        try:
            rss_mb = _get_rss_mb()
            if rss_mb is None:
                return HealthCheck("memory", True, "cannot read RSS")
            if rss_mb > self._memory_limit_mb:
                return HealthCheck("memory", False, f"RSS={rss_mb:.0f}MB > limit={self._memory_limit_mb}MB")
            return HealthCheck("memory", True, f"RSS={rss_mb:.0f}MB")
        except Exception as e:
            return HealthCheck("memory", True, f"check error: {e}")

    def _check_error_rate(self) -> HealthCheck:
        """Check error rate in the sliding window."""
        self._trim_errors()
        count = len(self._state.recent_errors)
        if count >= ERROR_RATE_THRESHOLD:
            return HealthCheck("error_rate", False, f"{count} errors in {ERROR_RATE_WINDOW}s")
        return HealthCheck("error_rate", True, f"{count} errors in window")

    # ------------------------------------------------------------------
    # Recovery actions
    # ------------------------------------------------------------------

    async def _soft_recovery(self, checks: list[HealthCheck]) -> None:
        """Soft recovery: clear stuck sessions, log warning."""
        self._state.total_soft_recoveries += 1
        names = ", ".join(c.name for c in checks)
        logger.warning(f"watchdog: soft recovery triggered ({names})")

        # Clear stuck sessions if that's the issue
        for c in checks:
            if c.name == "session_stuck" and self._session_manager is not None:
                try:
                    sessions = self._session_manager.list_sessions()
                    now = time.time()
                    for info in sessions:
                        updated_at = info.get("updated_at", 0)
                        is_active = info.get("active", False)
                        key = info.get("key", "")
                        if is_active and updated_at and (now - updated_at) > SESSION_STUCK_THRESHOLD:
                            logger.warning(f"watchdog: clearing stuck session {key}")
                            # Invalidate from cache to force reload on next access
                            self._session_manager.invalidate(key)
                except Exception as e:
                    logger.error(f"watchdog: soft recovery error: {e}")

    async def _hard_recovery(self, checks: list[HealthCheck]) -> None:
        """Hard recovery: exit process (K8s/launchd/systemd will restart).

        Respects 10-minute cooldown to prevent restart storms.
        Flushes all cached sessions before sending SIGTERM to minimize data loss.
        """
        now = time.monotonic()
        elapsed = now - self._state.last_hard_restart_time

        if self._state.last_hard_restart_time > 0 and elapsed < COOLDOWN_SECONDS:
            remaining = COOLDOWN_SECONDS - elapsed
            logger.warning(f"watchdog: hard restart in cooldown ({remaining:.0f}s remaining)")
            return

        self._state.total_hard_restarts += 1
        self._state.last_hard_restart_time = now
        names = ", ".join(c.name for c in checks)
        logger.critical(f"watchdog: HARD RESTART — {self._state.consecutive_failures} consecutive failures ({names})")

        # Flush all cached sessions to disk before killing the process
        if self._session_manager is not None:
            try:
                for key, session in list(getattr(self._session_manager, '_cache', {}).items()):
                    try:
                        self._session_manager.save(session)
                    except Exception:
                        logger.error(f"watchdog: failed to flush session {key}")
                logger.info("watchdog: flushed cached sessions before restart")
            except Exception as e:
                logger.error(f"watchdog: session flush failed: {e}")

        # Give a brief moment for logs to flush
        await asyncio.sleep(1)

        # Send SIGTERM to self first for graceful shutdown attempt
        os.kill(os.getpid(), signal.SIGTERM)

        # If still alive after 15s, force exit
        await asyncio.sleep(15)
        logger.critical("watchdog: SIGTERM did not terminate, forcing os._exit(1)")
        os._exit(1)


# ============================================================================
# Helpers
# ============================================================================


def _get_rss_mb() -> float | None:
    """Get current process RSS in MB. Uses /proc on Linux, resource on macOS."""
    try:
        import resource
        # getrusage returns max RSS in KB on Linux, bytes on macOS
        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss = usage.ru_maxrss
        import sys
        if sys.platform == "darwin":
            return rss / (1024 * 1024)  # bytes → MB
        else:
            return rss / 1024  # KB → MB
    except Exception:
        pass

    # Fallback: read /proc/self/status
    try:
        status = Path("/proc/self/status").read_text()
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                kb = int(line.split()[1])
                return kb / 1024
    except Exception:
        pass

    return None


def create_loguru_error_sink(watchdog: WatchdogService):
    """Create a loguru sink that feeds error events to the watchdog.

    Usage:
        logger.add(create_loguru_error_sink(watchdog), level="ERROR")
    """
    def sink(message):
        watchdog.record_error()
    return sink
