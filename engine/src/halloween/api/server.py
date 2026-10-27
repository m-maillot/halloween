"""Lancement du serveur HTTP (uvicorn) dans la boucle d'événements courante."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator

import uvicorn
from fastapi import FastAPI


class _Server(uvicorn.Server):
    async def serve(self, sockets=None) -> None:
        try:
            await super().serve(sockets)
        except SystemExit:
            # uvicorn quitte ainsi quand le démarrage de l'application échoue (déjà journalisé) ;
            # intercepté ici, sinon la sortie traverserait toute la boucle d'événements.
            return

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        # Les signaux (Ctrl+C, SIGTERM) sont gérés par la commande qui nous lance.
        yield


async def run_server(app: FastAPI, host: str, port: int) -> None:
    """Sert l'application jusqu'à l'annulation de la tâche, puis arrête proprement le serveur."""
    server = _Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    task = asyncio.ensure_future(server.serve())
    try:
        # `shield` : annuler cette coroutine ne doit pas interrompre brutalement uvicorn.
        await asyncio.shield(task)
    except asyncio.CancelledError:
        server.should_exit = True  # arrêt gracieux : le moteur s'arrête avec le lifespan
        await task
        raise
