# utils/env_config.py
"""Tolerant readers for numeric environment settings.

Tuning values are read at module import time, so a plain ``int(os.getenv(...))``
turns a typo in ``.env`` into a worker that cannot start at all - the whole
platform down because a cache size was misspelled. These helpers fall back to
the default and log instead.
"""

import os

from utils.logging import get_logger

logger = get_logger(__name__)


def env_int(name: str, default: int, minimum: int | None = None) -> int:
    """Read an integer setting, falling back to ``default`` if unusable."""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        value = default
    else:
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            logger.warning(f"{name}={raw!r} is not an integer; using {default}")
            value = default
    if minimum is not None and value < minimum:
        logger.warning(f"{name}={value} is below the minimum {minimum}; using {minimum}")
        value = minimum
    return value


def env_float(name: str, default: float, minimum: float | None = None) -> float:
    """Read a float setting, falling back to ``default`` if unusable."""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        value = default
    else:
        try:
            value = float(str(raw).strip())
        except (TypeError, ValueError):
            logger.warning(f"{name}={raw!r} is not a number; using {default}")
            value = default
    if minimum is not None and value < minimum:
        logger.warning(f"{name}={value} is below the minimum {minimum}; using {minimum}")
        value = minimum
    return value
