"""Interfaces des périphériques. L'interpréteur ne dépend que de ces classes : le matériel réel
(GPIO, Home Assistant) et les versions fictives des tests les implémentent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from halloween.log import get_logger

log = get_logger("drivers")

ButtonEventKind = Literal["short", "long", "double"]


@dataclass(frozen=True)
class ButtonEvent:
    button_id: str
    event: ButtonEventKind


ButtonHandler = Callable[[ButtonEvent], Awaitable[None] | None]


class RelayDriver(ABC):
    """Pilote les relais par leur id. `on` est l'état logique : le pilote gère `active_low`."""

    @abstractmethod
    async def set(self, relay_id: str, on: bool) -> None: ...

    @abstractmethod
    def is_on(self, relay_id: str) -> bool:
        """Dernier état commandé."""

    @abstractmethod
    async def all_off(self) -> None:
        """Coupe tous les relais (arrêt, reprise, erreur grave)."""

    async def close(self) -> None:  # noqa: B027 - facultatif
        """Libère les ressources matérielles."""


class ButtonDriver:
    """Émet des événements d'appui (court, long, double) vers les abonnés.

    Classe de base : les pilotes réels appellent `_emit` quand un appui est reconnu."""

    def __init__(self) -> None:
        self._handlers: list[ButtonHandler] = []

    def subscribe(self, handler: ButtonHandler) -> Callable[[], None]:
        """Abonne `handler` ; retourne la fonction de désabonnement."""
        self._handlers.append(handler)
        return lambda: self._handlers.remove(handler) if handler in self._handlers else None

    async def _emit(self, event: ButtonEvent) -> None:
        for handler in list(self._handlers):
            try:
                result = handler(event)
                if result is not None:
                    await result
            except Exception:
                # Un abonné défaillant ne doit pas empêcher les autres de recevoir l'appui.
                log.exception("abonné du bouton en échec", extra={"button": event.button_id})

    async def start(self) -> None:  # noqa: B027 - facultatif
        """Démarre la surveillance des entrées."""

    async def close(self) -> None:  # noqa: B027 - facultatif
        """Arrête la surveillance et libère les broches."""


class HAError(Exception):
    """Échec d'un appel à Home Assistant (réseau, authentification, entité inconnue…).

    Les sous-classes permettent d'afficher un message précis et d'agir selon la cause.
    """


class HAUnreachable(HAError):
    """Home Assistant ne répond pas du tout : hôte introuvable, connexion refusée, réseau coupé."""


class HATimeout(HAError):
    """Home Assistant n'a pas répondu dans le délai configuré (`timeout_s`)."""


class HAAuthError(HAError):
    """Jeton refusé (HTTP 401 / 403)."""


class HANotFound(HAError):
    """Service, entité ou chemin inconnu (HTTP 404) : URL incorrecte ou entité supprimée."""


class HABadRequest(HAError):
    """Requête refusée par Home Assistant (HTTP 400 / 422) : paramètre invalide."""


class HAServerError(HAError):
    """Erreur interne de Home Assistant (HTTP 5xx)."""


class HAClient(ABC):
    """Client Home Assistant. Les pilotes n'implémentent que `call_service`."""

    @abstractmethod
    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        """`POST /api/services/<domain>/<service>` avec `data` ; lève `HAError` en cas d'échec."""

    async def light_on(
        self,
        entity_id: str,
        *,
        rgb_color: tuple[int, int, int] | None = None,
        brightness: int | None = None,
        transition: float | None = None,
    ) -> None:
        data: dict[str, Any] = {"entity_id": entity_id}
        if rgb_color is not None:
            data["rgb_color"] = list(rgb_color)
        if brightness is not None:
            data["brightness"] = brightness
        if transition is not None:
            data["transition"] = transition
        await self.call_service("light", "turn_on", data)

    async def light_off(self, entity_id: str) -> None:
        await self.call_service("light", "turn_off", {"entity_id": entity_id})

    async def switch_on(self, entity_id: str) -> None:
        await self.call_service("switch", "turn_on", {"entity_id": entity_id})

    async def switch_off(self, entity_id: str) -> None:
        await self.call_service("switch", "turn_off", {"entity_id": entity_id})

    async def close(self) -> None:  # noqa: B027 - facultatif
        """Ferme les connexions."""
