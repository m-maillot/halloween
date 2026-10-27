"""Le moteur complet : démarrage, reprise après redémarrage, arrêt propre.

Au démarrage (spec 1 §5.3, §6.3), dans cet ordre :

1. charger et valider la configuration (invalide : on refuse de démarrer, plutôt que de piloter
   des relais avec une configuration vide ou fausse) ;
2. créer les pilotes (les sorties sont forcées au repos) et **remettre tout au repos** : relais
   éteints, lumières et interrupteurs à leur état de repos ;
3. charger les programmes et les déclencheurs ; ceux qui sont invalides sont **écartés et
   signalés**, les autres fonctionnent ;
4. seulement alors, activer les boutons et le planning : rien ne peut se déclencher avant que le
   repos soit appliqué.

Au Pi qui démarre plus vite que Home Assistant, la remise au repos des lumières est retentée en
tâche de fond pendant quelques minutes (sans toucher un composant déjà repris par un programme).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from halloween.backend import Backend
from halloween.config.models import AppConfig
from halloween.config.validation import validate_config
from halloween.drivers.base import ButtonDriver, ButtonEvent, HAClient, RelayDriver
from halloween.drivers.observed import ObservedHAClient, ObservedRelayDriver
from halloween.events import (
    ButtonPressEvent,
    ComponentChangedEvent,
    ErrorEvent,
    EventHub,
    from_run_event,
)
from halloween.issues import Issue, errors
from halloween.lock import LockState, Throttle
from halloween.log import current_context, get_logger
from halloween.program.models import ActionNode, Program
from halloween.program.runs import RunEvent, RunManager
from halloween.program.validation import validate_program
from halloween.store import Store
from halloween.triggers import TriggerEngine, parse_triggers, validate_triggers
from halloween.triggers.models import Trigger

log = get_logger("engine")

# Délais (s) entre les tentatives de remise au repos des lumières quand Home Assistant n'est pas
# encore prêt ; le dernier se répète jusqu'à `REST_RETRY_WINDOW_S`.
REST_RETRY_DELAYS = (15.0, 15.0, 30.0, 30.0, 60.0)
REST_RETRY_WINDOW_S = 600.0


class StartupError(Exception):
    """Démarrage impossible (configuration illisible ou invalide)."""

    def __init__(self, message: str, issues: list[Issue] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []


@dataclass
class StartupReport:
    programs: int = 0
    triggers: int = 0
    issues: list[Issue] = field(default_factory=list)
    rest_pending: list[str] = field(default_factory=list)  # remise au repos à retenter


class Engine:
    def __init__(
        self,
        store: Store,
        backend: Backend,
        write: Callable[[str], None] = print,
        ha_dry_run: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self._backend = backend
        self._write = write
        self._ha_dry_run = ha_dry_run
        self._clock = clock
        self.config: AppConfig = AppConfig()
        self.programs: dict[str, Program] = {}
        self.manager: RunManager | None = None
        self.triggers: TriggerEngine | None = None
        self._relays: RelayDriver | None = None
        self._buttons: ButtonDriver | None = None
        self._ha: HAClient | None = None
        self._retry: asyncio.Task[None] | None = None
        self.report = StartupReport()
        self.ready = asyncio.Event()
        self.hub = EventHub()
        self.lock = LockState.in_dir(store.root)
        self.throttle = Throttle()
        self._reconfiguring = asyncio.Lock()
        # Sérialise les modifications de configuration faites par l'API (lecture puis écriture).
        self.config_lock = asyncio.Lock()

    @property
    def relays(self) -> RelayDriver:
        assert self._relays is not None, "moteur non démarré"
        return self._relays

    @property
    def buttons(self) -> ButtonDriver:
        assert self._buttons is not None, "moteur non démarré"
        return self._buttons

    @property
    def images_dir(self) -> Path:
        return self.store.root / "images"

    @property
    def ha(self) -> HAClient:
        assert self._ha is not None, "moteur non démarré"
        return self._ha

    async def start(self) -> StartupReport:
        """Démarre le moteur ; en cas d'échec en cours de route, libère ce qui a été acquis."""
        try:
            return await self._start()
        except BaseException:
            await self.stop()
            raise

    async def _start(self) -> StartupReport:
        self.store.initialize()
        self.config = self._load_config()
        return await self._build()

    async def _build(self) -> StartupReport:
        """Crée pilotes, gestionnaire et déclencheurs d'après `self.config` (ordre en tête)."""
        report = StartupReport()
        # Pilotes : les sorties sont au repos dès leur création ; on le garantit aussitôt.
        self._relays = self._backend.relays(self.config)
        self._buttons = self._backend.buttons(self.config)
        self._ha = self._backend.ha(self.config, self._write, self._ha_dry_run)
        await self._relays.all_off()

        self._load_programs(report)
        triggers = self._load_triggers(report)
        self._buttons.subscribe(self._on_button)
        observed_relays = ObservedRelayDriver(
            self._relays, [r.id for r in self.config.relays], self._on_relay_change
        )
        observed_ha = ObservedHAClient(self._ha, self._on_ha_change)
        self.manager = RunManager(
            self.config,
            observed_relays,
            observed_ha,
            self._buttons,
            self.programs,
            on_event=self._on_run_event,
            on_action_error=self._on_action_error,
        )
        self.triggers = TriggerEngine(
            self.manager, self._buttons, self.programs, triggers, clock=self._clock
        )

        report.rest_pending = await self.manager.reset_all()
        if report.rest_pending:
            self._retry = asyncio.ensure_future(self._retry_rest(list(report.rest_pending)))

        await self._buttons.start()
        await self.triggers.start()

        report.programs = len(self.programs)
        report.triggers = len(self.triggers.triggers)
        for issue in report.issues:
            log.warning("démarrage : %s", issue.message, extra={"code": issue.code})
        self.report = report
        self.ready.set()
        log.info(
            "moteur démarré",
            extra={"programs": report.programs, "triggers": report.triggers},
        )
        return report

    async def stop(self) -> None:
        """Arrêt propre : plus de réaction, tout s'arrête, relais éteints, broches libérées."""
        self.ready.clear()
        if self._retry is not None:
            self._retry.cancel()
            await asyncio.gather(self._retry, return_exceptions=True)
            self._retry = None
        if self.triggers is not None:
            await self.triggers.stop()
        if self.manager is not None:
            await self.manager.shutdown()
        if self._buttons is not None:
            await self._buttons.close()
        if self._relays is not None:
            with contextlib.suppress(Exception):
                await self._relays.all_off()
            await self._relays.close()
        if self._ha is not None:
            await self._ha.close()
        self.manager = self.triggers = None
        self._relays = self._buttons = self._ha = None

    async def apply_config(self, config: AppConfig) -> StartupReport:
        """Remplace la configuration à chaud (spec 1 §4.6).

        Valide d'abord (invalide : `StartupError`, rien ne change), puis arrête tout (les runs en
        cours sont stoppés, état de repos de l'ancienne configuration), enregistre, et reconstruit
        pilotes, programmes et déclencheurs. `ready` est levé pendant l'opération.
        """
        problems = errors(validate_config(config))
        if problems:
            raise StartupError(
                "configuration invalide :\n" + "\n".join(f"  - {p.message}" for p in problems),
                problems,
            )
        async with self._reconfiguring:
            await self.stop()
            self.store.save_config(config)
            self.config = config
            report = await self._build()
        self.hub.publish(ComponentChangedEvent(kind="catalog"))
        return report

    def reload_content(self) -> list[Issue]:
        """Recharge programmes et déclencheurs depuis le disque (après une modification par l'API).

        Les programmes invalides sont écartés et les déclencheurs qui en dépendent aussi ; les
        runs en cours ne sont pas touchés. Retourne les problèmes rencontrés.
        """
        assert self.triggers is not None
        report = StartupReport()
        self._load_programs(report)
        self.triggers.set_triggers(self._load_triggers(report))
        self.report.issues = report.issues
        self.report.programs = len(self.programs)
        self.report.triggers = len(self.triggers.triggers)
        return report.issues

    def update_cosmetics(self, config: AppConfig) -> None:
        """Enregistre une config qui ne change que noms, images, repos : rien n'est interrompu."""
        self.store.save_config(config)
        self.config = config
        if self.manager is not None:
            self.manager.update_config(config)
        self.hub.publish(ComponentChangedEvent(kind="catalog"))

    # ------------------------------------------------------------------ événements temps réel

    def _on_run_event(self, event: RunEvent) -> None:
        for item in from_run_event(event):
            self.hub.publish(item)

    def _on_button(self, event: ButtonEvent) -> None:
        self.hub.publish(ButtonPressEvent(button_id=event.button_id, event=event.event))

    def _on_relay_change(self, relay_id: str, on: bool) -> None:
        self.hub.publish(
            ComponentChangedEvent(kind="relay", component_id=relay_id, state="on" if on else "off")
        )

    def _on_ha_change(self, domain: str, service: str, data: dict) -> None:
        components = {
            **{light.entity_id: ("light", light.id) for light in self.config.lights},
            **{switch.entity_id: ("switch", switch.id) for switch in self.config.switches},
        }
        found = components.get(str(data.get("entity_id")))
        if found is None or service not in ("turn_on", "turn_off"):
            return
        kind, component_id = found
        details = {k: v for k, v in data.items() if k in ("rgb_color", "brightness", "transition")}
        self.hub.publish(
            ComponentChangedEvent(
                kind=kind,  # type: ignore[arg-type]
                component_id=component_id,
                state="on" if service == "turn_on" else "off",
                details=details,
            )
        )

    def _on_action_error(self, node: ActionNode, exc: Exception) -> None:
        context = current_context()
        self.hub.publish(
            ErrorEvent(
                source="action",
                message=str(exc),
                run_id=context.get("run_id"),
                node_id=node.id,
                component_id=getattr(node, "target", None),
            )
        )

    # ------------------------------------------------------------------ chargement

    def _load_config(self) -> AppConfig:
        try:
            config = self.store.load_config()
        except ValidationError as exc:
            raise StartupError(f"{self.store.config_path} invalide :\n{exc}") from exc
        if not self.store.config_path.exists():
            raise StartupError(f"aucune configuration : {self.store.config_path} n'existe pas")
        problems = errors(validate_config(config))
        if problems:
            raise StartupError(
                "configuration invalide :\n" + "\n".join(f"  - {p.message}" for p in problems),
                problems,
            )
        return config

    def _load_programs(self, report: StartupReport) -> None:
        loaded = self.store.load_programs()
        report.issues.extend(loaded.issues)
        self.programs.clear()
        for program in loaded.programs.values():
            problems = errors(validate_program(program, self.config, loaded.programs))
            if problems:
                for problem in problems:
                    report.issues.append(
                        Issue(
                            "error",
                            problem.code,
                            f"programme `{program.id}` écarté : [{problem.node_id or '-'}] "
                            f"{problem.message}",
                            problem.node_id,
                        )
                    )
                continue
            self.programs[program.id] = program

    def _load_triggers(self, report: StartupReport) -> list[Trigger]:
        triggers, parse_issues = parse_triggers(self.store.load_triggers())
        report.issues.extend(parse_issues)
        problems = validate_triggers(triggers, self.config, set(self.programs))
        report.issues.extend(problems)
        rejected = {p.component_id for p in problems if p.severity == "error"}
        return [t for t in triggers if t.id not in rejected]

    # ------------------------------------------------------------------ Home Assistant en retard

    async def _retry_rest(self, pending: list[str]) -> None:
        """Retente la remise au repos des composants que Home Assistant n'a pas pu recevoir."""
        assert self.manager is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + REST_RETRY_WINDOW_S
        delays = iter(REST_RETRY_DELAYS)
        delay = REST_RETRY_DELAYS[-1]
        while pending and loop.time() < deadline:
            delay = next(delays, delay)
            await asyncio.sleep(delay)
            pending = await self.manager.reset_unowned(pending)
            if not pending:
                log.info("remise au repos terminée après nouvel essai")
                return
        if pending:
            log.error("remise au repos abandonnée", extra={"components": pending})
