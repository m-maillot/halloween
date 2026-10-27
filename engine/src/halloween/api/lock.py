"""Verrouillage par code : état, verrouiller / déverrouiller, définir ou changer le code."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from halloween.api.deps import EngineDep
from halloween.api.errors import api_error
from halloween.api.schemas import LockOut
from halloween.app import Engine
from halloween.events import LockChangedEvent
from halloween.lock import CODE_PATTERN, NoCode

router = APIRouter(tags=["verrouillage"])


class Code(BaseModel):
    code: str


class NewCode(BaseModel):
    new_code: str = Field(pattern=CODE_PATTERN, description="4 à 8 chiffres")
    # Obligatoire quand un code existe déjà.
    old_code: str | None = None


def lock_out(engine: Engine) -> LockOut:
    return LockOut(locked=engine.lock.locked, has_code=engine.lock.has_code)


def check_code(engine: Engine, code: str) -> None:
    """Vérifie un code ; `401` s'il est faux."""
    if not engine.lock.verify(code):
        raise api_error(401, "code incorrect")


@router.get("/lock", response_model=LockOut, operation_id="get_lock")
async def get_lock(engine: EngineDep) -> LockOut:
    """État du verrouillage (jamais l'empreinte du code)."""
    return lock_out(engine)


@router.post(
    "/lock",
    response_model=LockOut,
    operation_id="lock",
    responses={409: {"description": "Aucun code défini : en définir un d'abord"}},
)
async def lock(engine: EngineDep) -> LockOut:
    """Verrouille (sans code, comme le cadenas de l'interface). Conservé au redémarrage."""
    was_locked = engine.lock.locked
    try:
        engine.lock.lock()
    except NoCode as exc:
        raise api_error(409, str(exc)) from exc
    if not was_locked:
        engine.hub.publish(LockChangedEvent(locked=True))
    return lock_out(engine)


@router.post(
    "/unlock",
    response_model=LockOut,
    operation_id="unlock",
    responses={
        401: {"description": "Code incorrect"},
        409: {"description": "Aucun code défini"},
    },
)
async def unlock(body: Code, engine: EngineDep) -> LockOut:
    """Déverrouille avec le code."""
    if not engine.lock.has_code:
        raise api_error(409, "aucun code défini")
    check_code(engine, body.code)
    was_locked = engine.lock.locked
    engine.lock.unlock()
    if was_locked:
        engine.hub.publish(LockChangedEvent(locked=False))
    return lock_out(engine)


@router.put(
    "/lock/code",
    response_model=LockOut,
    operation_id="put_lock_code",
    responses={
        401: {"description": "Ancien code manquant ou incorrect"},
        423: {"description": "Verrouillé : déverrouiller d'abord"},
    },
)
async def put_lock_code(body: NewCode, engine: EngineDep) -> LockOut:
    """Définit le code, ou le change (`old_code` alors obligatoire). Refusé si verrouillé."""
    if engine.lock.has_code:
        if body.old_code is None:
            raise api_error(401, "l'ancien code est obligatoire pour changer le code")
        check_code(engine, body.old_code)
    engine.lock.set_code(body.new_code)
    return lock_out(engine)
