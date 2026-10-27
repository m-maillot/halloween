"""Authentification de l'API par jeton statique (`Authorization: Bearer <jeton>`).

Le jeton vient de `HALLOWEEN_API_TOKEN` ou, à défaut, du fichier `api-token` du dossier de données,
créé au premier démarrage (permissions 600). Réseau local uniquement : ce jeton protège contre un
appareil quelconque du réseau, pas contre un attaquant sur Internet (ne pas exposer le port).
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Mapping
from pathlib import Path

from fastapi import HTTPException, Request, WebSocket, status

from halloween.store import SECRET_MODE, write_atomic

TOKEN_ENV = "HALLOWEEN_API_TOKEN"
TOKEN_FILE = "api-token"
MIN_TOKEN_LENGTH = 16


def load_or_create_token(data_dir: Path, env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """Retourne `(jeton, origine)` ; crée le fichier `api-token` s'il n'existe pas."""
    value = (os.environ if env is None else env).get(TOKEN_ENV, "").strip()
    if value:
        if len(value) < MIN_TOKEN_LENGTH:
            raise ValueError(f"{TOKEN_ENV} trop court (au moins {MIN_TOKEN_LENGTH} caractères)")
        return value, f"variable {TOKEN_ENV}"
    path = data_dir / TOKEN_FILE
    if path.exists():
        stored = path.read_text(encoding="utf-8").strip()
        if len(stored) >= MIN_TOKEN_LENGTH:
            return stored, str(path)
    token = secrets.token_urlsafe(32)
    write_atomic(path, token + "\n", SECRET_MODE)
    return token, f"{path} (créé)"


def bearer(header: str | None) -> str | None:
    if header and header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def make_dependencies(expected: str) -> tuple[Callable, Callable]:
    """Dépendances FastAPI : une pour les routes HTTP, une pour le WebSocket."""

    def valid(candidate: str | None) -> bool:
        return candidate is not None and secrets.compare_digest(candidate, expected)

    async def require_token(request: Request) -> None:
        if not valid(bearer(request.headers.get("Authorization"))):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                detail="jeton d'API manquant ou invalide",
                headers={"WWW-Authenticate": "Bearer"},
            )

    async def require_ws_token(websocket: WebSocket) -> None:
        # Un navigateur ne peut pas poser d'en-tête sur un WebSocket : le jeton passe en paramètre.
        candidate = websocket.query_params.get("token") or bearer(
            websocket.headers.get("Authorization")
        )
        if not valid(candidate):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="jeton invalide")

    return require_token, require_ws_token
