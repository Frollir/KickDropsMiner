from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from constants import FILE_FORMATTER, VERBOSE_LOG_PATH


_handler: RotatingFileHandler | None = None


def configure_verbose_logging(
    enabled: bool,
    *,
    logging_level: int,
    api_level: int,
    websocket_level: int,
) -> Path | None:
    global _handler

    logger = logging.getLogger("KickDrops")
    api_logger = logging.getLogger("KickDrops.api")
    websocket_logger = logging.getLogger("KickDrops.websocket")

    if enabled:
        VERBOSE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if _handler is None:
            _handler = RotatingFileHandler(
                VERBOSE_LOG_PATH,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf8",
            )
            _handler.setLevel(logging.DEBUG)
            _handler.setFormatter(FILE_FORMATTER)
            logger.addHandler(_handler)
        logger.setLevel(logging.DEBUG)
        api_logger.setLevel(logging.DEBUG)
        websocket_logger.setLevel(logging.DEBUG)
        logger.info("Verbose diagnostic logging enabled: %s", VERBOSE_LOG_PATH)
        return VERBOSE_LOG_PATH

    if _handler is not None:
        logger.removeHandler(_handler)
        _handler.close()
        _handler = None
    logger.setLevel(logging_level)
    api_logger.setLevel(api_level)
    websocket_logger.setLevel(websocket_level)
    return None
