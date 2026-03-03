"""Config file watcher for hot-reloading credentials."""

import asyncio
import os
from pathlib import Path

from loguru import logger


class ConfigWatcher:
    """Watch config.json for changes and hot-reload provider credentials.

    Only reloads API keys and api_base — does not restart channels or MCP servers.
    """

    def __init__(self, config_path: Path, provider, *, interval: float = 10.0):
        self._path = config_path
        self._provider = provider
        self._interval = interval
        self._last_mtime: float = 0.0
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._last_mtime = self._get_mtime()
        self._task = asyncio.create_task(self._watch_loop())
        logger.info("Config watcher started (interval={}s)", self._interval)

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    def _get_mtime(self) -> float:
        try:
            return os.path.getmtime(self._path)
        except OSError:
            return 0.0

    async def _watch_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._interval)
                mtime = self._get_mtime()
                if mtime > self._last_mtime:
                    self._last_mtime = mtime
                    self._reload()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Config watcher error")

    def _reload(self) -> None:
        from lemonclaw.config.loader import load_config

        try:
            config = load_config(self._path)
            p = config.providers.get_provider_config(config.agents.defaults.model)
            api_key = p.api_key if p else None
            api_base = config.get_api_base(config.agents.defaults.model)

            if api_key and api_key != self._provider.api_key:
                self._provider.update_credentials(api_key, api_base)
                logger.info("Config watcher: API key hot-reloaded")
            elif api_base and api_base != self._provider.api_base:
                self._provider.update_credentials(self._provider.api_key, api_base)
                logger.info("Config watcher: API base hot-reloaded")
        except Exception:
            logger.exception("Config watcher: failed to reload")
