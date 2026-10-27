"""Journalisation structurée (JSON lines).

Chaque ligne est un objet JSON. Les champs de contexte `run_id`, `script_id` et `node_id`
sont ajoutés automatiquement quand ils sont définis par `log_context`, y compris dans les
tâches asyncio lancées depuis ce contexte, ce qui permet de filtrer le journal par run.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from types import MappingProxyType
from typing import IO, Any

ROOT_LOGGER = "halloween"

_context: ContextVar[Mapping[str, Any]] = ContextVar(
    "halloween_log_context", default=MappingProxyType({})
)

# Attributs standard d'un LogRecord : tout autre attribut est un champ « extra » à journaliser.
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """Ajoute des champs (ex. `run_id`, `node_id`) à toutes les lignes émises dans ce bloc."""
    token = _context.set({**_context.get(), **fields})
    try:
        yield
    finally:
        _context.reset(token)


def current_context() -> Mapping[str, Any]:
    """Champs de contexte actifs (`run_id`, `script_id`, `node_id`)."""
    return _context.get()


def get_logger(name: str) -> logging.Logger:
    """Retourne un logger enfant de `halloween`."""
    return logging.getLogger(f"{ROOT_LOGGER}.{name}")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Les champs de base ne sont jamais écrasés par le contexte ou les `extra`.
        for key, value in _context.get().items():
            entry.setdefault(key, value)
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                entry.setdefault(key, value)
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging(level: str | int = "INFO", stream: IO[str] | None = None) -> logging.Logger:
    """Configure le logger `halloween` (une ligne JSON par événement). Idempotent."""
    logger = logging.getLogger(ROOT_LOGGER)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger
