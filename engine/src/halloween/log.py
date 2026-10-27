"""Journalisation structurée (JSON lines).

Chaque ligne est un objet JSON. Les champs de contexte `run_id`, `script_id` et `node_id`
sont ajoutés automatiquement quand ils sont définis par `log_context`, y compris dans les
tâches asyncio lancées depuis ce contexte, ce qui permet de filtrer le journal par run.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from collections import deque
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
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


LOG_MAX_BYTES = 2_000_000
LOG_BACKUPS = 5  # au plus (1 + 5) × 2 Mo = 12 Mo sur la carte SD


def setup_logging(
    level: str | int = "INFO",
    stream: IO[str] | None = None,
    log_file: Path | None = None,
) -> logging.Logger:
    """Configure le logger `halloween` (une ligne JSON par événement). Idempotent.

    `level` règle la sortie `stream`. Avec `log_file`, le journal complet (INFO et plus) est aussi
    écrit dans ce fichier, en rotation (`LOG_MAX_BYTES`, `LOG_BACKUPS` archives `.1`, `.2`…).
    Le logger laisse toujours passer les avertissements : `/status` les affiche.
    """
    logger = logging.getLogger(ROOT_LOGGER)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    stream_level = logging.getLevelName(level) if isinstance(level, str) else level
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler.setLevel(stream_level)
    logger.addHandler(handler)
    floor = logging.INFO if log_file is not None else logging.WARNING
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        rotating = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
        )
        rotating.setFormatter(JsonFormatter())
        rotating.setLevel(logging.INFO)
        logger.addHandler(rotating)
    logger.setLevel(min(stream_level, floor))
    logger.propagate = False
    return logger


class ProblemLog(logging.Handler):
    """Garde en mémoire les derniers avertissements et erreurs, pour `/status`."""

    def __init__(self, capacity: int = 50) -> None:
        super().__init__(level=logging.WARNING)
        self._entries: deque[dict[str, Any]] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        entry: dict[str, Any] = {
            "ts": record.created,
            "level": record.levelname,
            "source": record.name.removeprefix(ROOT_LOGGER + "."),
            "message": record.getMessage(),
        }
        for key in ("run_id", "node_id", "component_id"):
            value = _context.get().get(key, record.__dict__.get(key))
            if value is not None:
                entry[key] = value
        self._entries.append(entry)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Les plus récents d'abord."""
        return list(self._entries)[::-1][:limit]
