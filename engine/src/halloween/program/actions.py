"""Exécution des blocs d'action : relais (GPIO), lumières, interrupteurs et lecteurs de vidéos
(Home Assistant)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from halloween.config.models import AppConfig, Relay, RelayMode
from halloween.drivers.base import HAClient, RelayDriver
from halloween.log import get_logger
from halloween.program.interpreter import ActionRunner, ExecutionError
from halloween.program.models import ActionNode, LightNode, PlayerNode, RelayNode, SwitchNode

log = get_logger("actions")


class ActionFailed(Exception):
    """Une action a échoué et son bloc demandait d'arrêter le run (`on_error: abort`)."""


class DeviceActions(ActionRunner):
    """Applique les blocs d'action sur les pilotes.

    - Erreur d'un appareil : journalisée et ignorée par défaut (`on_error: continue`), sinon
      `ActionFailed` arrête le run. L'annulation n'est jamais avalée.
    - `fire_and_forget` (Home Assistant) : l'appel part en tâche de fond, le bloc suivant n'attend
      pas la réponse ; une erreur y est seulement journalisée. `aclose()` annule ces tâches.
    - Relais `push` : impulsion de `pulse_ms` ; pendant `animation_s`, un nouveau déclenchement est
      ignoré (l'objet est occupé).
    """

    def __init__(
        self,
        config: AppConfig,
        relays: RelayDriver,
        ha: HAClient,
        on_error: Callable[[ActionNode, Exception], None] | None = None,
    ) -> None:
        self._on_error = on_error
        self._config = config
        self._relays = relays
        self._ha = ha
        self._busy_until: dict[str, float] = {}
        self._background: set[asyncio.Task[None]] = set()

    def update_config(self, config: AppConfig) -> None:
        self._config = config

    async def aclose(self) -> None:
        """Annule les appels en tâche de fond encore en cours."""
        tasks = list(self._background)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def execute(self, node: RelayNode | LightNode | SwitchNode | PlayerNode) -> None:
        try:
            if isinstance(node, RelayNode):
                await self._relay(node)
            elif node.fire_and_forget:
                self._spawn(node)
            else:
                await self._home_assistant(node)
        except (ExecutionError, asyncio.CancelledError):
            raise
        except Exception as exc:
            self._on_failure(node, exc)

    def _on_failure(self, node: ActionNode, exc: Exception) -> None:
        log.error(
            "action en échec",
            extra={"error": str(exc), "error_type": type(exc).__name__, "on_error": node.on_error},
        )
        if self._on_error is not None:
            self._on_error(node, exc)
        if node.on_error == "abort":
            raise ActionFailed(f"{node.id} : {exc}") from exc

    # ------------------------------------------------------------------ relais

    def _find_relay(self, relay_id: str) -> Relay:
        for relay in self._config.relays:
            if relay.id == relay_id:
                return relay
        raise ExecutionError(f"relais inconnu : {relay_id}")

    async def _relay(self, node: RelayNode) -> None:
        relay = self._find_relay(node.target)
        if node.state is not None:
            if relay.mode is not RelayMode.LATCHED:
                raise ExecutionError(
                    f"`{relay.id}` est en mode impulsion : utiliser « déclencher »"
                )
            log.info("relais", extra={"component": relay.id, "action": node.state})
            await self._relays.set(relay.id, node.state == "on")
            return
        if relay.mode is not RelayMode.PUSH:
            raise ExecutionError(f"`{relay.id}` est en mode maintenu : utiliser allumer/éteindre")
        await self._trigger(relay, wait_for_end=node.wait_for_end)

    async def _trigger(self, relay: Relay, wait_for_end: bool) -> None:
        loop = asyncio.get_running_loop()
        busy_until = self._busy_until.get(relay.id, 0.0)
        if loop.time() < busy_until:
            log.info("déclenchement ignoré : objet occupé", extra={"component": relay.id})
        else:
            pulse_s = (relay.pulse_ms or 500) / 1000
            log.info("relais", extra={"component": relay.id, "action": "trigger"})
            await self._relays.set(relay.id, True)
            # L'objet n'est occupé que si l'impulsion a bien été envoyée.
            if relay.animation_s is not None:
                self._busy_until[relay.id] = loop.time() + max(relay.animation_s, pulse_s)
            try:
                await asyncio.sleep(pulse_s)
            finally:
                await self._relays.set(relay.id, False)
        if wait_for_end:
            remaining = self._busy_until.get(relay.id, 0.0) - loop.time()
            if remaining > 0:
                await asyncio.sleep(remaining)

    # ------------------------------------------------------------------ Home Assistant

    def _spawn(self, node: LightNode | SwitchNode | PlayerNode) -> None:
        async def background() -> None:
            try:
                await self._home_assistant(node)
            except Exception as exc:  # personne n'attend cette tâche : on journalise
                log.error("action en tâche de fond en échec", extra={"error": str(exc)})

        task = asyncio.ensure_future(background())
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _player(self, node: PlayerNode) -> None:
        player = next((x for x in self._config.players if x.id == node.target), None)
        if player is None:
            raise ExecutionError(f"lecteur inconnu : {node.target}")
        if node.action == "rest":
            video = player.video(player.rest_video) if player.rest_video else None
            if video is None:
                raise ExecutionError(f"`{player.id}` n'a pas de vidéo de repos")
            loop = True
        else:
            video = player.video(node.video or "")
            if video is None:
                raise ExecutionError(f"vidéo inconnue sur `{player.id}` : {node.video}")
            loop = node.loop
        log.info(
            "lecteur",
            extra={"component": player.id, "action": node.action, "video": video.id},
        )
        await self._ha.play_video(player.script, video.media, loop)
        if node.wait_for_end and video.duration_s is not None:
            await asyncio.sleep(video.duration_s)

    async def _home_assistant(self, node: LightNode | SwitchNode | PlayerNode) -> None:
        if isinstance(node, PlayerNode):
            await self._player(node)
        elif isinstance(node, LightNode):
            light = next((x for x in self._config.lights if x.id == node.target), None)
            if light is None:
                raise ExecutionError(f"lumière inconnue : {node.target}")
            log.info("lumière", extra={"component": light.id, "action": node.state})
            if node.state == "on":
                await self._ha.light_on(
                    light.entity_id,
                    rgb_color=node.rgb_color,
                    brightness=node.brightness,
                    transition=node.transition,
                )
            else:
                await self._ha.light_off(light.entity_id)
        else:
            switch = next((x for x in self._config.switches if x.id == node.target), None)
            if switch is None:
                raise ExecutionError(f"interrupteur inconnu : {node.target}")
            log.info("interrupteur", extra={"component": switch.id, "action": node.state})
            call: Any = self._ha.switch_on if node.state == "on" else self._ha.switch_off
            await call(switch.entity_id)
