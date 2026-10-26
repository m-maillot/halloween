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

from halloween.config.models import Relay
from halloween.drivers.base import RelayDriver
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
