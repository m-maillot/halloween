"""Exécution : runs, arrêts, déclencheurs."""

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from halloween.api.deps import EngineDep
from halloween.api.errors import api_error
from halloween.api.lock import check_code
from halloween.api.schemas import IssueOut, RunOut
from halloween.issues import errors, warnings
from halloween.program.runs import AlreadyRunning, Policy, TooManyRuns
from halloween.triggers import Trigger, dump_triggers, parse_triggers, validate_triggers

router = APIRouter(tags=["exécution"])

TRIGGERS_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {"$ref": "#/components/schemas/ButtonTrigger"},
                            {"$ref": "#/components/schemas/ScheduleTrigger"},
                        ],
                        "discriminator": {"propertyName": "source"},
                    },
                }
            }
        },
    }
}


class StartRun(BaseModel):
    program_id: str
    # Que faire si ce programme tourne déjà : ignorer (409), le redémarrer, ou le mettre en file.
    policy: Policy = "ignore"
    # Obligatoire quand le moteur est verrouillé ; ne vaut que pour ce lancement.
    code: str | None = None


class StopAll(BaseModel):
    stopped: int


class TriggersOut(BaseModel):
    triggers: list[Trigger]
    # Entrées illisibles du fichier et déclencheurs écartés (programme ou bouton inconnu).
    issues: list[IssueOut] = []


# --------------------------------------------------------------------------- runs


@router.get("/runs", response_model=list[RunOut], operation_id="list_runs")
async def list_runs(engine: EngineDep) -> list[RunOut]:
    """Runs actifs (en cours ou en file)."""
    return [RunOut(**run.to_json()) for run in engine.manager.active]


@router.post(
    "/runs",
    response_model=RunOut,
    status_code=201,
    operation_id="start_run",
    responses={
        401: {"description": "Code incorrect"},
        404: {"description": "Programme inconnu"},
        409: {"description": "Le programme tourne déjà (politique `ignore`)"},
        422: {"description": "Programme écarté : incompatible avec la configuration"},
        423: {"description": "Verrouillé : le code est obligatoire"},
        429: {"description": "Trop de runs simultanés, ou trop d'essais de code"},
    },
)
async def start_run(body: StartRun, engine: EngineDep) -> RunOut:
    """Lance un programme. Plusieurs programmes différents peuvent tourner en même temps.

    Verrouillé, le `code` est exigé à chaque lancement (il n'ouvre aucune session).
    """
    if engine.lock.locked:
        if body.code is None:
            raise api_error(423, "verrouillé : le code est obligatoire pour lancer")
        await check_code(engine, body.code)
    program = engine.programs.get(body.program_id)
    if program is None:
        if engine.store.get_program(body.program_id) is None:
            raise api_error(404, f"programme inconnu : {body.program_id}")
        raise api_error(
            422, "programme écarté : incompatible avec la configuration (voir /api/status)"
        )
    try:
        run = await engine.manager.start(program, body.policy)
    except AlreadyRunning as exc:
        raise api_error(409, str(exc), run_id=exc.run.id) from exc
    except TooManyRuns as exc:
        raise api_error(429, str(exc)) from exc
    return RunOut(**run.to_json())


@router.post("/runs/stop", response_model=StopAll, operation_id="stop_all_runs")
async def stop_all_runs(engine: EngineDep) -> StopAll:
    """**Arrêt global** : tous les runs, puis état de repos complet (relais, lumières)."""
    count = len(engine.manager.active)
    await engine.manager.stop_all()
    return StopAll(stopped=count)


@router.post(
    "/runs/{run_id}/stop",
    response_model=RunOut,
    operation_id="stop_run",
    responses={404: {"description": "Run inconnu ou déjà terminé"}},
)
async def stop_run(run_id: str, engine: EngineDep) -> RunOut:
    """Arrête un seul run ; les composants qu'il pilotait reviennent au repos (sauf reprise)."""
    run = engine.manager.get(run_id)
    if run is None:
        raise api_error(404, f"run inconnu ou déjà terminé : {run_id}")
    await engine.manager.stop(run_id)
    return RunOut(**run.to_json())


# --------------------------------------------------------------------------- déclencheurs


def _read_triggers(engine) -> TriggersOut:
    triggers, issues = parse_triggers(engine.store.load_triggers())
    issues += validate_triggers(triggers, engine.config, set(engine.programs))
    return TriggersOut(triggers=triggers, issues=[IssueOut.from_issue(i) for i in issues])


@router.get("/triggers", response_model=TriggersOut, operation_id="get_triggers")
async def get_triggers(engine: EngineDep) -> TriggersOut:
    """Déclencheurs enregistrés, avec les problèmes qui en écartent certains."""
    return _read_triggers(engine)


@router.put(
    "/triggers",
    response_model=TriggersOut,
    operation_id="put_triggers",
    openapi_extra=TRIGGERS_BODY,
    responses={422: {"description": "Déclencheur invalide (forme, bouton ou programme inconnu)"}},
)
async def put_triggers(request: Request, engine: EngineDep) -> TriggersOut:
    """Remplace tous les déclencheurs ; effet immédiat. Un seul déclencheur invalide refuse tout."""
    body: Any = await _read_list(request)
    triggers, shape_issues = parse_triggers(body)
    if shape_issues:
        raise api_error(422, "déclencheur invalide", shape_issues)
    problems = validate_triggers(triggers, engine.config, set(engine.programs))
    if errors(problems):
        raise api_error(422, "déclencheur invalide", errors(problems))
    async with engine.config_lock:
        engine.store.save_triggers(dump_triggers(triggers))
        engine.reload_content()
    return TriggersOut(
        triggers=triggers, issues=[IssueOut.from_issue(i) for i in warnings(problems)]
    )


async def _read_list(request: Request) -> list[Any]:
    try:
        body = await request.json()
    except ValueError as exc:
        raise api_error(400, f"JSON invalide : {exc}") from exc
    if not isinstance(body, list):
        raise api_error(422, "une liste JSON de déclencheurs est attendue")
    return body
