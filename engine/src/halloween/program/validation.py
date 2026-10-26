"""Validation d'un programme par rapport à la configuration et aux autres programmes.

Erreurs (bloquantes) : composant inconnu ou d'un autre type, bloc incompatible avec le mode du
relais, paramètre non supporté par la lumière, bouton inconnu, programme appelé inconnu, cycle
ou profondeur excessive des `call`.
Avertissements : deux scripts ou branches parallèles qui commandent le même composant (la
dernière commande l'emporte), boucle infinie sans attente.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from halloween.config.models import AppConfig, RelayMode
from halloween.issues import Issue
from halloween.program.models import (
    ButtonCondition,
    CallNode,
    IfNode,
    LightNode,
    Node,
    ParallelNode,
    Program,
    RelayIsCondition,
    RelayNode,
    RepeatNode,
    SwitchNode,
    WaitNode,
    WaitUntilNode,
    walk,
)

MAX_CALL_DEPTH = 5

ACTION_NODES = (RelayNode, LightNode, SwitchNode)


def validate_program(
    program: Program,
    config: AppConfig,
    programs: Mapping[str, Program] | None = None,
) -> list[Issue]:
    """`programs` : les autres programmes enregistrés (sans lui, les `call` ne sont pas vérifiés)."""
    issues: list[Issue] = []
    relays = {r.id: r for r in config.relays}
    lights = {light.id: light for light in config.lights}
    switches = {s.id: s for s in config.switches}
    buttons = {b.id for b in config.buttons}

    def error(code: str, message: str, node: Node) -> None:
        issues.append(Issue("error", code, message, node_id=node.id))

    for node in program.nodes():
        if isinstance(node, RelayNode):
            _check_relay(node, relays, lights, switches, error)
        elif isinstance(node, LightNode):
            _check_light(node, lights, relays, switches, error)
        elif isinstance(node, SwitchNode):
            if node.target not in switches:
                error(
                    "unknown_component", _unknown("interrupteur", node.target, relays, lights), node
                )
        elif isinstance(node, IfNode | WaitUntilNode):
            _check_condition(node, relays, buttons, error)

    if programs is not None:
        issues.extend(_check_calls(program, programs))
    issues.extend(_warn_parallel_conflicts(program))
    issues.extend(_warn_busy_loops(program))
    return issues


# --------------------------------------------------------------------------- composants


def _unknown(kind: str, target: str, *others: Mapping[str, object]) -> str:
    if any(target in other for other in others):
        return f"`{target}` existe mais n'est pas un(e) {kind}"
    return f"{kind} inconnu(e) : `{target}`"


def _check_relay(node, relays, lights, switches, error) -> None:
    relay = relays.get(node.target)
    if relay is None:
        error("unknown_component", _unknown("relais", node.target, lights, switches), node)
        return
    if node.state is not None and relay.mode is RelayMode.PUSH:
        error(
            "relay_mode",
            f"`{relay.name}` est en mode impulsion : utiliser « déclencher », pas allumer/éteindre",
            node,
        )
    if node.action == "trigger" and relay.mode is RelayMode.LATCHED:
        error(
            "relay_mode",
            f"`{relay.name}` est en mode maintenu : utiliser allumer/éteindre, pas « déclencher »",
            node,
        )
    if node.wait_for_end and relay.mode is RelayMode.PUSH and relay.animation_s is None:
        error(
            "wait_for_end",
            f"« attendre la fin » exige une durée d'animation sur `{relay.name}`",
            node,
        )


def _check_light(node: LightNode, lights, relays, switches, error) -> None:
    light = lights.get(node.target)
    if light is None:
        error("unknown_component", _unknown("lumière", node.target, relays, switches), node)
        return
    if node.state == "off":
        return  # couleur et luminosité sont ignorées à l'extinction
    for field, supported, label in (
        ("rgb_color", light.supports_color, "la couleur"),
        ("brightness", light.supports_brightness, "la luminosité"),
        ("transition", light.supports_transition, "la transition"),
    ):
        if getattr(node, field) is not None and not supported:
            error("unsupported_parameter", f"`{light.name}` ne gère pas {label}", node)


def _check_condition(node, relays, buttons, error) -> None:
    condition = node.condition
    if isinstance(condition, ButtonCondition) and condition.id not in buttons:
        error("unknown_component", f"bouton inconnu : `{condition.id}`", node)
    elif isinstance(condition, RelayIsCondition):
        relay = relays.get(condition.id)
        if relay is None:
            error("unknown_component", f"relais inconnu : `{condition.id}`", node)
        elif relay.mode is not RelayMode.LATCHED:
            error(
                "relay_mode",
                f"`{relay.name}` est en mode impulsion : son état n'est pas lisible",
                node,
            )


# --------------------------------------------------------------------------- appels de programmes


def _calls(program: Program) -> list[CallNode]:
    return [n for n in program.nodes() if isinstance(n, CallNode)]


def _check_calls(program: Program, programs: Mapping[str, Program]) -> list[Issue]:
    issues: list[Issue] = []
    known = {**programs, program.id: program}

    def longest_chain(pid: str, stack: tuple[str, ...]) -> tuple[int, bool]:
        """(profondeur maximale d'appels sous `pid`, cycle rencontré)."""
        depth, cycle = 0, False
        for call in _calls(known[pid]) if pid in known else []:
            if call.program_id in stack:
                cycle = True
            elif call.program_id in known:
                sub_depth, sub_cycle = longest_chain(call.program_id, (*stack, call.program_id))
                depth = max(depth, 1 + sub_depth)
                cycle = cycle or sub_cycle
            else:
                depth = max(depth, 1)
        return depth, cycle

    for call in _calls(program):
        if call.program_id not in known:
            issues.append(
                Issue(
                    "error",
                    "unknown_program",
                    f"programme inconnu : `{call.program_id}`",
                    node_id=call.id,
                )
            )
            continue
        if call.program_id == program.id:
            issues.append(
                Issue(
                    "error",
                    "call_cycle",
                    "un programme ne peut pas s'appeler lui-même",
                    node_id=call.id,
                )
            )
            continue
        depth, cycle = longest_chain(call.program_id, (program.id, call.program_id))
        if cycle:
            issues.append(
                Issue(
                    "error",
                    "call_cycle",
                    f"cycle d'appels via `{call.program_id}`",
                    node_id=call.id,
                )
            )
        elif 1 + depth > MAX_CALL_DEPTH:
            issues.append(
                Issue(
                    "error",
                    "call_depth",
                    f"appels imbriqués sur {1 + depth} niveaux (maximum {MAX_CALL_DEPTH})",
                    node_id=call.id,
                )
            )
    return issues


# --------------------------------------------------------------------------- avertissements


def _commanded(node: Node) -> dict[tuple[str, str], list[str]]:
    """Composants commandés dans un sous-arbre : (type, cible) -> ids des blocs."""
    found: dict[tuple[str, str], list[str]] = defaultdict(list)
    for n in walk(node):
        if isinstance(n, ACTION_NODES):
            found[(n.type, n.target)].append(n.id)
    return found


def _conflicts(branches: list[Node], where: str) -> list[Issue]:
    per_branch = [_commanded(b) for b in branches]
    issues: list[Issue] = []
    seen_components = {key for branch in per_branch for key in branch}
    for key in sorted(seen_components):
        involved = [branch[key] for branch in per_branch if key in branch]
        if len(involved) < 2:
            continue
        for node_ids in involved:
            for node_id in node_ids:
                issues.append(
                    Issue(
                        "warning",
                        "parallel_conflict",
                        f"`{key[1]}` est commandé par plusieurs {where} en parallèle : "
                        "la dernière commande l'emporte",
                        node_id=node_id,
                    )
                )
    return issues


def _warn_parallel_conflicts(program: Program) -> list[Issue]:
    issues = _conflicts([s.root for s in program.scripts], "scripts")
    for node in program.nodes():
        if isinstance(node, ParallelNode):
            issues.extend(_conflicts(list(node.children), "branches"))
    # un même bloc peut être signalé par deux niveaux (scripts et branches) : un seul avertissement
    return list({(i.code, i.node_id): i for i in issues}.values())


def _warn_busy_loops(program: Program) -> list[Issue]:
    issues = []
    for node in program.nodes():
        if isinstance(node, RepeatNode) and node.forever:
            has_pause = any(isinstance(n, WaitNode | WaitUntilNode) for n in walk(node.child))
            has_pause = has_pause or any(
                isinstance(n, RelayNode) and n.wait_for_end for n in walk(node.child)
            )
            if not has_pause:
                issues.append(
                    Issue(
                        "warning",
                        "busy_loop",
                        "boucle infinie sans attente : elle enverrait des commandes en continu",
                        node_id=node.id,
                    )
                )
    return issues
