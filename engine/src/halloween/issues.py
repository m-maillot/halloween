"""Résultat d'une validation : erreurs (bloquantes) et avertissements, localisés."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError


@dataclass(frozen=True)
class Issue:
    severity: Literal["error", "warning"]
    code: str
    message: str
    # Nœud du programme concerné (pour surligner le bloc), ou composant concerné.
    node_id: str | None = None
    component_id: str | None = None


def errors(issues: Iterable[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error"]


def warnings(issues: Iterable[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "warning"]


def issues_from_validation_error(exc: ValidationError, raw: Any) -> list[Issue]:
    """Convertit une erreur Pydantic en `Issue`, localisée au bloc le plus proche (`node_id`).

    `raw` est le JSON d'origine : on le parcourt le long du chemin de l'erreur pour retrouver le
    dernier objet portant un `id` (le bloc fautif). Les étiquettes de l'union discriminée qui
    figurent dans le chemin sans exister dans les données sont ignorées.
    """
    result = []
    for err in exc.errors():
        node_id = None
        current = raw
        in_scripts = False
        for step in err["loc"]:
            if isinstance(current, dict) and step in current:
                current = current[step]
            elif isinstance(current, list) and isinstance(step, int) and step < len(current):
                current = current[step]
            else:
                continue
            if step == "scripts":
                in_scripts = True
            if in_scripts and isinstance(current, dict) and isinstance(current.get("id"), str):
                node_id = current["id"]
        location = ".".join(str(s) for s in err["loc"])
        result.append(
            Issue("error", "invalid", f"{location} : {err['msg']}".strip(" :"), node_id=node_id)
        )
    return result
