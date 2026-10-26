"""Évaluation des conditions (`if`, `wait_until`) : bouton, état d'un relais, tirage aléatoire."""

from __future__ import annotations

import asyncio
import random

from halloween.drivers.base import ButtonDriver, ButtonEvent, RelayDriver
from halloween.program.models import ButtonCondition, Condition, RandomCondition, RelayIsCondition

POLL_INTERVAL_S = 0.05


class Conditions:
    """Conditions d'un run. S'abonne aux boutons à la création ; appeler `close()` à la fin.

    - `button` dans un `if` : vrai si l'événement s'est produit **depuis le début du run**.
    - `button` dans un `wait_until` : attend l'événement **suivant**.
    - `relay_is` : état logique commandé du relais.
    - `random` : vrai avec la probabilité donnée, tirée à chaque évaluation.
    """

    def __init__(
        self,
        relays: RelayDriver,
        buttons: ButtonDriver,
        rng: random.Random | None = None,
        poll_interval_s: float = POLL_INTERVAL_S,
    ) -> None:
        self._relays = relays
        self._rng = rng or random.Random()
        self._poll = poll_interval_s
        self._seen: set[tuple[str, str]] = set()
        self._waiters: list[tuple[ButtonCondition, asyncio.Future[None]]] = []
        self._unsubscribe = buttons.subscribe(self._on_button)

    def close(self) -> None:
        self._unsubscribe()
        for _, future in self._waiters:
            future.cancel()
        self._waiters.clear()

    def _on_button(self, event: ButtonEvent) -> None:
        self._seen.add((event.button_id, event.event))
        for condition, future in list(self._waiters):
            if (condition.id, condition.event) == (
                event.button_id,
                event.event,
            ) and not future.done():
                future.set_result(None)

    def evaluate(self, condition: Condition) -> bool:
        match condition:
            case ButtonCondition():
                return (condition.id, condition.event) in self._seen
            case RelayIsCondition():
                return self._relays.is_on(condition.id) == (condition.state == "on")
            case RandomCondition():
                return self._rng.random() < condition.probability

    async def wait_for(self, condition: Condition, timeout_s: float | None = None) -> bool:
        """Attend que la condition soit vraie. Retourne `False` si le délai est écoulé."""
        try:
            async with asyncio.timeout(timeout_s):
                if isinstance(condition, ButtonCondition):
                    await self._next_button_event(condition)
                else:
                    # Pas d'événement pour l'état d'un relais : on l'observe à intervalle régulier.
                    while not self.evaluate(condition):  # noqa: ASYNC110
                        await asyncio.sleep(self._poll)
        except TimeoutError:
            return False
        return True

    async def _next_button_event(self, condition: ButtonCondition) -> None:
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        entry = (condition, future)
        self._waiters.append(entry)
        try:
            await future
        finally:
            if entry in self._waiters:
                self._waiters.remove(entry)
