"""Gestionnaire de runs : plusieurs programmes en parallèle, politiques, arrêts, état de repos.

Un *run* est une exécution d'un programme (une tâche par script). Règles (spec 1 §5.3 et §6.1) :

- plusieurs runs simultanés (programmes différents) ; un seul run actif par programme, et une
  nouvelle demande est `ignore`, `restart` ou `queue` ;
- aucun verrou sur les composants : si deux runs commandent le même, la dernière commande
  l'emporte ;
- à la fin d'un run (quelle qu'en soit l'issue) avec `on_end: reset`, seuls les composants que ce
  run a commandés **et dont il est le dernier à avoir changé l'état** reviennent au repos ;
- le stop global annule tous les runs puis applique l'état de repos complet.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from halloween.config.models import AppConfig, RelayMode
from halloween.drivers.base import ButtonDriver, HAClient, RelayDriver
from halloween.log import get_logger, log_context
from halloween.program.actions import DeviceActions
from halloween.program.conditions import Conditions
from halloween.program.interpreter import ActionRunner, Interpreter, NodeEvent, RunContext
from halloween.program.models import LightNode, Program, RelayNode, SwitchNode

log = get_logger("runs")

Outcome = Literal["completed", "stopped", "failed", "timeout"]
Policy = Literal["ignore", "restart", "queue"]
RunState = Literal["queued", "running", "ended"]

MAX_ACTIVE_RUNS = 20


class AlreadyRunning(Exception):
    """Le programme tourne déjà (politique `ignore`, ou une exécution est déjà en file)."""

    def __init__(self, run: Run) -> None:
        super().__init__(f"le programme `{run.program.id}` tourne déjà")
        self.run = run


class TooManyRuns(Exception):
    pass


@dataclass(eq=False)
class Run:
    id: str
    program: Program
    state: RunState = "running"
    outcome: Outcome | None = None
    error: str | None = None
    started_at: float | None = None
    ended_at: float | None = None
    touched: set[str] = field(default_factory=set)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.id,
            "program_id": self.program.id,
            "state": self.state,
            "outcome": self.outcome,
            "error": self.error,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
        }


@dataclass(frozen=True)
class RunEvent:
    kind: Literal["run_started", "run_ended", "node_started", "node_finished"]
    run_id: str
    program_id: str
    script_id: str | None = None
    node_id: str | None = None
    outcome: Outcome | None = None
    error: str | None = None


class _RunActions(ActionRunner):
    """Actions d'un run : note quel run a commandé quel composant (propriétaire du repos)."""

    def __init__(self, manager: RunManager, run: Run) -> None:
        self._manager = manager
        self._run = run

    async def execute(self, node: RelayNode | LightNode | SwitchNode) -> None:
        self._run.touched.add(node.target)
        self._manager._owner[node.target] = self._run.id
        await self._manager.actions.execute(node)


class RunManager:
    def __init__(
        self,
        config: AppConfig,
        relays: RelayDriver,
        ha: HAClient,
        buttons: ButtonDriver,
        programs: Mapping[str, Program],
        on_event: Callable[[RunEvent], None] | None = None,
        rng_factory: Callable[[], random.Random] = random.Random,
    ) -> None:
        self._config = config
        self._relays = relays
        self._ha = ha
        self._buttons = buttons
        self._programs = programs
        self._on_event = on_event
        self._rng_factory = rng_factory
        # Une seule instance partagée : le verrou d'animation des relais impulsion y vit.
        self.actions = DeviceActions(config, relays, ha)
        self._runs: dict[str, Run] = {}
        self._owner: dict[str, str] = {}

    # ------------------------------------------------------------------ consultation

    @property
    def active(self) -> list[Run]:
        return list(self._runs.values())

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    # ------------------------------------------------------------------ démarrage

    async def start(self, program: Program, policy: Policy = "ignore") -> Run:
        same = [r for r in self._runs.values() if r.program.id == program.id]
        running = next((r for r in same if r.state == "running"), None)
        queued = next((r for r in same if r.state == "queued"), None)
        predecessor: Run | None = None
        if running is not None:
            if policy == "ignore":
                raise AlreadyRunning(running)
            if policy == "restart":
                await self.stop(running.id)
            elif queued is not None:  # une seule exécution en file par programme
                raise AlreadyRunning(queued)
            else:
                predecessor = running
        if len(self._runs) >= MAX_ACTIVE_RUNS:
            raise TooManyRuns(f"plus de {MAX_ACTIVE_RUNS} runs simultanés")

        run = Run(uuid.uuid4().hex[:8], program, state="queued" if predecessor else "running")
        self._runs[run.id] = run
        run.task = asyncio.ensure_future(self._execute(run, predecessor))
        run.task.add_done_callback(lambda _: self._ensure_ended(run))
        return run

    def _ensure_ended(self, run: Run) -> None:
        """Filet : une tâche annulée avant son premier pas n'exécute jamais son `finally`."""
        if run.done.is_set():
            return
        run.outcome = run.outcome or "stopped"
        run.state = "ended"
        run.ended_at = asyncio.get_running_loop().time()
        self._runs.pop(run.id, None)
        run.done.set()

    async def _execute(self, run: Run, predecessor: Run | None) -> None:
        loop = asyncio.get_running_loop()
        conditions: Conditions | None = None
        started = False
        try:
            if predecessor is not None:
                await predecessor.done.wait()
            run.state = "running"
            run.started_at = loop.time()
            started = True
            self._emit(RunEvent("run_started", run.id, run.program.id))
            rng = self._rng_factory()
            conditions = Conditions(self._relays, self._buttons, rng)
            context = RunContext(
                run.id,
                _RunActions(self, run),
                conditions,
                self._programs,
                rng,
                emit=lambda event: self._emit_node(run, event),
            )
            with log_context(run_id=run.id):
                log.info("run démarré", extra={"program": run.program.id})
                async with asyncio.timeout(run.program.max_duration_s):
                    await Interpreter(context).run_program(run.program)
            run.outcome = "completed"
        except TimeoutError:
            run.outcome = "timeout"
        except asyncio.CancelledError:
            run.outcome = "stopped"
        except Exception as exc:
            run.outcome, run.error = "failed", f"{type(exc).__name__}: {exc}"
            log.error("run en échec", extra={"run_id": run.id, "error": run.error}, exc_info=True)
        finally:
            await self._finish(run, conditions, started)

    async def _finish(self, run: Run, conditions: Conditions | None, started: bool) -> None:
        if conditions is not None:
            conditions.close()
        try:
            if started and run.program.on_end == "reset":
                await self._reset_components(
                    [c for c in run.touched if self._owner.get(c) == run.id]
                )
        finally:
            for component in [c for c, owner in self._owner.items() if owner == run.id]:
                del self._owner[component]
            run.state = "ended"
            run.ended_at = asyncio.get_running_loop().time()
            self._runs.pop(run.id, None)
            run.done.set()
            log.info("run terminé", extra={"run_id": run.id, "outcome": run.outcome})
            if started:
                self._emit(
                    RunEvent(
                        "run_ended", run.id, run.program.id, outcome=run.outcome, error=run.error
                    )
                )

    # ------------------------------------------------------------------ arrêts

    async def stop(self, run_id: str) -> None:
        """Arrête un run (sans effet s'il est déjà terminé)."""
        run = self._runs.get(run_id)
        if run is None or run.task is None:
            return
        run.task.cancel()
        await run.done.wait()

    async def stop_all(self) -> None:
        """Arrêt global : annule tous les runs puis applique l'état de repos complet."""
        runs = list(self._runs.values())
        for run in runs:
            if run.task is not None:
                run.task.cancel()
        await asyncio.gather(*(run.done.wait() for run in runs))
        await self.actions.aclose()
        await self.reset_all()

    async def reset_all(self) -> None:
        """État de repos complet : relais éteints, lumières et interrupteurs à leur repos défini.

        Appelé au démarrage du moteur et au stop global.
        """
        try:
            await self._relays.all_off()
        except Exception:
            log.exception("extinction des relais en échec")
        await self._reset_components(list(self._config.rest_state))
        self._owner.clear()

    async def shutdown(self) -> None:
        await self.stop_all()
        await self.actions.aclose()

    # ------------------------------------------------------------------ état de repos

    async def _reset_components(self, component_ids: list[str]) -> None:
        for component_id in component_ids:
            try:
                await self._reset_component(component_id)
            except Exception:  # un appareil en panne ne doit pas empêcher de remettre les autres
                log.exception("remise au repos en échec", extra={"component": component_id})

    async def _reset_component(self, component_id: str) -> None:
        relay = next((r for r in self._config.relays if r.id == component_id), None)
        if relay is not None:
            if relay.mode is RelayMode.LATCHED:
                await self._relays.set(relay.id, False)
            return
        rest = self._config.rest_state.get(component_id)
        if rest is None:
            return  # aucun état de repos défini : le composant n'est pas touché
        light = next((x for x in self._config.lights if x.id == component_id), None)
        if light is not None:
            if rest.state == "on":
                await self._ha.light_on(
                    light.entity_id,
                    rgb_color=rest.rgb_color,
                    brightness=rest.brightness,
                    transition=rest.transition,
                )
            else:
                await self._ha.light_off(light.entity_id)
            return
        switch = next((x for x in self._config.switches if x.id == component_id), None)
        if switch is not None:
            await (self._ha.switch_on if rest.state == "on" else self._ha.switch_off)(
                switch.entity_id
            )

    # ------------------------------------------------------------------ événements

    def _emit(self, event: RunEvent) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(event)
        except Exception:
            log.exception("abonné aux événements de run en échec")

    def _emit_node(self, run: Run, event: NodeEvent) -> None:
        kind = "node_started" if event.kind == "started" else "node_finished"
        self._emit(RunEvent(kind, run.id, run.program.id, event.script_id, event.node_id))
