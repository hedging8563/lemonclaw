"""CloudConnector stub — LemonData cloud integration interface.

The actual implementation lives in the private `lemonclaw-cloud` package.
When not installed, LemonClaw runs in standalone mode with full functionality.
Cloud features (smart routing, billing sync, remote config) require the package.

Version compatibility:
- lemonclaw bumps CLOUD_API_VERSION when the interface changes
- Incompatible lemonclaw-cloud versions auto-degrade to standalone mode
"""

from loguru import logger

CLOUD_API_VERSION = 1  # Bump when CloudConnector interface changes

try:
    from lemonclaw_cloud import CloudConnector, CLOUD_VERSION  # type: ignore[import-not-found]

    if CLOUD_VERSION != CLOUD_API_VERSION:
        logger.warning(
            f"lemonclaw-cloud v{CLOUD_VERSION} 与 lemonclaw 期望的 v{CLOUD_API_VERSION} 不兼容，"
            "降级为无云端模式"
        )
        CloudConnector = None  # type: ignore[assignment,misc]
except ImportError:
    CloudConnector = None  # type: ignore[assignment,misc]

__all__ = ["CloudConnector", "CLOUD_API_VERSION"]
