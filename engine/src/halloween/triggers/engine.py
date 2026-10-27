"""Moteur de déclencheurs : réagit aux appuis de bouton et au planning (cron).

Les déclencheurs peuvent être remplacés à chaud (`set_triggers`). Chaque réaction s'exécute dans sa
propre tâche : un arrêt d'urgence n'attend jamais le démarrage d'un programme, et une erreur ne
casse pas l'écoute des boutons.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo

from halloween.drivers.base import ButtonDriver, ButtonEvent
from halloween.log import get_logger
from halloween.program.models import Program
from halloween.program.runs import AlreadyRunning, RunManager, TooManyRuns
from halloween.triggers.cron import CronError, CronExpression
from halloween.triggers.models import ButtonTrigger, ScheduleTrigger, Trigger
from halloween.triggers.timezone import system_timezone

log = get_logger("triggers")

# Le planning se réveille au plus tard toutes les TICK_S secondes : il détecte ainsi un saut
# d'horloge (le Pi n'a pas d'horloge à pile et se recale par le réseau après le démarrage).
TICK_S = 15.0
# Une échéance dépassée de plus que GRACE_S (arrêt du moteur, saut d'horloge) est sautée plutôt
# que lancée en retard, au mauvais moment du spectacle.
GRACE_S = 60.0


class TriggerEngine:
    def __init__(
        self,
        manager: RunManager,
        buttons: ButtonDriver,
        programs: Mapping[str, Program],
        triggers: Iterable[Trigger] = (),
        clock: Callable[[], datetime] | None = None,
        default_timezone: tzinfo | None = None,
    ) -> None:
        self._manager = manager
        self._buttons = buttons
        self._programs = programs
        self._triggers: list[Trigger] = list(triggers)
        self._default_tz = default_timezone or system_timezone()
        self._clock = clock or (lambda: datetime.now(self._default_tz))
        self._unsubscribe = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._scheduler: asyncio.Task[None] | None = None
        self._changed = asyncio.Event()
        self._crons: dict[tuple[str, str | None], CronExpression] = {}

    @property
    def triggers(self) -> list[Trigger]:
        return list(self._triggers)

    def set_triggers(self, triggers: Iterable[Trigger]) -> None:
        """Remplace les déclencheurs (effet immédiat, sans redémarrer)."""
        self._triggers = list(triggers)
        self._changed.set()  # le planning recalcule ses échéances

    async def start(self) -> None:
        if self._unsubscribe is None:
            self._unsubscribe = self._buttons.subscribe(self._on_button)
        if self._scheduler is None:
            self._scheduler = asyncio.ensure_future(self._run_schedule())

    async def stop(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._scheduler is not None:
            self._scheduler.cancel()
            await asyncio.gather(self._scheduler, return_exceptions=True)
            self._scheduler = None
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

    # ------------------------------------------------------------------ planning

    def _cron(self, trigger: ScheduleTrigger) -> tuple[CronExpression, tzinfo] | None:
        tz = ZoneInfo(trigger.timezone) if trigger.timezone else self._default_tz
        key = (trigger.cron, trigger.timezone)
        if key not in self._crons:
            try:
                self._crons[key] = CronExpression(trigger.cron)
            except CronError as exc:
                log.error("cron invalide", extra={"trigger": trigger.id, "error": str(exc)})
                return None
        return self._crons[key], tz

    async def _run_schedule(self) -> None:
        last = self._clock()
        while True:
            current = self._clock()
            if current < last:  # horloge reculée (resynchronisation) : on repart d'ici
                log.warning(
                    "horloge reculée", extra={"from": last.isoformat(), "to": current.isoformat()}
                )
                last = current
            delay = TICK_S
            for trigger in self._triggers:
                if not isinstance(trigger, ScheduleTrigger) or not trigger.enabled:
                    continue
                compiled = self._cron(trigger)
                if compiled is None:
                    continue
                expression, tz = compiled
                due = expression.next_after(last.astimezone(tz))
                if due is not None and due <= current:
                    lateness = (current - due).total_seconds()
                    if lateness <= GRACE_S:
                        self._spawn(self._fire(trigger))
                    else:
                        log.warning(
                            "échéance manquée, non lancée",
                            extra={
                                "trigger": trigger.id,
                                "due": due.isoformat(),
                                "late_s": lateness,
                            },
                        )
                upcoming = expression.next_after(current.astimezone(tz))
                if upcoming is not None:
                    delay = min(delay, max((upcoming - current).total_seconds(), 0.0))
            last = current
            self._changed.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._changed.wait(), timeout=max(delay, 0.05))

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
