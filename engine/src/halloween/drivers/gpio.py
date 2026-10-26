"""Pilotes GPIO réels (Raspberry Pi) basés sur gpiozero.

`gpiozero` est importé à la demande : le reste du moteur reste importable sans lui. Sur le Pi,
l'extra `pi` installe aussi `lgpio` (compatible Pi 5). Pour les tests, une fabrique de broches
fictive (`gpiozero.pins.mock.MockFactory`) peut être injectée via `pin_factory`.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterable
from typing import Any

from halloween.config.models import Button, Relay
from halloween.drivers.base import ButtonDriver, ButtonEvent, ButtonEventKind, RelayDriver
from halloween.drivers.presses import PressClassifier
from halloween.log import get_logger

log = get_logger("gpio")


class GpioRelayDriver(RelayDriver):
    """Un relais par broche. `on` est l'état logique : `active_low` inverse le niveau électrique.

    - À la création, **chaque sortie est forcée au repos** (relais ouvert) avant toute autre action.
    - Si un relais a `max_on_seconds`, le pilote le coupe lui-même au bout de ce délai, quoi que
      fasse le programme (garde-fou indépendant des scénarios).
    - `close()` éteint les relais puis libère les broches.
    """

    def __init__(self, relays: Iterable[Relay], pin_factory: Any = None) -> None:
        from gpiozero import DigitalOutputDevice

        self._relays = {relay.id: relay for relay in relays}
        self._devices: dict[str, Any] = {}
        self._watchdogs: dict[str, asyncio.TimerHandle] = {}
        try:
            for relay in self._relays.values():
                self._devices[relay.id] = DigitalOutputDevice(
                    relay.pin,
                    active_high=not relay.active_low,
                    initial_value=False,
                    pin_factory=pin_factory,
                )
        except BaseException:
            self._release()
            raise

    def _device(self, relay_id: str) -> Any:
        try:
            return self._devices[relay_id]
        except KeyError:
            raise KeyError(f"relais inconnu : {relay_id}") from None

    async def set(self, relay_id: str, on: bool) -> None:
        device = self._device(relay_id)
        self._cancel_watchdog(relay_id)
        if on:
            device.on()
            limit = self._relays[relay_id].max_on_seconds
            if limit is not None:
                loop = asyncio.get_running_loop()
                self._watchdogs[relay_id] = loop.call_later(limit, self._expire, relay_id)
        else:
            device.off()

    def is_on(self, relay_id: str) -> bool:
        return bool(self._device(relay_id).value)

    async def all_off(self) -> None:
        for relay_id in self._devices:
            self._cancel_watchdog(relay_id)
        self._all_off_now()

    async def close(self) -> None:
        self._release()

    # ------------------------------------------------------------------ interne

    def _expire(self, relay_id: str) -> None:
        self._watchdogs.pop(relay_id, None)
        self._devices[relay_id].off()
        log.warning(
            "durée maximale d'allumage atteinte : relais coupé",
            extra={"component": relay_id, "max_on_seconds": self._relays[relay_id].max_on_seconds},
        )

    def _cancel_watchdog(self, relay_id: str) -> None:
        handle = self._watchdogs.pop(relay_id, None)
        if handle is not None:
            handle.cancel()

    def _all_off_now(self) -> None:
        for relay_id, device in self._devices.items():
            try:
                device.off()
            except Exception:
                log.exception("extinction impossible", extra={"component": relay_id})

    def _release(self) -> None:
        for handle in self._watchdogs.values():
            handle.cancel()
        self._watchdogs.clear()
        self._all_off_now()
        for device in self._devices.values():
            with contextlib.suppress(Exception):
                device.close()
        self._devices.clear()


class GpioButtonDriver(ButtonDriver):
    """Boutons câblés sur des broches GPIO (appui = niveau bas avec `pull: up`).

    gpiozero appelle ses rappels dans un fil à part : chaque front est transmis à la boucle asyncio
    (`call_soon_threadsafe`), où `PressClassifier` reconnaît appui court, long ou double.
    L'anti-rebond (`debounce_ms`) est assuré par gpiozero.
    """

    def __init__(self, buttons: Iterable[Button], pin_factory: Any = None) -> None:
        super().__init__()
        self._buttons = list(buttons)
        self._pin_factory = pin_factory
        self._devices: dict[str, Any] = {}
        self._classifiers: dict[str, PressClassifier] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        from gpiozero import Button as GpioButton

        loop = asyncio.get_running_loop()
        try:
            for button in self._buttons:
                classifier = PressClassifier(
                    lambda kind, button_id=button.id: self._on_event(button_id, kind),
                    button.long_press_ms / 1000,
                    button.double_press_ms / 1000,
                )
                device = GpioButton(
                    button.pin,
                    pull_up=button.pull == "up",
                    bounce_time=button.debounce_ms / 1000 or None,
                    pin_factory=self._pin_factory,
                )
                device.when_pressed = self._threadsafe(loop, classifier.press)
                device.when_released = self._threadsafe(loop, classifier.release)
                self._classifiers[button.id] = classifier
                self._devices[button.id] = device
        except BaseException:
            await self.close()
            raise

    @staticmethod
    def _threadsafe(loop: asyncio.AbstractEventLoop, callback: Any) -> Any:
        def forward() -> None:
            with contextlib.suppress(RuntimeError):  # boucle déjà fermée à l'arrêt
                loop.call_soon_threadsafe(callback)

        return forward

    def _on_event(self, button_id: str, kind: ButtonEventKind) -> None:
        log.info("appui", extra={"button": button_id, "event": kind})
        task = asyncio.ensure_future(self._emit(ButtonEvent(button_id, kind)))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def close(self) -> None:
        for device in self._devices.values():
            device.when_pressed = None
            device.when_released = None
            with contextlib.suppress(Exception):
                device.close()
        for classifier in self._classifiers.values():
            classifier.reset()
        self._devices.clear()
        self._classifiers.clear()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
