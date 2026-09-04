"""Consistent structured logging for agent-frameworks.

All modules use this to produce uniform, prefixed log output.

Usage:
    from common.logging import setup_logging, get_logger

    # At app startup (once):
    setup_logging(level="INFO")

    # In any module:
    logger = get_logger("governance")
    logger.info("Collecting evidence...")
"""

import logging
import sys
from typing import Optional

# Module-level cache: module_name -> logger
_loggers: dict = {}
_root_logger: Optional[logging.Logger] = None

# Format: [HH:MM:SS] [LEVEL  ] [module] message
_FORMAT = "%(asctime)s [%(levelname)-7s] [%(module)s] %(message)s"
_DATE_FORMAT = "%H:%M:%S"


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure the root agent-fw logger. Call once at startup.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).

    Returns:
        The root agent-fw logger.
    """
    global _root_logger

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Create or get the root agent-fw logger
    _root_logger = logging.getLogger("agent-fw")
    _root_logger.setLevel(numeric_level)

    # Avoid duplicate handlers on repeated calls
    if not _root_logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(numeric_level)
        formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)
        handler.setFormatter(formatter)
        _root_logger.addHandler(handler)

    # Prevent propagation to root logger (avoids double output)
    _root_logger.propagate = False

    return _root_logger


def get_logger(module: Optional[str] = None) -> logging.Logger:
    """Get a module-prefixed logger.

    Args:
        module: Module name (e.g., "governance", "pattern-memory").
                If None, returns the root agent-fw logger.

    Returns:
        A logger named "agent-fw.<module>" (or "agent-fw" if module is None).
    """
    global _root_logger

    # Ensure root logger exists
    if _root_logger is None:
        setup_logging()

    if module is None:
        return _root_logger

    # Cache loggers by module name
    if module not in _loggers:
        _loggers[module] = logging.getLogger(f"agent-fw.{module}")
        # Inherit level from root
        _loggers[module].setLevel(_root_logger.level)

    return _loggers[module]
