"""Contrôles qui croisent plusieurs composants : ids et broches uniques."""

from __future__ import annotations

from collections import defaultdict

from halloween.config.models import AppConfig
from halloween.issues import Issue


def validate_config(config: AppConfig) -> list[Issue]:
    issues: list[Issue] = []

    # Les blocs désignent leur cible par un seul champ `target` : les ids sont uniques tous types
    # confondus.
    by_id: dict[str, list[str]] = defaultdict(list)
    for kind in ("relays", "buttons", "lights", "switches", "players"):
        for component in getattr(config, kind):
            by_id[component.id].append(kind)
    for component_id, kinds in by_id.items():
        if len(kinds) > 1:
            issues.append(
                Issue(
                    "error",
                    "duplicate_id",
                    f"id `{component_id}` utilisé par {len(kinds)} composants ({', '.join(kinds)})",
                    component_id=component_id,
                )
            )

    # Une broche ne sert qu'une fois, y compris entre une entrée et une sortie.
    by_pin: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for relay in config.relays:
        by_pin[relay.pin].append(("relais", relay.id))
    for button in config.buttons:
        by_pin[button.pin].append(("bouton", button.id))
    for pin, users in sorted(by_pin.items()):
        if len(users) > 1:
            names = ", ".join(f"{kind} `{cid}`" for kind, cid in users)
            for _, cid in users:
                issues.append(
                    Issue(
                        "error",
                        "duplicate_pin",
                        f"GPIO {pin} utilisée plusieurs fois : {names}",
                        component_id=cid,
                    )
                )

    # L'état de repos ne concerne que des lumières et des interrupteurs existants.
    lights = {light.id: light for light in config.lights}
    switches = {switch.id for switch in config.switches}
    for component_id, rest in config.rest_state.items():
        light = lights.get(component_id)
        if light is None and component_id not in switches:
            issues.append(
                Issue(
                    "error",
                    "rest_state_unknown",
                    f"état de repos défini pour `{component_id}`, qui n'est pas une lumière "
                    "ni un interrupteur",
                    component_id=component_id,
                )
            )
            continue
        if rest.state == "off":
            continue
        for field, supported, label in (
            ("rgb_color", light is not None and light.supports_color, "la couleur"),
            ("brightness", light is not None and light.supports_brightness, "la luminosité"),
            ("transition", light is not None and light.supports_transition, "la transition"),
        ):
            if getattr(rest, field) is not None and not supported:
                issues.append(
                    Issue(
                        "error",
                        "rest_state_parameter",
                        f"`{component_id}` ne gère pas {label} : retirer ce paramètre du repos",
                        component_id=component_id,
                    )
                )

    # Entités Home Assistant en double : probablement une erreur de copier-coller.
    by_entity: dict[str, list[str]] = defaultdict(list)
    for light in config.lights:
        by_entity[light.entity_id].append(light.id)
    for switch in config.switches:
        by_entity[switch.entity_id].append(switch.id)
    for entity, ids in by_entity.items():
        if len(ids) > 1:
            for cid in ids:
                issues.append(
                    Issue(
                        "warning",
                        "duplicate_entity",
                        f"entité `{entity}` utilisée par plusieurs composants : {', '.join(ids)}",
                        component_id=cid,
                    )
                )
    return issues
