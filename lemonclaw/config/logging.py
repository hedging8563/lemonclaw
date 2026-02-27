"""Loguru logging configuration for LemonClaw.

Output target is controlled by LOG_TARGET env var:
- "stdout" (default for K8s): logs to stdout/stderr, kubectl logs compatible
- "file" (default for self-hosted): logs to ~/.lemonclaw/lemonclaw.log + .err

Usage:
    from lemonclaw.config.logging import setup_logging
    setup_logging()  # Call once at startup
"""

import os
import sys
from pathlib import Path

from loguru import logger


def setup_logging(log_dir: Path | None = None) -> None:
    """Configure loguru based on LOG_TARGET environment variable.

    Args:
        log_dir: Override log directory (default: ~/.lemonclaw/)
    """
    # Remove default loguru handler
    logger.remove()

    target = os.environ.get("LOG_TARGET", "stdout").lower()
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    if target == "file":
        base = log_dir or (Path.home() / ".lemonclaw")
        base.mkdir(parents=True, exist_ok=True)

        # INFO+ → lemonclaw.log
        logger.add(
            base / "lemonclaw.log",
            level=level,
            format=fmt,
            rotation="10 MB",
            retention="7 days",
            compression="gz",
            encoding="utf-8",
        )
        # ERROR+ → lemonclaw.err (separate file for quick triage)
        logger.add(
            base / "lemonclaw.err",
            level="ERROR",
            format=fmt,
            rotation="5 MB",
            retention="7 days",
            compression="gz",
            encoding="utf-8",
        )
    else:
        # stdout: all levels (K8s kubectl logs)
        logger.add(
            sys.stderr,
            level=level,
            format=fmt,
            colorize=True,
        )
