"""Événements temps réel : modèles, diffusion (`EventHub`) et conversions.

Les événements sont diffusés par le WebSocket `/api/events`. Chacun porte un `type` et l'heure
(`ts`, secondes depuis 1970). Un abonné lent ne bloque jamais le moteur : sa file est bornée et
les plus anciens événements sont abandonnés (compteur `dropped`).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from halloween.drivers.base import ButtonEventKind
from halloween.program.runs import Outcome, RunEvent


class _Base(BaseModel):
    ts: float = Field(default_factory=time.time)


class RunStartedEvent(_Base):
    type: Literal["run_started"] = "run_started"
    run_id: str
    program_id: str


class RunEndedEvent(_Base):
    type: Literal["run_ended"] = "run_ended"
    run_id: str
    program_id: str
    outcome: Outcome | None = None
    error: str | None = None


class NodeStartedEvent(_Base):
    type: Literal["node_started"] = "node_started"
    run_id: str
    program_id: str
    script_id: str
    node_id: str


class NodeFinishedEvent(_Base):
    type: Literal["node_finished"] = "node_finished"
    run_id: str
    program_id: str
    script_id: str
    node_id: str


class ComponentChangedEvent(_Base):
    """Un composant a changé d'état (`kind` relay / light / switch / player), ou le catalogue a été
    modifié (`kind: "catalog"`, sans `component_id`) : l'interface relit alors `/api/devices`."""

    type: Literal["component_changed"] = "component_changed"
    kind: Literal["relay", "light", "switch", "player", "catalog"]
    component_id: str | None = None
    state: Literal["on", "off"] | None = None
    details: dict[str, Any] = {}


class ButtonPressEvent(_Base):
    type: Literal["button_event"] = "button_event"
    button_id: str
    event: ButtonEventKind


class LockChangedEvent(_Base):
    type: Literal["lock_changed"] = "lock_changed"
    locked: bool


class ErrorEvent(_Base):
    type: Literal["error"] = "error"
    source: Literal["run", "action", "startup"]
    message: str
    run_id: str | None = None
    node_id: str | None = None
    component_id: str | None = None


class SnapshotEvent(_Base):
    """Premier message d'une connexion : l'état courant, pour se resynchroniser."""

    type: Literal["snapshot"] = "snapshot"
    runs: list[dict[str, Any]]
    relays: dict[str, bool]
    locked: bool = False


Event = Annotated[
    RunStartedEvent
    | RunEndedEvent
    | NodeStartedEvent
    | NodeFinishedEvent
    | ComponentChangedEvent
    | ButtonPressEvent
    | LockChangedEvent
    | ErrorEvent
    | SnapshotEvent,
    Field(discriminator="type"),
]

EVENT_MODELS: tuple[type[BaseModel], ...] = (
    RunStartedEvent,
    RunEndedEvent,
    NodeStartedEvent,
    NodeFinishedEvent,
    ComponentChangedEvent,
    ButtonPressEvent,
    LockChangedEvent,
    ErrorEvent,
    SnapshotEvent,
)


def from_run_event(event: RunEvent) -> list[BaseModel]:
    """Un `RunEvent` du gestionnaire de runs devient un ou deux événements (échec : + `error`)."""
    base = {"run_id": event.run_id, "program_id": event.program_id}
    if event.kind == "run_started":
        return [RunStartedEvent(**base)]
    if event.kind == "run_ended":
        ended: list[BaseModel] = [RunEndedEvent(**base, outcome=event.outcome, error=event.error)]
        if event.outcome == "failed":
            message = event.error or "le programme a échoué"
            ended.append(ErrorEvent(source="run", message=message, run_id=event.run_id))
        return ended
    node = {**base, "script_id": event.script_id or "", "node_id": event.node_id or ""}
    cls = NodeStartedEvent if event.kind == "node_started" else NodeFinishedEvent
    return [cls(**node)]


class Subscription:
    """File d'événements d'un abonné ; s'itère avec `async for`."""

    def __init__(self, hub: EventHub, maxsize: int) -> None:
        self._hub = hub
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize)
        self.dropped = 0

    def _put(self, item: dict[str, Any] | None) -> None:
        if self._queue.full():
            self._queue.get_nowait()  # on garde les plus récents
            self.dropped += 1
        self._queue.put_nowait(item)

    def close(self) -> None:
        self._hub._subscribers.discard(self)

    async def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item


class EventHub:
    def __init__(self, maxsize: int = 1000) -> None:
        self._maxsize = maxsize
        self._subscribers: set[Subscription] = set()

    def subscribe(self) -> Subscription:
        subscription = Subscription(self, self._maxsize)
        self._subscribers.add(subscription)
        return subscription

    def publish(self, event: BaseModel) -> None:
        """Diffuse un événement (appelable depuis le code synchrone du moteur)."""
        data = event.model_dump(mode="json")
        for subscriber in list(self._subscribers):
            subscriber._put(data)

    def close(self) -> None:
        """Termine toutes les files (arrêt du service)."""
        for subscriber in list(self._subscribers):
            subscriber._put(None)
        self._subscribers.clear()
