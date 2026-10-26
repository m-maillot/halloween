"""Boucle d'événements à temps virtuel.

Sur cette boucle, `asyncio.sleep(3600)` se termine instantanément et `loop.time()` avance de 3600 :
l'interpréteur s'exécute sans attendre, ce qui sert aux tests et à la simulation d'un scénario
(timeline des commandes). Si plus rien ne peut se produire (tâches bloquées sans minuteur),
`SimulationDeadlock` est levée au lieu de bloquer indéfiniment.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


class SimulationDeadlock(RuntimeError):
    """Toutes les tâches attendent un événement qui ne viendra pas (ex. un bouton)."""


class _VirtualSelector:
    def __init__(self, selector: Any, loop: VirtualEventLoop) -> None:
        self._selector = selector
        self._loop = loop

    def select(self, timeout: float | None = None) -> list:
        events = self._selector.select(0)
        if events:
            return events
        if timeout is None:
            raise SimulationDeadlock(
                "plus rien ne peut se produire : tâches en attente sans minuteur"
            )
        if timeout > 0:
            self._loop._now += timeout
        return events

    def __getattr__(self, name: str) -> Any:
        return getattr(self._selector, name)


class VirtualEventLoop(asyncio.SelectorEventLoop):
    def __init__(self) -> None:
        super().__init__()
        self._now = 0.0
        self._selector = _VirtualSelector(self._selector, self)

    def time(self) -> float:
        return self._now


def run_virtual(main: Callable[[], Awaitable[T]]) -> T:
    """Exécute `main()` sur une boucle à temps virtuel et retourne son résultat."""
    with asyncio.Runner(loop_factory=VirtualEventLoop) as runner:

        async def wrapper() -> T:
            return await main()

        return runner.run(wrapper())
