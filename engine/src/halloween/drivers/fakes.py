"""Pilotes fictifs : enregistrent les appels dans un `Recorder` partagé (timeline de la
simulation) et permettent d'injecter des pannes."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from halloween.config.models import AppConfig
from halloween.drivers.base import (
    ButtonDriver,
    ButtonEvent,
    ButtonEventKind,
    HAClient,
    HAError,
    RelayDriver,
)


@dataclass(frozen=True)
class Entry:
    t: float
    component: str
    action: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Recorder:
    """Journal des commandes envoyées aux périphériques, horodaté par `now`."""

    now: Callable[[], float] = time.monotonic
    entries: list[Entry] = field(default_factory=list)

    def record(self, component: str, action: str, **data: Any) -> None:
        self.entries.append(Entry(self.now(), component, action, data))

    def timeline(self) -> list[tuple[float, str, str]]:
        return [(e.t, e.component, e.action) for e in self.entries]


class FakeRelayDriver(RelayDriver):
    def __init__(self, relay_ids: Iterable[str], recorder: Recorder | None = None) -> None:
        self.recorder = recorder or Recorder()
        self._state = dict.fromkeys(relay_ids, False)
        self.fail_on: dict[str, Exception] = {}

    @classmethod
    def from_config(cls, config: AppConfig, recorder: Recorder | None = None) -> FakeRelayDriver:
        return cls((r.id for r in config.relays), recorder)

    def _known(self, relay_id: str) -> None:
        if relay_id not in self._state:
            raise KeyError(f"relais inconnu : {relay_id}")

    async def set(self, relay_id: str, on: bool) -> None:
        self._known(relay_id)
        if relay_id in self.fail_on:
            raise self.fail_on[relay_id]
        self._state[relay_id] = on
        self.recorder.record(relay_id, "on" if on else "off")

    def is_on(self, relay_id: str) -> bool:
        self._known(relay_id)
        return self._state[relay_id]

    async def all_off(self) -> None:
        for relay_id, on in self._state.items():
            if on:
                self._state[relay_id] = False
                self.recorder.record(relay_id, "off", reason="all_off")


class FakeButtonDriver(ButtonDriver):
    def __init__(self, button_ids: Iterable[str]) -> None:
        super().__init__()
        self._ids = set(button_ids)

    async def press(self, button_id: str, event: ButtonEventKind = "short") -> None:
        """Simule un appui."""
        if button_id not in self._ids:
            raise KeyError(f"bouton inconnu : {button_id}")
        await self._emit(ButtonEvent(button_id, event))


class FakeHAClient(HAClient):
    """Enregistre les appels de service ; `fail_with` simule une panne de Home Assistant."""

    def __init__(self, recorder: Recorder | None = None) -> None:
        self.recorder = recorder or Recorder()
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.fail_with: Exception | None = None
        self.fail_entities: dict[str, Exception] = {}

    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        entity = data.get("entity_id", "")
        error = self.fail_entities.get(entity) or self.fail_with
        if error is not None:
            raise error if isinstance(error, HAError) else HAError(str(error))
        self.calls.append((domain, service, dict(data)))
        self.recorder.record(
            entity, f"{domain}.{service}", **{k: v for k, v in data.items() if k != "entity_id"}
        )
