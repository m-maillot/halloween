"""Déclencheurs : ce qui lance un programme (ou arrête tout) sans intervention de l'interface.

Stockés dans `triggers.json` (spec 1 §7). Deux sources : un bouton physique, un planning cron.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from halloween.config.models import Model, Slug
from halloween.issues import Issue
from halloween.program.runs import Policy


class ButtonTrigger(Model):
    id: Slug
    source: Literal["button"]
    button: Slug
    event: Literal["short", "long", "double"]
    # Soit lancer un programme, soit arrêter tout (arrêt d'urgence) : jamais les deux.
    program: Slug | None = None
    action: Literal["stop"] | None = None
    # Que faire si le programme tourne déjà (voir `RunManager.start`).
    policy: Policy = "ignore"
    enabled: bool = True

    @model_validator(mode="after")
    def _program_xor_action(self) -> Self:
        if (self.program is None) == (self.action is None):
            raise ValueError("indiquer soit `program`, soit `action: stop`")
        return self


class ScheduleTrigger(Model):
    id: Slug
    source: Literal["schedule"]
    # Cron à 5 champs : minute heure jour-du-mois mois jour-de-semaine.
    cron: str
    # Fuseau IANA (ex. `Europe/Paris`) ; absent = fuseau du Raspberry Pi.
    timezone: str | None = None
    program: Slug
    policy: Policy = "ignore"
    enabled: bool = True


Trigger = Annotated[ButtonTrigger | ScheduleTrigger, Field(discriminator="source")]

_adapter: TypeAdapter[Trigger] = TypeAdapter(Trigger)


def parse_triggers(raw: list[dict]) -> tuple[list[Trigger], list[Issue]]:
    """Charge une liste brute ; une entrée invalide est signalée sans bloquer les autres."""
    triggers: list[Trigger] = []
    issues: list[Issue] = []
    for index, item in enumerate(raw):
        label = item.get("id") if isinstance(item, dict) else None
        try:
            triggers.append(_adapter.validate_python(item))
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(map(str, e['loc']))} : {e['msg']}" for e in exc.errors()
            )
            issues.append(
                Issue(
                    "error",
                    "invalid_trigger",
                    f"déclencheur n°{index + 1} invalide : {details}",
                    component_id=label if isinstance(label, str) else None,
                )
            )
    return triggers, issues


def dump_triggers(triggers: list[Trigger]) -> list[dict]:
    return [t.model_dump(mode="json", exclude_none=True) for t in triggers]


def emergency_stop_for(button_id: str) -> ButtonTrigger:
    """Déclencheur proposé à la création d'un bouton : appui long = arrêt d'urgence."""
    return ButtonTrigger(
        id=f"arret-{button_id}"[:64],
        source="button",
        button=button_id,
        event="long",
        action="stop",
    )
