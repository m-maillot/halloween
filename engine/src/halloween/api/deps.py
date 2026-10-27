"""Dépendances FastAPI partagées par les routeurs."""

from __future__ import annotations

import asyncio
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
