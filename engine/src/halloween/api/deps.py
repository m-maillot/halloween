"""Dépendances FastAPI partagées par les routeurs."""

from __future__ import annotations

import asyncio
import re
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from halloween.app import Engine

READY_TIMEOUT_S = 5.0


async def get_engine(request: Request) -> Engine:
    """Le moteur, une fois prêt (il ne l'est pas pendant une reconfiguration à chaud)."""
    engine: Engine = request.app.state.engine
    try:
        await asyncio.wait_for(engine.ready.wait(), READY_TIMEOUT_S)
    except TimeoutError:
        raise HTTPException(503, "le moteur redémarre, réessayer dans un instant") from None
    return engine


EngineDep = Annotated[Engine, Depends(get_engine)]


# Écritures permises même verrouillé (spec 1 §6.4). Tout le reste, hors lecture, est refusé : la
# liste des exceptions est courte et explicite, une route ajoutée plus tard est donc protégée
# d'office. `POST /runs` vérifie le code lui-même ; `validate` et `simulate` ne modifient rien.
# On compare l'URL réelle (et non la route trouvée par FastAPI, dont la forme change selon la
# version quand les routeurs sont imbriqués).
LOCK_EXEMPT = re.compile(
    r"^/api/(runs|runs/stop|runs/[^/]+/stop|lock|unlock|simulate|programs/validate)$"
)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def is_lock_exempt(method: str, path: str) -> bool:
    return method in SAFE_METHODS or (
        method == "POST" and bool(LOCK_EXEMPT.match(path.rstrip("/")))
    )


async def enforce_lock(request: Request) -> None:
    """Refuse (`423`) toute écriture tant que le moteur est verrouillé, quel que soit le jeton."""
    if is_lock_exempt(request.method, request.url.path):
        return
    engine: Engine = request.app.state.engine
    if engine.lock.locked:
        raise HTTPException(
            423,
            detail={
                "message": "verrouillé : déverrouiller avec le code pour modifier",
                "issues": [],
            },
        )
