"""Client Home Assistant par l'API REST (`/api/services/...`, `/api/states`).

Authentification par jeton longue durée (`Authorization: Bearer`). Le jeton n'apparaît ni dans
`repr()` ni dans les messages d'erreur.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from halloween.config.models import HomeAssistant
from halloween.drivers.base import HAClient, HAError
from halloween.log import get_logger

log = get_logger("homeassistant")

TOKEN_ENV = "HALLOWEEN_HA_TOKEN"


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
    ) -> None:
        self._url = url.rstrip("/")
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

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise HAError(f"Home Assistant : {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise HAError(f"Home Assistant : HTTP {response.status_code} sur {method} {path}")
        return response

    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        await self._request("POST", f"api/services/{domain}/{service}", json=data)

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
        except HAError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise
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
