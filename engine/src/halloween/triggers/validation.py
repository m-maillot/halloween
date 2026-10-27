"""Validation des déclencheurs par rapport à la configuration et aux programmes."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection

from halloween.config.models import AppConfig
from halloween.issues import Issue
from halloween.triggers.models import ButtonTrigger, Trigger


def validate_triggers(
    triggers: list[Trigger], config: AppConfig, program_ids: Collection[str]
) -> list[Issue]:
    issues: list[Issue] = []
    buttons = {b.id for b in config.buttons}

    for trigger_id, count in Counter(t.id for t in triggers).items():
        if count > 1:
            issues.append(
                Issue(
                    "error",
                    "duplicate_id",
                    f"id de déclencheur en double : `{trigger_id}`",
                    component_id=trigger_id,
                )
            )

    seen: dict[tuple[str, str], list[str]] = defaultdict(list)
    for trigger in triggers:
        if isinstance(trigger, ButtonTrigger):
            if trigger.button not in buttons:
                issues.append(
                    Issue(
                        "error",
                        "unknown_button",
                        f"bouton inconnu : `{trigger.button}`",
                        component_id=trigger.id,
                    )
                )
            if trigger.enabled:
                seen[(trigger.button, trigger.event)].append(trigger.id)
        if (trigger.program is not None) and trigger.program not in program_ids:
            issues.append(
                Issue(
                    "error",
                    "unknown_program",
                    f"programme inconnu : `{trigger.program}`",
                    component_id=trigger.id,
                )
            )

    for (button, event), ids in seen.items():
        if len(ids) > 1:
            for trigger_id in ids:
                issues.append(
                    Issue(
                        "warning",
                        "duplicate_trigger",
                        f"plusieurs déclencheurs sur `{button}` / {event} : {', '.join(ids)}",
                        component_id=trigger_id,
                    )
                )
    return issues
