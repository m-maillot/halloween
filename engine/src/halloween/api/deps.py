"""Dépendances FastAPI partagées par les routeurs."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from halloween.app import Engine


def get_engine(request: Request) -> Engine:
    return request.app.state.engine


EngineDep = Annotated[Engine, Depends(get_engine)]
