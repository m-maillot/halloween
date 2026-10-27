"""Programmes : enregistrement versionné, validation, simulation."""

import asyncio
import json
import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Header, Request, Response
from pydantic import BaseModel, Field, ValidationError

from halloween.api.deps import EngineDep
from halloween.api.errors import api_error
from halloween.api.schemas import IssueOut
from halloween.app import Engine
from halloween.drivers.base import ButtonEventKind
from halloween.issues import Issue, errors, issues_from_validation_error, warnings
from halloween.program.models import CallNode, Program
from halloween.program.simulation import simulate
from halloween.program.validation import validate_program
from halloween.store import RevisionConflict

router = APIRouter(tags=["programmes"])

PROGRAM_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Program"}}},
    }
}


class ProgramSummary(BaseModel):
    id: str
    name: str
    revision: int
    show: bool
    show_order: int | None = None
    max_duration_s: float | None = None
    scripts: int
    # Faux si le programme est écarté (blocs incompatibles avec la configuration actuelle).
    valid: bool
    running: bool = False


class ProgramSaved(BaseModel):
    program: Program
    warnings: list[IssueOut] = []


class ValidationReport(BaseModel):
    valid: bool
    issues: list[IssueOut]


class ButtonPress(BaseModel):
    t: Annotated[float, Field(ge=0)]
    button: str
    event: ButtonEventKind = "short"


class SimulateRequest(BaseModel):
    """Soit `program_id` (programme enregistré), soit `program` (brouillon de l'éditeur)."""

    program_id: str | None = None
    program: dict[str, Any] | None = None
    seed: int = 0
    button_presses: list[ButtonPress] = []
    horizon_s: Annotated[float, Field(gt=0, le=86_400)] = 3600


class TimelineEntryOut(BaseModel):
    t: float
    component: str
    action: str
    data: dict[str, Any] = {}


class SimulationOut(BaseModel):
    status: Literal["completed", "timeout", "horizon", "deadlock", "truncated", "failed"]
    duration_s: float
    timeline: list[TimelineEntryOut]
    still_on: list[str] = []
    error: str | None = None


# --------------------------------------------------------------------------- utilitaires


async def read_json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise api_error(400, f"JSON invalide : {exc}") from exc
    if not isinstance(body, dict):
        raise api_error(422, "un objet JSON est attendu")
    return body


def parse_program(raw: dict[str, Any]) -> tuple[Program | None, list[Issue]]:
    """Valide la forme ; les erreurs sont localisées sur le bloc fautif (`node_id`)."""
    try:
        return Program.model_validate(raw), []
    except ValidationError as exc:
        return None, issues_from_validation_error(exc, raw)


def stored_programs(engine: Engine) -> dict[str, Program]:
    return engine.store.load_programs().programs


def check_semantics(engine: Engine, program: Program) -> list[Issue]:
    others = {**stored_programs(engine), program.id: program}
    return validate_program(program, engine.config, others)


def parse_if_match(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.fullmatch(r'\s*(?:W/)?"?(\d+)"?\s*', value)
    if not match:
        raise api_error(400, 'If-Match doit contenir un numéro de révision (ex. "3")')
    return int(match.group(1))


def etag(revision: int) -> str:
    return f'"{revision}"'


# --------------------------------------------------------------------------- routes


@router.get("/programs", response_model=list[ProgramSummary], operation_id="list_programs")
async def list_programs(engine: EngineDep) -> list[ProgramSummary]:
    running = {r.program.id for r in engine.manager.active}
    return [
        ProgramSummary(
            id=p.id,
            name=p.name,
            revision=p.revision,
            show=p.show,
            show_order=p.show_order,
            max_duration_s=p.max_duration_s,
            scripts=len(p.scripts),
            valid=p.id in engine.programs,
            running=p.id in running,
        )
        for p in sorted(
            stored_programs(engine).values(),
            key=lambda p: (p.show_order is None, p.show_order or 0, p.name.lower()),
        )
    ]


@router.get(
    "/programs/{program_id}",
    response_model=Program,
    response_model_by_alias=True,
    operation_id="get_program",
    responses={404: {"description": "Programme inconnu"}},
)
async def get_program(program_id: str, engine: EngineDep, response: Response) -> Program:
    program = engine.store.get_program(program_id)
    if program is None:
        raise api_error(404, f"programme inconnu : {program_id}")
    response.headers["ETag"] = etag(program.revision)
    return program


@router.put(
    "/programs/{program_id}",
    response_model=ProgramSaved,
    response_model_by_alias=True,
    operation_id="put_program",
    openapi_extra=PROGRAM_BODY,
    responses={
        412: {"description": "Révision périmée (voir `current_revision` dans `detail`)"},
        422: {"description": "Programme invalide : problèmes localisés par `node_id`"},
        428: {"description": "`If-Match` obligatoire pour modifier un programme existant"},
    },
)
async def put_program(
    program_id: str,
    request: Request,
    response: Response,
    engine: EngineDep,
    if_match: Annotated[str | None, Header()] = None,
) -> ProgramSaved:
    """Crée (sans `If-Match`, ou `0`) ou remplace (`If-Match: "<révision>"`) un programme.

    Le programme est validé (forme, composants, modes, capacités, appels) avant d'être enregistré ;
    un programme invalide n'est jamais écrit.
    """
    raw = await read_json(request)
    raw.setdefault("id", program_id)
    if raw["id"] != program_id:
        raise api_error(422, "l'id du corps ne correspond pas à celui de l'URL")
    program, shape_issues = parse_program(raw)
    if program is None:
        raise api_error(422, "programme invalide", shape_issues)
    problems = check_semantics(engine, program)
    if errors(problems):
        raise api_error(422, "programme invalide", errors(problems))

    expected = parse_if_match(if_match)
    existing = engine.store.get_program(program_id)
    if existing is not None and expected is None:
        raise api_error(
            428, "If-Match (révision attendue) est obligatoire pour modifier un programme"
        )
    try:
        saved = engine.store.save_program(program, expected)
    except RevisionConflict as exc:
        raise api_error(
            412,
            "le programme a changé depuis sa lecture : le relire avant de réenregistrer",
            current_revision=exc.current,
        ) from exc
    engine.reload_content()
    response.status_code = 200 if existing is not None else 201
    response.headers["ETag"] = etag(saved.revision)
    return ProgramSaved(
        program=saved, warnings=[IssueOut.from_issue(i) for i in warnings(problems)]
    )


@router.delete("/programs/{program_id}", status_code=204, operation_id="delete_program")
async def delete_program(program_id: str, engine: EngineDep) -> None:
    if engine.store.get_program(program_id) is None:
        raise api_error(404, f"programme inconnu : {program_id}")
    if any(r.program.id == program_id for r in engine.manager.active):
        raise api_error(409, "ce programme est en cours d'exécution : l'arrêter d'abord")
    used = [
        f"déclencheur `{t.id}`"
        for t in engine.triggers.triggers
        if getattr(t, "program", None) == program_id
    ]
    for other in stored_programs(engine).values():
        if other.id != program_id and any(
            isinstance(n, CallNode) and n.program_id == program_id for n in other.nodes()
        ):
            used.append(f"programme « {other.name} » (appel)")
    if used:
        raise api_error(409, "programme utilisé : " + " ; ".join(used))
    engine.store.delete_program(program_id)
    engine.reload_content()


@router.post(
    "/programs/validate",
    response_model=ValidationReport,
    operation_id="validate_program",
    openapi_extra=PROGRAM_BODY,
)
async def validate(request: Request, engine: EngineDep) -> ValidationReport:
    """Valide sans enregistrer (toujours 200) : erreurs et avertissements, localisés par bloc."""
    raw = await read_json(request)
    program, issues = parse_program(raw)
    if program is not None:
        issues = check_semantics(engine, program)
    return ValidationReport(
        valid=not errors(issues), issues=[IssueOut.from_issue(i) for i in issues]
    )


@router.post(
    "/simulate",
    response_model=SimulationOut,
    operation_id="simulate_program",
    responses={422: {"description": "Programme invalide ou introuvable"}},
)
async def simulate_program(body: SimulateRequest, engine: EngineDep) -> SimulationOut:
    """Simule un programme en temps virtuel : timeline des commandes, sans rien actionner."""
    if (body.program_id is None) == (body.program is None):
        raise api_error(422, "indiquer soit `program_id`, soit `program`")
    if body.program is not None:
        program, issues = parse_program(body.program)
        if program is None:
            raise api_error(422, "programme invalide", issues)
    else:
        program = engine.store.get_program(body.program_id or "")
        if program is None:
            raise api_error(404, f"programme inconnu : {body.program_id}")
    problems = check_semantics(engine, program)
    if errors(problems):
        raise api_error(422, "programme invalide", errors(problems))
    programs = {**stored_programs(engine), program.id: program}
    result = await asyncio.to_thread(
        simulate,
        program,
        engine.config,
        programs,
        seed=body.seed,
        button_presses=[(p.t, p.button, p.event) for p in body.button_presses],
        horizon_s=body.horizon_s,
    )
    return SimulationOut(**result.to_json())
