"""Persistance en fichiers JSON : configuration, programmes, déclencheurs.

Disposition du dossier de données (`/var/lib/halloween/` sur le Pi) :

    config.json         composants, Home Assistant, état de repos (permissions 600 : jeton)
    triggers.json       déclencheurs
    programs/<id>.json  un fichier par programme

Les écritures sont atomiques (fichier temporaire dans le même dossier, `fsync`, puis `os.replace`) :
un arrêt brutal laisse l'ancienne version intacte. Les programmes portent une `revision`
incrémentée à chaque enregistrement ; un enregistrement fondé sur une révision périmée est refusé.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from halloween.config.models import AppConfig
from halloween.issues import Issue, issues_from_validation_error
from halloween.log import get_logger
from halloween.program.models import Program

log = get_logger("store")

SECRET_MODE = 0o600
DEFAULT_MODE = 0o644


class RevisionConflict(Exception):
    """Le programme a changé depuis la révision sur laquelle l'enregistrement s'appuie."""

    def __init__(self, program_id: str, expected: int | None, current: int | None) -> None:
        super().__init__(
            f"programme `{program_id}` : révision attendue {expected}, révision actuelle {current}"
        )
        self.program_id = program_id
        self.expected = expected
        self.current = current


@dataclass(frozen=True)
class LoadedPrograms:
    programs: dict[str, Program]
    issues: list[Issue]  # fichiers illisibles ou invalides (laissés intacts sur le disque)


def write_atomic(path: Path, text: str, mode: int = DEFAULT_MODE) -> None:
    """Écrit `text` dans `path` de façon atomique."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
    # Rend le renommage durable.
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _dump(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


class Store:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    @property
    def triggers_path(self) -> Path:
        return self.root / "triggers.json"

    @property
    def programs_dir(self) -> Path:
        return self.root / "programs"

    def program_path(self, program_id: str) -> Path:
        # `program_id` est un slug validé par le modèle : pas de séparateur de chemin possible.
        return self.programs_dir / f"{program_id}.json"

    def initialize(self) -> None:
        """Crée les dossiers et supprime les fichiers temporaires laissés par un arrêt brutal."""
        self.programs_dir.mkdir(parents=True, exist_ok=True)
        for directory in (self.root, self.programs_dir):
            for leftover in directory.glob(".*.tmp"):
                with contextlib.suppress(FileNotFoundError):
                    leftover.unlink()

    # ------------------------------------------------------------------ configuration

    def load_config(self) -> AppConfig:
        """Configuration enregistrée ; vide si le fichier n'existe pas encore."""
        if not self.config_path.exists():
            return AppConfig()
        return AppConfig.model_validate_json(self.config_path.read_text(encoding="utf-8"))

    def save_config(self, config: AppConfig) -> None:
        with self._lock:
            write_atomic(self.config_path, _dump(config.model_dump(mode="json")), SECRET_MODE)

    # ------------------------------------------------------------------ déclencheurs

    def load_triggers(self) -> list[dict[str, Any]]:
        if not self.triggers_path.exists():
            return []
        return json.loads(self.triggers_path.read_text(encoding="utf-8"))

    def save_triggers(self, triggers: list[dict[str, Any]]) -> None:
        with self._lock:
            write_atomic(self.triggers_path, _dump(triggers))

    # ------------------------------------------------------------------ programmes

    def get_program(self, program_id: str) -> Program | None:
        path = self.program_path(program_id)
        if not path.exists():
            return None
        return Program.model_validate_json(path.read_text(encoding="utf-8"))

    def _stored_revision(self, program_id: str) -> int | None:
        existing = self.get_program(program_id)
        return None if existing is None else existing.revision

    def save_program(self, program: Program, expected_revision: int | None = None) -> Program:
        """Enregistre `program` et retourne la version enregistrée (révision incrémentée).

        - nouveau programme : `expected_revision` doit être `None` (ou 0) et le fichier absent ;
        - programme existant : `expected_revision` doit égaler la révision enregistrée.
        La révision portée par `program` lui-même est ignorée : la source de vérité est le disque.
        """
        with self._lock:
            current = self._stored_revision(program.id)
            if current is None:
                if expected_revision not in (None, 0):
                    raise RevisionConflict(program.id, expected_revision, None)
            elif expected_revision != current:
                raise RevisionConflict(program.id, expected_revision, current)
            saved = program.model_copy(update={"revision": (current or 0) + 1})
            write_atomic(self.program_path(program.id), _dump(saved.to_json()))
            return saved

    def delete_program(self, program_id: str) -> bool:
        with self._lock:
            try:
                self.program_path(program_id).unlink()
            except FileNotFoundError:
                return False
            return True

    def load_programs(self) -> LoadedPrograms:
        """Tous les programmes ; un fichier invalide est signalé sans bloquer les autres."""
        programs: dict[str, Program] = {}
        issues: list[Issue] = []
        if not self.programs_dir.exists():
            return LoadedPrograms(programs, issues)
        for path in sorted(self._program_files()):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                program = Program.model_validate(raw)
            except json.JSONDecodeError as exc:
                issues.append(
                    Issue("error", "unreadable_file", f"{path.name} : JSON invalide ({exc})")
                )
                continue
            except ValidationError as exc:
                found = issues_from_validation_error(exc, raw)
                issues.extend(
                    Issue(i.severity, "invalid_file", f"{path.name} : {i.message}", i.node_id)
                    for i in found
                )
                continue
            if program.id != path.stem:
                issues.append(
                    Issue(
                        "error",
                        "id_mismatch",
                        f"{path.name} : l'id `{program.id}` ne correspond pas au nom du fichier",
                    )
                )
                continue
            programs[program.id] = program
        for issue in issues:
            log.error("programme illisible", extra={"detail": issue.message})
        return LoadedPrograms(programs, issues)

    def _program_files(self) -> Iterator[Path]:
        return (p for p in self.programs_dir.glob("*.json") if not p.name.startswith("."))
