"""Home Assistant : paramètres de connexion, test, liste des entités."""

import os
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, ValidationError

from halloween.api.components import StopRuns, commit
from halloween.api.deps import EngineDep
from halloween.api.errors import api_error
from halloween.api.schemas import IssueOut
from halloween.config.models import HomeAssistant
from halloween.drivers.base import HAError
from halloween.drivers.homeassistant import TOKEN_ENV, HttpHAClient
from halloween.ha_check import Capabilities, infer_capabilities

router = APIRouter(tags=["home-assistant"])


class HaConfigOut(BaseModel):
    """Paramètres de connexion ; le jeton n'est **jamais** renvoyé."""

    configured: bool
    url: str | None = None
    timeout_s: float = 5.0
    token_set: bool = False
    # `env` : HALLOWEEN_HA_TOKEN remplace le jeton enregistré
    token_source: Literal["config", "env", "none"] = "none"


class HaConfigIn(BaseModel):
    url: str
    # absent / null : jeton inchangé ; chaîne vide : le supprimer
    token: str | None = None
    timeout_s: Annotated[float, Field(gt=0, le=60)] = 5.0


class HaConfigSaved(BaseModel):
    config: HaConfigOut
    issues: list[IssueOut] = []


class HaTestIn(BaseModel):
    """Essai de connexion avec des paramètres non encore enregistrés (champs absents : actuels)."""

    url: str | None = None
    token: str | None = None
    timeout_s: Annotated[float, Field(gt=0, le=60)] | None = None


class HaTestOut(BaseModel):
    ok: bool
    message: str
    latency_ms: float | None = None
    error_type: str | None = None


class EntityOut(BaseModel):
    entity_id: str
    name: str
    state: str
    domain: str
    # Capacités déduites de Home Assistant (lumières) : pré-remplissent le formulaire.
    capabilities: Capabilities | None = None


def _describe(settings: HomeAssistant | None) -> HaConfigOut:
    if settings is None:
        return HaConfigOut(configured=False)
    from_env = bool(os.environ.get(TOKEN_ENV))
    token_set = from_env or bool(settings.token)
    return HaConfigOut(
        configured=True,
        url=settings.url,
        timeout_s=settings.timeout_s,
        token_set=token_set,
        token_source="env" if from_env else ("config" if settings.token else "none"),
    )


@router.get("/config/home-assistant", response_model=HaConfigOut, operation_id="get_ha_config")
async def get_ha_config(engine: EngineDep) -> HaConfigOut:
    return _describe(engine.config.home_assistant)


@router.put("/config/home-assistant", response_model=HaConfigSaved, operation_id="put_ha_config")
async def put_ha_config(
    body: HaConfigIn, engine: EngineDep, stop_runs: StopRuns = False
) -> HaConfigSaved:
    """Enregistre la connexion. Les scénarios en cours sont arrêtés si `stop_runs=true`."""
    async with engine.config_lock:
        current = engine.config.home_assistant
        token = current.token if (current and body.token is None) else (body.token or "")
        try:
            settings = HomeAssistant(url=body.url, token=token, timeout_s=body.timeout_s)
        except ValidationError as exc:
            raise api_error(422, "; ".join(e["msg"] for e in exc.errors())) from exc
        issues = await commit(
            engine, engine.config.model_copy(update={"home_assistant": settings}), stop_runs
        )
    return HaConfigSaved(
        config=_describe(settings), issues=[IssueOut.from_issue(i) for i in issues]
    )


@router.post(
    "/config/home-assistant/test", response_model=HaTestOut, operation_id="test_ha_connection"
)
async def test_ha_connection(body: HaTestIn, engine: EngineDep) -> HaTestOut:
    """Teste la connexion (réponse 200 même en cas d'échec : `ok=false` et la cause)."""
    current = engine.config.home_assistant
    url = body.url or (current.url if current else None)
    if not url:
        return HaTestOut(ok=False, message="aucune URL de Home Assistant configurée")
    timeout = body.timeout_s or (current.timeout_s if current else 5.0)
    token = (
        body.token
        if body.token is not None
        else (os.environ.get(TOKEN_ENV) or (current.token if current else ""))
    )
    if not token:
        return HaTestOut(ok=False, message="aucun jeton : le renseigner ou définir " + TOKEN_ENV)
    client = HttpHAClient(url, token, timeout)
    started = time.perf_counter()
    try:
        message = await client.check_connection()
    except HAError as exc:
        return HaTestOut(ok=False, message=str(exc), error_type=type(exc).__name__)
    finally:
        await client.close()
    return HaTestOut(
        ok=True, message=message, latency_ms=round((time.perf_counter() - started) * 1000, 1)
    )


@router.get("/ha/entities", response_model=list[EntityOut], operation_id="list_ha_entities")
async def list_ha_entities(
    engine: EngineDep, domain: Annotated[Literal["light", "switch"] | None, Query()] = None
) -> list[EntityOut]:
    """Entités de Home Assistant, à proposer dans les formulaires de lumières et d'interrupteurs."""
    settings = engine.config.home_assistant
    if settings is None or not (os.environ.get(TOKEN_ENV) or settings.token):
        raise api_error(409, "Home Assistant n'est pas configuré (URL et jeton)")
    client = HttpHAClient.from_config(settings)
    try:
        entities = await client.list_entities(domain)
    except HAError as exc:
        raise api_error(502, str(exc)) from exc
    finally:
        await client.close()
    return [
        EntityOut(
            entity_id=e.entity_id,
            name=e.name,
            state=e.state,
            domain=e.domain,
            capabilities=infer_capabilities(e.attributes) if e.domain == "light" else None,
        )
        for e in entities
        if e.domain in ("light", "switch")
    ]
