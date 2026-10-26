import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from halloween.config import AppConfig
from halloween.config.validation import validate_config
from halloween.issues import errors, issues_from_validation_error, warnings
from halloween.program import Program
from halloween.program.validation import validate_program

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__file__).parent / "data"


@pytest.fixture
def config() -> AppConfig:
    raw = json.loads((ROOT / "deploy" / "config.example.json").read_text(encoding="utf-8"))
    raw["switches"] = [
        {"id": "prise", "name": "Prise", "entity_id": "switch.prise_salon"},
    ]
    raw["relays"].append(
        {"id": "robot", "name": "Robot", "pin": 5, "mode": "push", "animation_s": 8},
    )
    raw["relays"].append({"id": "sirene", "name": "Sirène", "pin": 6, "mode": "push"})
    return AppConfig.model_validate(raw)


def prog(root: dict, id_: str = "p", extra_scripts: list[dict] | None = None) -> Program:
    scripts = [{"id": "s1", "root": root}] + (extra_scripts or [])
    return Program.model_validate({"id": id_, "name": "P", "scripts": scripts})


def codes(issues):
    return sorted((i.code, i.node_id) for i in issues)


def relay(id_, target, **kw):
    return {"id": id_, "type": "relay", "target": target} | (kw or {"state": "on"})


def call(id_, target):
    return {"id": id_, "type": "call", "program_id": target}


# ------------------------------------------------------------------------------- configuration


def test_example_config_has_no_issue(config):
    assert validate_config(config) == []


def test_duplicate_ids_across_types(config):
    raw = config.model_dump(mode="json")
    raw["lights"].append({"id": "fantome", "name": "X", "entity_id": "light.x"})
    issues = validate_config(AppConfig.model_validate(raw))
    assert [(i.code, i.component_id) for i in issues] == [("duplicate_id", "fantome")]


def test_duplicate_pin_between_relay_and_button(config):
    raw = config.model_dump(mode="json")
    raw["buttons"][0]["pin"] = 18
    issues = validate_config(AppConfig.model_validate(raw))
    assert {(i.code, i.component_id) for i in issues} == {
        ("duplicate_pin", "fantome"),
        ("duplicate_pin", "bouton_principal"),
    }
    assert "GPIO 18" in issues[0].message


def test_duplicate_entity_is_only_a_warning(config):
    raw = config.model_dump(mode="json")
    raw["switches"][0]["entity_id"] = "switch.x"
    raw["lights"].append({"id": "l2", "name": "L2", "entity_id": "light.bandeau_hue"})
    issues = validate_config(AppConfig.model_validate(raw))
    assert errors(issues) == [] and {i.code for i in warnings(issues)} == {"duplicate_entity"}


# ------------------------------------------------------------------------------- composants


def test_valid_example_programs_have_no_error(config):
    main = Program.model_validate(
        json.loads((DATA / "scenario_principal.json").read_text(encoding="utf-8"))
    )
    assert errors(validate_program(main, config)) == []


@pytest.mark.parametrize(
    ("node", "code"),
    [
        (relay("n", "nope"), "unknown_component"),
        (relay("n", "bandeau"), "unknown_component"),  # une lumière, pas un relais
        ({"id": "n", "type": "light", "target": "fantome", "state": "on"}, "unknown_component"),
        ({"id": "n", "type": "switch", "target": "bandeau", "state": "on"}, "unknown_component"),
    ],
)
def test_unknown_or_wrong_type_component(config, node, code):
    assert codes(validate_program(prog(node), config)) == [(code, "n")]


def test_relay_mode_compatibility(config):
    assert codes(validate_program(prog(relay("a", "robot", state="on")), config)) == [
        ("relay_mode", "a")
    ]
    assert codes(validate_program(prog(relay("b", "fantome", action="trigger")), config)) == [
        ("relay_mode", "b")
    ]
    assert (
        validate_program(prog(relay("c", "robot", action="trigger", wait_for_end=True)), config)
        == []
    )
    assert validate_program(prog(relay("d", "fantome", state="off")), config) == []


def test_wait_for_end_needs_animation_duration(config):
    node = relay("n", "sirene", action="trigger", wait_for_end=True)
    assert codes(validate_program(prog(node), config)) == [("wait_for_end", "n")]


def test_unsupported_light_parameters(config):
    node = {
        "id": "n",
        "type": "light",
        "target": "guirlande",
        "state": "on",
        "rgb_color": [1, 2, 3],
        "transition": 1,
        "brightness": 10,
    }
    issues = validate_program(prog(node), config)
    assert [i.code for i in issues] == ["unsupported_parameter", "unsupported_parameter"]
    assert "couleur" in issues[0].message and "transition" in issues[1].message


def test_light_off_ignores_unsupported_parameters(config):
    node = {
        "id": "n",
        "type": "light",
        "target": "guirlande",
        "state": "off",
        "rgb_color": [1, 2, 3],
    }
    assert validate_program(prog(node), config) == []


def test_conditions_reference_known_components(config):
    def cond_if(condition):
        return {
            "id": "i",
            "type": "if",
            "condition": condition,
            "then": {"id": "w", "type": "wait", "seconds": 1},
        }

    ok = {"type": "button", "id": "bouton_principal", "event": "short"}
    assert validate_program(prog(cond_if(ok)), config) == []
    bad_button = {"type": "button", "id": "autre", "event": "short"}
    assert codes(validate_program(prog(cond_if(bad_button)), config)) == [
        ("unknown_component", "i")
    ]
    push = {"type": "relay_is", "id": "robot", "state": "on"}
    assert codes(validate_program(prog(cond_if(push)), config)) == [("relay_mode", "i")]
    assert (
        validate_program(prog(cond_if({"type": "relay_is", "id": "orage", "state": "on"})), config)
        == []
    )
    unknown = {"type": "relay_is", "id": "zzz", "state": "on"}
    assert codes(validate_program(prog(cond_if(unknown)), config)) == [("unknown_component", "i")]


def test_all_problems_are_reported_not_just_the_first(config):
    seq = {
        "id": "root",
        "type": "sequence",
        "children": [relay("a", "nope"), relay("b", "robot", state="on")],
    }
    assert codes(validate_program(prog(seq), config)) == [
        ("relay_mode", "b"),
        ("unknown_component", "a"),
    ]


# ------------------------------------------------------------------------------- appels


def test_call_requires_known_program_only_when_programs_given(config):
    p = prog(call("c", "fantome-2"))
    assert validate_program(p, config) == []
    assert codes(validate_program(p, config, {})) == [("unknown_program", "c")]


def test_self_call_and_cycles(config):
    assert codes(validate_program(prog(call("c", "p")), config, {})) == [("call_cycle", "c")]
    a = prog(call("c", "b"), "a")
    b = prog(call("d", "a"), "b")
    assert codes(validate_program(a, config, {"b": b})) == [("call_cycle", "c")]


def chain(length: int) -> dict[str, Program]:
    """p0 -> p1 -> ... -> p<length>."""
    progs = {}
    for i in range(length):
        progs[f"p{i}"] = prog(call(f"c{i}", f"p{i + 1}"), f"p{i}")
    progs[f"p{length}"] = prog({"id": "end", "type": "wait", "seconds": 1}, f"p{length}")
    return progs


def test_call_depth_limit(config):
    ok = chain(5)  # p0 appelle p1..p5 : 5 niveaux
    assert errors(validate_program(ok["p0"], config, ok)) == []
    too_deep = chain(6)
    assert codes(validate_program(too_deep["p0"], config, too_deep)) == [("call_depth", "c0")]


# ------------------------------------------------------------------------------- avertissements


def test_scripts_commanding_the_same_component_warn(config):
    p = prog(
        relay("a", "fantome"),
        extra_scripts=[{"id": "s2", "root": relay("b", "fantome", state="off")}],
    )
    issues = validate_program(p, config)
    assert errors(issues) == []
    assert codes(warnings(issues)) == [("parallel_conflict", "a"), ("parallel_conflict", "b")]


def test_parallel_branches_commanding_the_same_component_warn(config):
    par = {
        "id": "par",
        "type": "parallel",
        "children": [relay("a", "orage"), relay("b", "orage", state="off")],
    }
    assert codes(validate_program(prog(par), config)) == [
        ("parallel_conflict", "a"),
        ("parallel_conflict", "b"),
    ]


def test_node_flagged_at_two_levels_is_reported_once(config):
    par = {
        "id": "par",
        "type": "parallel",
        "children": [relay("a", "orage"), relay("b", "orage", state="off")],
    }
    p = prog(par, extra_scripts=[{"id": "s2", "root": relay("c", "orage", state="off")}])
    assert codes(validate_program(p, config)) == [
        ("parallel_conflict", "a"),
        ("parallel_conflict", "b"),
        ("parallel_conflict", "c"),
    ]


def test_sequence_on_same_component_does_not_warn(config):
    seq = {
        "id": "s",
        "type": "sequence",
        "children": [relay("a", "orage"), relay("b", "orage", state="off")],
    }
    assert validate_program(prog(seq), config) == []


def test_busy_forever_loop_warns_but_loop_with_wait_does_not(config):
    busy = {"id": "r", "type": "repeat", "forever": True, "child": relay("a", "orage")}
    assert codes(validate_program(prog(busy), config)) == [("busy_loop", "r")]
    paused = {
        "id": "r",
        "type": "repeat",
        "forever": True,
        "child": {
            "id": "s",
            "type": "sequence",
            "children": [relay("a", "orage"), {"id": "w", "type": "wait", "seconds": 1}],
        },
    }
    assert validate_program(prog(paused), config) == []


# ------------------------------------------------------------------------------- erreurs Pydantic


def test_pydantic_errors_are_located_on_the_faulty_block():
    raw = {
        "id": "p",
        "name": "P",
        "scripts": [
            {
                "id": "s1",
                "root": {
                    "id": "n1",
                    "type": "sequence",
                    "children": [
                        {"id": "n2", "type": "wait", "seconds": 1},
                        {"id": "n3", "type": "wait", "seconds": -4},
                        {
                            "id": "n4",
                            "type": "light",
                            "target": "x",
                            "state": "on",
                            "brightness": 999,
                        },
                    ],
                },
            }
        ],
    }
    with pytest.raises(ValidationError) as exc:
        Program.model_validate(raw)
    issues = issues_from_validation_error(exc.value, raw)
    assert {(i.node_id) for i in issues} == {"n3", "n4"}
    assert all(i.severity == "error" for i in issues)


def test_pydantic_error_outside_a_block_has_no_node_id():
    raw = {
        "id": "p",
        "name": "",
        "scripts": [{"id": "s1", "root": {"id": "n1", "type": "wait", "seconds": 1}}],
    }
    with pytest.raises(ValidationError) as exc:
        Program.model_validate(raw)
    (issue,) = issues_from_validation_error(exc.value, raw)
    assert issue.node_id is None and "name" in issue.message
