"""Boucle d'événements à temps virtuel.

Sur cette boucle, `asyncio.sleep(3600)` se termine instantanément et `loop.time()` avance de 3600 :
l'interpréteur s'exécute sans attendre, ce qui sert aux tests et à la simulation d'un scénario
(timeline des commandes). Si plus rien ne peut se produire (tâches bloquées sans minuteur),
`SimulationDeadlock` est levée au lieu de bloquer indéfiniment ; `SimulationHorizon` signale que
la limite de temps virtuel est atteinte.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


class SimulationDeadlock(RuntimeError):
    """Toutes les tâches attendent un événement qui ne viendra pas (ex. un bouton)."""


class SimulationHorizon(RuntimeError):
    """Le temps virtuel a atteint la limite fixée (ex. boucle infinie)."""


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
        loop = self._loop
        if loop.horizon_s is not None and loop._now + timeout > loop.horizon_s:
            loop._now = loop.horizon_s
            raise SimulationHorizon(f"limite de {loop.horizon_s:g} s de temps virtuel atteinte")
        if timeout > 0:
            loop._now += timeout
        return events

    def __getattr__(self, name: str) -> Any:
        return getattr(self._selector, name)


class VirtualEventLoop(asyncio.SelectorEventLoop):
    def __init__(self, horizon_s: float | None = None) -> None:
        super().__init__()
        self._now = 0.0
        self.horizon_s = horizon_s
        self._selector = _VirtualSelector(self._selector, self)

    def time(self) -> float:
        return self._now


def run_virtual(main: Callable[[], Awaitable[T]], horizon_s: float | None = None) -> T:
    """Exécute `main()` sur une boucle à temps virtuel et retourne son résultat.

    `horizon_s` : limite de temps virtuel ; la dépasser lève `SimulationHorizon`.
    """
    with asyncio.Runner(loop_factory=lambda: VirtualEventLoop(horizon_s)) as runner:

        async def wrapper() -> T:
            return await main()

        return runner.run(wrapper())
