"""Logging setup: console (containers) + rotating files under ./logs (host persistence)."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from config import settings

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def setup_logging(service: str) -> logging.Logger:
    """Idempotent root logging config; one file per service name."""
    root = logging.getLogger()
    if root.handlers:
        return logging.getLogger(service)

    root.setLevel(settings.log_level.upper())
    formatter = logging.Formatter(_FORMAT)

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    settings.log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        settings.log_dir / f"{service}.log", maxBytes=5_000_000, backupCount=3
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    return logging.getLogger(service)
