"""Composants : relais, boutons, lumières, interrupteurs (CRUD, test manuel, catalogue)."""

import asyncio
import re
import unicodedata
from typing import Annotated, Generic, Literal, TypeVar

from fastapi import APIRouter, Query
from pydantic import BaseModel

from halloween.api import schemas
from halloween.api.deps import EngineDep
from halloween.api.errors import api_error
from halloween.app import Engine, StartupError
from halloween.config.models import (
    AppConfig,
    Button,
    Component,
    Light,
    Relay,
    RelayMode,
    RestState,
    Slug,
    Switch,
)
from halloween.config.validation import validate_config
from halloween.drivers.base import HAError
from halloween.issues import Issue, errors, warnings
from halloween.program.actions import ActionFailed
from halloween.program.interpreter import ExecutionError
from halloween.program.models import (
    ButtonCondition,
    LightNode,
    RelayIsCondition,
    RelayNode,
    SwitchNode,
)

router = APIRouter(tags=["composants"])

C = TypeVar("C")

_BUILTIN = "builtin:"


class RelayIn(Relay):
    id: Slug | None = None


class ButtonIn(Button):
    id: Slug | None = None


class LightIn(Light):
    id: Slug | None = None


class SwitchIn(Switch):
    id: Slug | None = None


class ImageUrl(BaseModel):
    image_url: str | None = (
        None  # None pour une icône intégrée (`builtin:`) : l'interface la résout
    )


class RelayOut(Relay, ImageUrl): ...


class ButtonOut(Button, ImageUrl): ...


class LightOut(Light, ImageUrl): ...


class SwitchOut(Switch, ImageUrl): ...


class Result(BaseModel, Generic[C]):
    component: C
    # Avertissements de configuration et programmes devenus invalides par ce changement.
    issues: list[schemas.IssueOut] = []


class Devices(BaseModel):
    """Catalogue complet, pour construire l'éditeur de blocs et le tableau de bord."""

    relays: list[RelayOut]
    buttons: list[ButtonOut]
    lights: list[LightOut]
    switches: list[SwitchOut]
    rest_state: dict[str, RestState]


KINDS: dict[str, tuple[type[Component], type[Component], type[Component], str]] = {
    "relays": (Relay, RelayIn, RelayOut, "relais"),
    "buttons": (Button, ButtonIn, ButtonOut, "bouton"),
    "lights": (Light, LightIn, LightOut, "lumière"),
    "switches": (Switch, SwitchIn, SwitchOut, "interrupteur"),
}


def image_url(image: str | None) -> str | None:
    if not image or image.startswith(_BUILTIN):
        return None
    return f"/api/images/{image}"


def to_out(kind: str, component: Component):
    out_class = KINDS[kind][2]
    return out_class(**component.model_dump(), image_url=image_url(component.image))


def slugify(name: str, taken: set[str]) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:56] or "composant"
    candidate, n = base, 1
    while candidate in taken:
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def all_ids(config: AppConfig) -> set[str]:
    return {c.id for kind in KINDS for c in getattr(config, kind)}


# --------------------------------------------------------------------------- utilisation


def usages(engine: Engine, component_id: str) -> list[str]:
    """Où un composant est utilisé (programmes, déclencheurs, état de repos)."""
    found: list[str] = []
    for program in engine.store.load_programs().programs.values():
        for node in program.nodes():
            target = getattr(node, "target", None)
            condition = getattr(node, "condition", None)
            if target == component_id or (
                isinstance(condition, ButtonCondition | RelayIsCondition)
                and condition.id == component_id
            ):
                found.append(f"programme « {program.name} » (bloc {node.id})")
    for trigger in engine.triggers.triggers if engine.triggers else []:
        if getattr(trigger, "button", None) == component_id:
            found.append(f"déclencheur `{trigger.id}`")
    if component_id in engine.config.rest_state:
        found.append("état de repos")
    return found


def _strip_cosmetics(config: AppConfig) -> dict:
    data = config.model_dump(mode="json")
    data.pop("rest_state", None)  # le repos se lit à l'usage : pas besoin de reconstruire
    for kind in KINDS:
        for component in data[kind]:
            component.pop("name", None)
            component.pop("image", None)
    return data


def is_structural(old: AppConfig, new: AppConfig) -> bool:
    """Vrai si le changement touche autre chose que noms, images et état de repos."""
    return _strip_cosmetics(old) != _strip_cosmetics(new)


async def commit(engine: Engine, new_config: AppConfig, stop_runs: bool) -> list[Issue]:
    """Valide puis applique `new_config` ; retourne les avertissements / programmes écartés."""
    issues = validate_config(new_config)
    if errors(issues):
        raise api_error(422, "configuration invalide", errors(issues))
    if is_structural(engine.config, new_config):
        active = engine.manager.active
        if active and not stop_runs:
            names = ", ".join(r.program.id for r in active)
            raise api_error(
                409,
                f"des scénarios tournent ({names}) : ils seraient arrêtés par ce changement ; "
                "relancer avec stop_runs=true pour confirmer",
            )
        try:
            report = await engine.apply_config(new_config)
        except StartupError as exc:
            raise api_error(422, str(exc), exc.issues) from exc
        return [*warnings(issues), *report.issues]
    engine.update_cosmetics(new_config)
    return warnings(issues)


def check_image(engine: Engine, component: Component) -> None:
    image = component.image
    if image and not image.startswith(_BUILTIN) and not (engine.images_dir / image).is_file():
        raise api_error(
            422, f"image introuvable : {image} (téléverser d'abord via POST /api/images)"
        )


StopRuns = Annotated[
    bool, Query(description="Autorise l'arrêt des scénarios en cours si le changement l'exige.")
]


# --------------------------------------------------------------------------- routes par type


def _register(kind: str) -> None:
    model, model_in, out_class, label = KINDS[kind]
    singular = {"relays": "relay", "buttons": "button", "lights": "light", "switches": "switch"}[
        kind
    ]
    path = f"/components/{kind}"
    # Nom propre dans l'OpenAPI (`RelayResult` plutôt que `Result_RelayOut_`).
    result_class = type(f"{singular.capitalize()}Result", (Result[out_class],), {})

    def find(engine: Engine, component_id: str):
        for item in getattr(engine.config, kind):
            if item.id == component_id:
                return item
        raise api_error(404, f"{label} inconnu : {component_id}")

    @router.get(path, response_model=list[out_class], operation_id=f"list_{kind}")
    async def list_components(engine: EngineDep):
        return [to_out(kind, c) for c in getattr(engine.config, kind)]

    @router.post(
        path, response_model=result_class, status_code=201, operation_id=f"create_{singular}"
    )
    async def create_component(body: model_in, engine: EngineDep, stop_runs: StopRuns = False):
        async with engine.config_lock:
            config = engine.config
            component_id = body.id or slugify(body.name, all_ids(config))
            if component_id in all_ids(config):
                raise api_error(409, f"id déjà utilisé : {component_id}")
            component = model(**{**body.model_dump(), "id": component_id})
            check_image(engine, component)
            new = config.model_copy(update={kind: [*getattr(config, kind), component]})
            issues = await commit(engine, new, stop_runs)
        return result_class(
            component=to_out(kind, component),
            issues=[schemas.IssueOut.from_issue(i) for i in issues],
        )

    @router.get(
        f"{path}/{{component_id}}", response_model=out_class, operation_id=f"get_{singular}"
    )
    async def get_component(component_id: str, engine: EngineDep):
        return to_out(kind, find(engine, component_id))

    @router.put(
        f"{path}/{{component_id}}",
        response_model=result_class,
        operation_id=f"update_{singular}",
    )
    async def update_component(
        component_id: str, body: model_in, engine: EngineDep, stop_runs: StopRuns = False
    ):
        async with engine.config_lock:
            find(engine, component_id)
            if body.id is not None and body.id != component_id:
                raise api_error(422, "l'identifiant d'un composant n'est pas modifiable")
            component = model(**{**body.model_dump(), "id": component_id})
            check_image(engine, component)
            config = engine.config
            items = [component if c.id == component_id else c for c in getattr(config, kind)]
            issues = await commit(engine, config.model_copy(update={kind: items}), stop_runs)
        return result_class(
            component=to_out(kind, component),
            issues=[schemas.IssueOut.from_issue(i) for i in issues],
        )

    @router.delete(f"{path}/{{component_id}}", status_code=204, operation_id=f"delete_{singular}")
    async def delete_component(component_id: str, engine: EngineDep, stop_runs: StopRuns = False):
        async with engine.config_lock:
            find(engine, component_id)
            used = usages(engine, component_id)
            if used:
                raise api_error(409, f"{label} utilisé : " + " ; ".join(used))
            config = engine.config
            items = [c for c in getattr(config, kind) if c.id != component_id]
            await commit(engine, config.model_copy(update={kind: items}), stop_runs)

    # noms lisibles dans l'OpenAPI
    for fn in (
        list_components,
        create_component,
        get_component,
        update_component,
        delete_component,
    ):
        fn.__name__ = f"{fn.__name__}_{kind}"


for _kind in KINDS:
    _register(_kind)


@router.get("/devices", response_model=Devices, operation_id="get_devices")
async def get_devices(engine: EngineDep) -> Devices:
    """Catalogue complet des composants avec leurs capacités."""
    config = engine.config
    return Devices(
        relays=[to_out("relays", c) for c in config.relays],
        buttons=[to_out("buttons", c) for c in config.buttons],
        lights=[to_out("lights", c) for c in config.lights],
        switches=[to_out("switches", c) for c in config.switches],
        rest_state=config.rest_state,
    )


# --------------------------------------------------------------------------- test manuel


class ComponentTest(BaseModel):
    """Commande manuelle d'un composant, sans écrire de programme."""

    action: Literal["on", "off", "trigger", "press"]
    # lumières (`on`)
    rgb_color: tuple[int, int, int] | None = None
    brightness: int | None = None
    transition: float | None = None
    # boutons (`press`)
    event: Literal["short", "long", "double"] = "short"


class TestResult(BaseModel):
    __test__ = False  # pas une classe de test pour pytest

    ok: bool = True
    message: str


@router.post(
    "/components/{kind}/{component_id}/test",
    response_model=TestResult,
    operation_id="test_component",
    responses={502: {"description": "L'appareil a refusé ou n'a pas répondu"}},
)
async def test_component(
    kind: Literal["relays", "buttons", "lights", "switches"],
    component_id: str,
    body: ComponentTest,
    engine: EngineDep,
) -> TestResult:
    """Commande un composant à la main : relais on/off/impulsion, lumière, interrupteur, appui."""
    component = next((c for c in getattr(engine.config, kind) if c.id == component_id), None)
    if component is None:
        raise api_error(404, f"composant inconnu : {component_id}")
    actions = engine.manager.actions
    try:
        if kind == "buttons":
            if body.action != "press":
                raise api_error(422, "un bouton se teste avec action=press")
            await engine.buttons.simulate(component_id, body.event)
            return TestResult(message=f"appui {body.event} simulé sur {component.name}")
        if kind == "relays":
            if body.action == "trigger":
                node = RelayNode(id="test", type="relay", target=component_id, action="trigger")
                if component.mode is RelayMode.LATCHED:
                    raise api_error(
                        422, "relais maintenu : utiliser on / off (trigger est pour l'impulsion)"
                    )
            elif body.action in ("on", "off"):
                node = RelayNode(id="test", type="relay", target=component_id, state=body.action)
            else:
                raise api_error(422, "action invalide pour un relais (on, off, trigger)")
            node = node.model_copy(update={"on_error": "abort"})
        elif kind == "lights":
            if body.action not in ("on", "off"):
                raise api_error(422, "action invalide pour une lumière (on, off)")
            unsupported = [
                label
                for value, supported, label in (
                    (body.rgb_color, component.supports_color, "couleur"),
                    (body.brightness, component.supports_brightness, "luminosité"),
                    (body.transition, component.supports_transition, "transition"),
                )
                if value is not None and not supported
            ]
            if unsupported and body.action == "on":
                raise api_error(422, f"{component.name} ne gère pas : {', '.join(unsupported)}")
            node = LightNode(
                id="test",
                type="light",
                target=component_id,
                state=body.action,
                rgb_color=body.rgb_color,
                brightness=body.brightness,
                transition=body.transition,
                on_error="abort",
            )
        else:
            if body.action not in ("on", "off"):
                raise api_error(422, "action invalide pour un interrupteur (on, off)")
            node = SwitchNode(
                id="test", type="switch", target=component_id, state=body.action, on_error="abort"
            )
        await actions.execute(node)
    except ExecutionError as exc:
        raise api_error(422, str(exc)) from exc
    except (ActionFailed, HAError) as exc:
        raise api_error(502, str(exc)) from exc
    await asyncio.sleep(0)
    return TestResult(message=f"{component.name} : {body.action}")


class RestStateBody(BaseModel):
    rest_state: dict[str, RestState]


@router.get("/config/rest-state", response_model=RestStateBody, operation_id="get_rest_state")
async def get_rest_state(engine: EngineDep) -> RestStateBody:
    """État de repos de chaque lumière / interrupteur (appliqué en fin de scénario et à l'arrêt)."""
    return RestStateBody(rest_state=engine.config.rest_state)


class RestStateSaved(BaseModel):
    rest_state: dict[str, RestState]
    issues: list[schemas.IssueOut] = []


@router.put("/config/rest-state", response_model=RestStateSaved, operation_id="put_rest_state")
async def put_rest_state(body: RestStateBody, engine: EngineDep) -> RestStateSaved:
    """Remplace l'état de repos ; effet immédiat, aucun scénario n'est interrompu."""
    async with engine.config_lock:
        new = engine.config.model_copy(update={"rest_state": body.rest_state})
        issues = await commit(engine, new, stop_runs=False)
    return RestStateSaved(
        rest_state=body.rest_state, issues=[schemas.IssueOut.from_issue(i) for i in issues]
    )
