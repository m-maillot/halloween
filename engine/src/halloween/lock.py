"""Verrouillage par code (spec 1 §6.4) : état persistant et empreinte du code.

Le code (4 à 8 chiffres) n'est jamais stocké en clair : seule l'empreinte `scrypt` salée l'est,
dans `lock.json` (permissions 600). Le fichier est relu à chaque accès : `halloween-cli unlock
--reset`, lancé sur le Pi pendant que le service tourne, est ainsi pris en compte aussitôt.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from halloween.store import SECRET_MODE, write_atomic

LOCK_FILE = "lock.json"
CODE_PATTERN = r"^\d{4,8}$"
_CODE = re.compile(CODE_PATTERN)

# Paramètres scrypt : ~50 ms sur un Pi 4, ce qui rend l'énumération des 10^4 à 10^8 codes coûteuse.
_N, _R, _P = 2**14, 8, 1
_SALT_BYTES = 16


class NoCode(Exception):
    """Aucun code n'a encore été défini."""


@dataclass(frozen=True)
class _Stored:
    locked: bool = False
    salt: bytes | None = None
    digest: bytes | None = None


def _hash(code: str, salt: bytes) -> bytes:
    return hashlib.scrypt(code.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)


class LockState:
    def __init__(self, path: Path) -> None:
        self._path = path

    @classmethod
    def in_dir(cls, root: Path) -> LockState:
        return cls(root / LOCK_FILE)

    # ------------------------------------------------------------------ fichier

    def _load(self) -> _Stored:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            code = raw.get("code") or {}
            salt, digest = code.get("salt"), code.get("hash")
            if not (salt and digest):
                return _Stored()  # sans code, pas de verrou possible
            return _Stored(bool(raw.get("locked")), bytes.fromhex(salt), bytes.fromhex(digest))
        except FileNotFoundError:
            return _Stored()
        except (ValueError, AttributeError, OSError):
            # Fichier illisible : on ne laisse pas la configuration ouverte par accident, mais
            # on ne bloque pas non plus définitivement : `unlock --reset` permet d'en sortir.
            return _Stored(locked=True, salt=b"", digest=b"")

    def _save(self, stored: _Stored) -> None:
        data = {
            "locked": stored.locked,
            "code": {
                "algo": "scrypt",
                "n": _N,
                "r": _R,
                "p": _P,
                "salt": stored.salt.hex(),
                "hash": stored.digest.hex(),
            }
            if stored.salt is not None and stored.digest is not None
            else None,
        }
        write_atomic(self._path, json.dumps(data, indent=2) + "\n", SECRET_MODE)

    # ------------------------------------------------------------------ état

    @property
    def locked(self) -> bool:
        return self._load().locked

    @property
    def has_code(self) -> bool:
        return self._load().digest is not None

    @staticmethod
    def valid_format(code: str) -> bool:
        return bool(_CODE.fullmatch(code))

    def verify(self, code: str) -> bool:
        """Compare à temps constant. Faux aussi quand aucun code n'existe."""
        stored = self._load()
        if stored.salt is None or stored.digest is None:
            return False
        return hmac.compare_digest(_hash(code, stored.salt), stored.digest)

    def set_code(self, code: str) -> None:
        """Définit ou remplace le code (l'état verrouillé / déverrouillé est conservé)."""
        if not self.valid_format(code):
            raise ValueError("le code doit comporter 4 à 8 chiffres")
        salt = os.urandom(_SALT_BYTES)
        self._save(_Stored(self._load().locked, salt, _hash(code, salt)))

    def lock(self) -> None:
        stored = self._load()
        if stored.digest is None:
            raise NoCode("aucun code défini : définir un code avant de verrouiller")
        self._save(_Stored(True, stored.salt, stored.digest))

    def unlock(self) -> None:
        stored = self._load()
        if stored.digest is not None:
            self._save(_Stored(False, stored.salt, stored.digest))

    def reset(self) -> None:
        """Supprime le code et déverrouille (code perdu : accès shell au Pi exigé par la CLI)."""
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass


MAX_FREE_ATTEMPTS = 5
BASE_DELAY_S = 30.0
MAX_DELAY_S = 900.0


class Throttle:
    """Délai croissant après trop de codes faux, commun à tous les endroits qui demandent le code.

    Les 5 premiers essais ratés n'entraînent rien ; ensuite chaque échec double l'attente
    (30 s, 1 min, 2 min… 15 min au plus). Pendant l'attente, aucun essai n'est examiné (et il ne
    compte pas). Un bon code remet le compteur à zéro. L'état est en mémoire : un redémarrage le
    remet à zéro, ce qui n'aide pas un attaquant réseau (il ne peut pas redémarrer le service).
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._failures = 0
        self._blocked_until = 0.0
        # Un seul essai examiné à la fois : des requêtes en parallèle ne contournent pas le compte.
        self.guard = asyncio.Lock()

    def retry_after(self) -> int:
        """Secondes à attendre avant le prochain essai (0 : libre)."""
        remaining = self._blocked_until - self.clock()
        return math.ceil(remaining) if remaining > 0 else 0

    def failure(self) -> None:
        self._failures += 1
        if self._failures >= MAX_FREE_ATTEMPTS:
            delay = min(BASE_DELAY_S * 2 ** (self._failures - MAX_FREE_ATTEMPTS), MAX_DELAY_S)
            self._blocked_until = self.clock() + delay

    def success(self) -> None:
        self._failures = 0
        self._blocked_until = 0.0
