"""Simulation d'un programme : exécution en temps virtuel avec des pilotes fictifs.

Retourne la timeline des commandes (`t` en secondes depuis le lancement) sans rien actionner ni
attendre. Appelée depuis l'API, `simulate` doit tourner hors de la boucle principale
(`await asyncio.to_thread(simulate, ...)`) car elle crée sa propre boucle à temps virtuel.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from halloween.config.models import AppConfig
from halloween.drivers.base import ButtonEventKind
from halloween.drivers.fakes import FakeButtonDriver, FakeHAClient, FakeRelayDriver, Recorder
from halloween.program.actions import ActionFailed, DeviceActions
from halloween.program.conditions import Conditions
from halloween.program.interpreter import ExecutionError, Interpreter, NodeEvent, RunContext
from halloween.program.models import Program
from halloween.program.virtual import SimulationDeadlock, SimulationHorizon, run_virtual

Status = Literal["completed", "timeout", "horizon", "deadlock", "truncated", "failed"]

DEFAULT_HORIZON_S = 3600.0
DEFAULT_MAX_EVENTS = 100_000


@dataclass(frozen=True)
class TimelineEntry:
    t: float
    component: str
    action: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationResult:
    status: Status
    duration_s: float
    timeline: list[TimelineEntry]
    still_on: list[str] = field(default_factory=list)
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "duration_s": self.duration_s,
            "error": self.error,
            "still_on": self.still_on,
            "timeline": [
                {"t": e.t, "component": e.component, "action": e.action, "data": e.data}
                for e in self.timeline
            ],
        }


class _BudgetExceeded(Exception):
    pass


def simulate(
    program: Program,
    config: AppConfig,
    programs: Mapping[str, Program] | None = None,
    *,
    seed: int = 0,
    button_presses: Iterable[tuple[float, str, ButtonEventKind]] = (),
    horizon_s: float = DEFAULT_HORIZON_S,
    max_events: int = DEFAULT_MAX_EVENTS,
) -> SimulationResult:
    """Simule `program`.

    - `button_presses` : appuis à jouer, `(t, id du bouton, événement)`. Sans appui, une attente de
      bouton sans délai ne se termine jamais (statut `deadlock`).
    - `horizon_s` : durée virtuelle maximale ; au-delà le statut est `horizon` (ex. boucle infinie).
    - `max_events` : borne le nombre de blocs exécutés (boucle sans attente) ; statut `truncated`.
    """
    state: dict[str, Any] = {"loop": None, "status": "completed", "error": None}
    holder = Recorder(now=lambda: state["loop"].time())
    relays = FakeRelayDriver.from_config(config, holder)
    ha = FakeHAClient(holder)
    buttons = FakeButtonDriver(b.id for b in config.buttons)

    async def main() -> None:
        loop = asyncio.get_running_loop()
        state["loop"] = loop
        rng = random.Random(seed)
        conditions = Conditions(relays, buttons, rng)
        actions = DeviceActions(config, relays, ha)
        counter = {"events": 0}

        def on_node(_: NodeEvent) -> None:
            counter["events"] += 1
            if counter["events"] > max_events:
                raise _BudgetExceeded

        ctx = RunContext("simulation", actions, conditions, programs or {}, rng, emit=on_node)

        async def play_presses() -> None:
            for t, button_id, event in sorted(button_presses):
                await asyncio.sleep(max(0.0, t - loop.time()))
                await buttons.press(button_id, event)

        presser = asyncio.ensure_future(play_presses())
        try:
            await asyncio.wait_for(Interpreter(ctx).run_program(program), program.max_duration_s)
        except TimeoutError:
            state["status"] = "timeout"  # `max_duration_s` atteinte : le run est arrêté
        except _BudgetExceeded:
            state["status"] = "truncated"
        except (ExecutionError, ActionFailed) as exc:
            state["status"], state["error"] = "failed", str(exc)
        except (
            Exception
        ) as exc:  # incohérence imprévue : on la rapporte plutôt que de planter l'API
            state["status"], state["error"] = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            presser.cancel()
            await asyncio.gather(presser, return_exceptions=True)
            await actions.aclose()
            conditions.close()

    try:
        run_virtual(main, horizon_s)
    except SimulationDeadlock as exc:
        state["status"], state["error"] = "deadlock", str(exc)
    except SimulationHorizon:
        state["status"] = "horizon"

    loop = state["loop"]
    return SimulationResult(
        status=state["status"],
        duration_s=loop.time() if loop is not None else 0.0,
        timeline=_timeline(holder, config),
        still_on=[r.id for r in config.relays if relays.is_on(r.id)],
        error=state["error"],
    )


def _timeline(recorder: Recorder, config: AppConfig) -> list[TimelineEntry]:
    """Remplace les `entity_id` par l'id du composant et `turn_on/off` par `on/off`."""
    component_of = {x.entity_id: x.id for x in (*config.lights, *config.switches)}
    component_of.update({p.script: p.id for p in config.players})
    video_of = {v.media: (p, v) for p in config.players for v in p.videos}
    result = []
    for entry in recorder.entries:
        action = entry.action
        data = entry.data
        if action.startswith("script."):
            # Lecteur : la vidéo de repos (écran noir) est « éteint », toute autre « allumé ».
            player, video = video_of.get(data.get("video"), (None, None))
            action = "off" if video and video.id == player.rest_video else "on"
            data = {"video": video.id if video else data.get("video"), "loop": data.get("boucle")}
        elif "." in action:  # appel de service Home Assistant
            action = "on" if action.endswith("turn_on") else "off"
        result.append(
            TimelineEntry(entry.t, component_of.get(entry.component, entry.component), action, data)
        )
    return result
