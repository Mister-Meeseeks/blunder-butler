"""Structured logging to stderr."""

from __future__ import annotations

import logging
import sys


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure and return the blunder-butler logger."""
    logger = logging.getLogger("blunder_butler")
    if logger.handlers:
        return logger

    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(level)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    """Get the blunder-butler logger (must call setup_logging first)."""
    return logging.getLogger("blunder_butler")
