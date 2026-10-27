"""Client Home Assistant par l'API REST (`/api/services/...`, `/api/states`).

Authentification par jeton longue durée (`Authorization: Bearer`). Le jeton n'apparaît ni dans
`repr()` ni dans les messages d'erreur.
"""

from __future__ import annotations

import os
import socket
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from halloween.config.models import HomeAssistant
from halloween.drivers.base import (
    HAAuthError,
    HABadRequest,
    HAClient,
    HAError,
    HANotFound,
    HAServerError,
    HATimeout,
    HAUnreachable,
)
from halloween.log import get_logger

log = get_logger("homeassistant")

TOKEN_ENV = "HALLOWEEN_HA_TOKEN"
# Après un échec réseau, les appels suivants échouent aussitôt pendant ce délai (voir `_request`).
DEFAULT_COOLDOWN_S = 10.0


@dataclass(frozen=True)
class EntityInfo:
    """État d'une entité Home Assistant (extrait de `/api/states`)."""

    entity_id: str
    state: str
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]


class HttpHAClient(HAClient):
    def __init__(
        self,
        url: str,
        token: str,
        timeout_s: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
        cooldown_s: float = DEFAULT_COOLDOWN_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url.rstrip("/")
        self._timeout_s = timeout_s
        self._cooldown_s = cooldown_s
        self._clock = clock
        self._down_until = 0.0
        # Dernier résultat observé, pour afficher l'état de la connexion en permanence.
        self.last_ok_at: float | None = None
        self.last_error: str | None = None
        self._client = httpx.AsyncClient(
            base_url=self._url + "/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout_s,
            transport=transport,
        )

    def __repr__(self) -> str:
        return f"HttpHAClient(url={self._url!r})"

    @classmethod
    def from_config(
        cls,
        ha: HomeAssistant,
        env: Mapping[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> HttpHAClient:
        """`HALLOWEEN_HA_TOKEN`, si défini, remplace le jeton du fichier de configuration."""
        token = (os.environ if env is None else env).get(TOKEN_ENV) or ha.token
        return cls(ha.url, token, ha.timeout_s, transport)

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ requêtes

    async def _request(
        self, method: str, path: str, *, guarded: bool = False, **kwargs: Any
    ) -> httpx.Response:
        """Envoie la requête et traduit les échecs en erreurs typées (jamais le jeton).

        `guarded` (appels de scénario) : si Home Assistant vient d'être injoignable ou trop lent,
        l'appel échoue immédiatement pendant `cooldown_s` au lieu d'attendre `timeout_s` à chaque
        bloc, ce qui décalerait tout le scénario. Les appels explicites (test de connexion,
        liste d'entités) essaient toujours.
        """
        if guarded and self._clock() < self._down_until:
            remaining = self._down_until - self._clock()
            raise HAUnreachable(
                f"Home Assistant indisponible, nouvel essai dans {remaining:.0f} s ({self._url})"
            )
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            self._down_until = self._clock() + self._cooldown_s
            self.last_error = f"délai de {self._timeout_s:g} s dépassé"
            raise HATimeout(
                f"Home Assistant n'a pas répondu en {self._timeout_s:g} s ({self._url})"
            ) from exc
        except httpx.TransportError as exc:
            self._down_until = self._clock() + self._cooldown_s
            self.last_error = self._reason(exc)
            raise HAUnreachable(
                f"Home Assistant injoignable : {self.last_error} ({self._url})"
            ) from exc
        self._down_until = 0.0
        self.last_ok_at = time.time()  # Home Assistant répond (même par une erreur HTTP)
        self.last_error = None
        if response.status_code >= 400:
            raise self._http_error(response, method, path)
        return response

    @staticmethod
    def _reason(exc: BaseException) -> str:
        """Cause lisible d'un échec réseau, lue dans la chaîne d'exceptions (httpx → socket)."""
        chain: list[BaseException] = []
        current: BaseException | None = exc
        while current is not None and current not in chain:
            chain.append(current)
            current = current.__cause__ or current.__context__
        if any(isinstance(e, ConnectionRefusedError) for e in chain):
            return "connexion refusée"
        text = " ".join(str(e) for e in chain).lower()
        if any(isinstance(e, socket.gaierror) for e in chain) or any(
            marker in text for marker in ("name or service not known", "nodename nor servname")
        ):
            return "nom d'hôte introuvable"
        if "refused" in text:
            return "connexion refusée"
        return type(exc).__name__

    @staticmethod
    def _http_error(response: httpx.Response, method: str, path: str) -> HAError:
        status = response.status_code
        where = f"{method} /{path}"
        if status in (401, 403):
            return HAAuthError(f"jeton refusé par Home Assistant (HTTP {status})")
        if status == 404:
            return HANotFound(f"introuvable : {where} (HTTP 404) - vérifier l'URL et l'entité")
        if status in (400, 422):
            return HABadRequest(f"requête refusée par Home Assistant (HTTP {status}) : {where}")
        if status >= 500:
            return HAServerError(f"erreur interne de Home Assistant (HTTP {status}) : {where}")
        return HAError(f"Home Assistant : HTTP {status} sur {where}")

    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        await self._request("POST", f"api/services/{domain}/{service}", guarded=True, json=data)

    async def check_connection(self) -> str:
        """`GET /api/` ; retourne le message de Home Assistant (« API running. »)."""
        response = await self._request("GET", "api/")
        return str(response.json().get("message", ""))

    async def list_entities(self, domain: str | None = None) -> list[EntityInfo]:
        """Entités connues (filtrées par domaine : `light`, `switch`…), triées par identifiant."""
        response = await self._request("GET", "api/states")
        entities = [self._entity(item) for item in response.json()]
        if domain is not None:
            entities = [e for e in entities if e.domain == domain]
        return sorted(entities, key=lambda e: e.entity_id)

    async def get_entity(self, entity_id: str) -> EntityInfo | None:
        """État d'une entité, ou `None` si elle n'existe pas."""
        try:
            response = await self._request("GET", f"api/states/{entity_id}")
        except HANotFound:
            return None
        return self._entity(response.json())

    @staticmethod
    def _entity(item: dict[str, Any]) -> EntityInfo:
        attributes = item.get("attributes") or {}
        return EntityInfo(
            entity_id=item["entity_id"],
            state=str(item.get("state", "")),
            name=str(attributes.get("friendly_name") or item["entity_id"]),
            attributes=attributes,
        )
