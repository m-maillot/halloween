"""Moteur de déclencheurs : réagit aux appuis de bouton (et, plus tard, au planning).

Les déclencheurs peuvent être remplacés à chaud (`set_triggers`). Chaque réaction s'exécute dans sa
propre tâche : un arrêt d'urgence n'attend jamais le démarrage d'un programme, et une erreur ne
casse pas l'écoute des boutons.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping

from halloween.drivers.base import ButtonDriver, ButtonEvent
from halloween.log import get_logger
from halloween.program.models import Program
from halloween.program.runs import AlreadyRunning, RunManager, TooManyRuns
from halloween.triggers.models import ButtonTrigger, Trigger

log = get_logger("triggers")


class TriggerEngine:
    def __init__(
        self,
        manager: RunManager,
        buttons: ButtonDriver,
        programs: Mapping[str, Program],
        triggers: Iterable[Trigger] = (),
    ) -> None:
        self._manager = manager
        self._buttons = buttons
        self._programs = programs
        self._triggers: list[Trigger] = list(triggers)
        self._unsubscribe = None
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def triggers(self) -> list[Trigger]:
        return list(self._triggers)

    def set_triggers(self, triggers: Iterable[Trigger]) -> None:
        """Remplace les déclencheurs (effet immédiat, sans redémarrer)."""
        self._triggers = list(triggers)

    async def start(self) -> None:
        if self._unsubscribe is None:
            self._unsubscribe = self._buttons.subscribe(self._on_button)

    async def stop(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # ------------------------------------------------------------------ boutons

    def _on_button(self, event: ButtonEvent) -> None:
        for trigger in self._triggers:
            if (
                isinstance(trigger, ButtonTrigger)
                and trigger.enabled
                and trigger.button == event.button_id
                and trigger.event == event.event
            ):
                self._spawn(self._fire(trigger))

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _fire(self, trigger: Trigger) -> None:
        with_context = {"trigger": trigger.id}
        try:
            if isinstance(trigger, ButtonTrigger) and trigger.action == "stop":
                log.warning("arrêt d'urgence demandé", extra=with_context)
                await self._manager.stop_all()
                return
            program = self._programs.get(trigger.program or "")
            if program is None:
                log.error("programme du déclencheur introuvable", extra=with_context)
                return
            run = await self._manager.start(program, trigger.policy)
            log.info("programme lancé", extra={**with_context, "run_id": run.id})
        except AlreadyRunning:
            log.info("déclenchement ignoré : le programme tourne déjà", extra=with_context)
        except TooManyRuns as exc:
            log.error("déclenchement refusé", extra={**with_context, "error": str(exc)})
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("déclencheur en échec", extra=with_context)
