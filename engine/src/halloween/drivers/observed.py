"""Enveloppes qui signalent les changements d'état des composants (événements temps réel)."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from halloween.drivers.base import HAClient, RelayDriver


class ObservedRelayDriver(RelayDriver):
    """Relais : `on_change(relay_id, allumé)` après chaque commande réussie."""

    def __init__(
        self,
        inner: RelayDriver,
        relay_ids: Iterable[str],
        on_change: Callable[[str, bool], None],
    ) -> None:
        self._inner = inner
        self._ids = list(relay_ids)
        self._on_change = on_change

    async def set(self, relay_id: str, on: bool) -> None:
        await self._inner.set(relay_id, on)
        self._on_change(relay_id, on)

    def is_on(self, relay_id: str) -> bool:
        return self._inner.is_on(relay_id)

    async def all_off(self) -> None:
        was_on = [r for r in self._ids if self._inner.is_on(r)]
        await self._inner.all_off()
        for relay_id in was_on:
            self._on_change(relay_id, False)

    async def close(self) -> None:
        await self._inner.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class ObservedHAClient(HAClient):
    """Home Assistant : `on_change(domain, service, données)` après chaque appel réussi."""

    def __init__(
        self, inner: HAClient, on_change: Callable[[str, str, dict[str, Any]], None]
    ) -> None:
        self._inner = inner
        self._on_change = on_change

    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        await self._inner.call_service(domain, service, data)
        self._on_change(domain, service, data)

    async def close(self) -> None:
        await self._inner.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
