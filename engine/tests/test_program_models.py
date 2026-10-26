import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from halloween.program import (
    IfNode,
    LightNode,
    ParallelNode,
    Program,
    RelayNode,
    RepeatNode,
    WaitNode,
    walk,
)

DATA = Path(__file__).parent / "data"


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def program(root: dict, **overrides) -> dict:
    return {"id": "p", "name": "P", "scripts": [{"id": "s1", "root": root}]} | overrides


def wait(id_: str = "w", **kw) -> dict:
    return {"id": id_, "type": "wait"} | ({"seconds": 1} if not kw else kw)


@pytest.mark.parametrize("name", ["scenario_principal.json", "ambiance.json"])
def test_examples_load_and_round_trip_without_loss(name):
    raw = load(name)
    parsed = Program.model_validate(raw)
    dumped = parsed.to_json()
    assert dumped["schema"] == 1
    assert Program.model_validate(dumped) == parsed
    # toutes les valeurs du fichier d'origine sont conservées
    assert_contains(dumped, raw)


def assert_contains(actual, expected):
    """Chaque valeur de `expected` se retrouve dans `actual` (qui peut ajouter des défauts)."""
    if isinstance(expected, dict):
        for key, value in expected.items():
            assert key in actual, key
            assert_contains(actual[key], value)
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for a, e in zip(actual, expected, strict=True):
            assert_contains(a, e)
    else:
        assert actual == expected


def test_program_defaults():
    p = Program.model_validate(program(wait()))
    assert (p.max_duration_s, p.on_end, p.show, p.revision, p.editor) == (
        None,
        "reset",
        False,
        0,
        None,
    )
    assert p.scripts[0].hat.type == "start"


def test_main_example_structure():
    p = Program.model_validate(load("scenario_principal.json"))
    ids = [n.id for n in p.nodes()]
    assert ids[0] == "n1" and len(ids) == 13
    assert any(isinstance(n, ParallelNode) for n in p.nodes())
    light = next(n for n in p.nodes() if isinstance(n, LightNode))
    assert light.rgb_color == (255, 0, 0) and light.brightness == 40 and light.transition == 2


def test_ambiance_example_has_forever_loop_two_scripts_and_else_branch():
    p = Program.model_validate(load("ambiance.json"))
    assert p.max_duration_s is None and len(p.scripts) == 2
    assert next(n for n in p.nodes() if isinstance(n, RepeatNode)).forever is True
    if_node = next(n for n in p.nodes() if isinstance(n, IfNode))
    assert if_node.else_ is not None and if_node.else_.id == "a7"
    relay = next(n for n in p.nodes() if isinstance(n, RelayNode))
    assert (relay.action, relay.wait_for_end) == ("trigger", True)


def test_walk_visits_nested_nodes():
    p = Program.model_validate(load("ambiance.json"))
    assert {"a1", "a6", "a7", "a9", "a10"} <= {n.id for n in walk(p.scripts[0].root)}


class TestControlBlocks:
    @pytest.mark.parametrize(
        "kwargs",
        [{}, {"times": 2, "forever": True}, {"times": 0}, {"forever": False}],
    )
    def test_repeat_needs_exactly_one_of_times_or_forever(self, kwargs):
        with pytest.raises(ValidationError):
            Program.model_validate(
                program({"id": "r", "type": "repeat", "child": wait(), **kwargs})
            )

    @pytest.mark.parametrize("kwargs", [{"times": 3}, {"forever": True}])
    def test_repeat_valid(self, kwargs):
        Program.model_validate(program({"id": "r", "type": "repeat", "child": wait(), **kwargs}))

    @pytest.mark.parametrize(
        "kwargs",
        [{}, {"seconds": -1}, {"seconds": 1, "min": 0, "max": 2}, {"min": 1}, {"min": 3, "max": 2}],
    )
    def test_invalid_waits(self, kwargs):
        with pytest.raises(ValidationError):
            Program.model_validate(program({"id": "w", "type": "wait"} | kwargs))

    @pytest.mark.parametrize("kwargs", [{"seconds": 0}, {"seconds": 2.5}, {"min": 0.1, "max": 0.1}])
    def test_valid_waits(self, kwargs):
        p = Program.model_validate(program({"id": "w", "type": "wait"} | kwargs))
        assert isinstance(p.scripts[0].root, WaitNode)

    def test_parallel_until_values(self):
        for until in ("all", "first"):
            Program.model_validate(
                program({"id": "p1", "type": "parallel", "children": [], "until": until})
            )
        with pytest.raises(ValidationError):
            Program.model_validate(
                program({"id": "p1", "type": "parallel", "children": [], "until": "any"})
            )

    def test_random_choice_needs_a_choice_and_positive_weights(self):
        with pytest.raises(ValidationError):
            Program.model_validate(program({"id": "c", "type": "random_choice", "choices": []}))
        with pytest.raises(ValidationError):
            Program.model_validate(
                program(
                    {
                        "id": "c",
                        "type": "random_choice",
                        "choices": [{"weight": 0, "child": wait()}],
                    }
                )
            )

    @pytest.mark.parametrize(
        "condition",
        [
            {"type": "button", "id": "b", "event": "triple"},
            {"type": "random", "probability": 1.5},
            {"type": "relay_is", "id": "r", "state": "maybe"},
            {"type": "unknown"},
        ],
    )
    def test_invalid_conditions(self, condition):
        with pytest.raises(ValidationError):
            Program.model_validate(
                program({"id": "i", "type": "if", "condition": condition, "then": wait()})
            )

    def test_wait_until_timeout_must_be_positive(self):
        cond = {"type": "button", "id": "b", "event": "short"}
        with pytest.raises(ValidationError):
            Program.model_validate(
                program({"id": "u", "type": "wait_until", "condition": cond, "timeout_s": 0})
            )


class TestActionBlocks:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {},
            {"state": "on", "action": "trigger"},
            {"state": "toggle"},
            {"state": "on", "wait_for_end": True},
        ],
    )
    def test_invalid_relay_blocks(self, kwargs):
        with pytest.raises(ValidationError):
            Program.model_validate(program({"id": "r", "type": "relay", "target": "x"} | kwargs))

    @pytest.mark.parametrize(
        "kwargs",
        [{"state": "off"}, {"action": "trigger"}, {"action": "trigger", "wait_for_end": True}],
    )
    def test_valid_relay_blocks(self, kwargs):
        Program.model_validate(program({"id": "r", "type": "relay", "target": "x"} | kwargs))

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"rgb_color": [256, 0, 0]},
            {"rgb_color": [1, 2]},
            {"rgb_color": [-1, 0, 0]},
            {"brightness": 300},
            {"transition": -1},
        ],
    )
    def test_invalid_light_parameters(self, kwargs):
        with pytest.raises(ValidationError):
            Program.model_validate(
                program({"id": "l", "type": "light", "target": "x", "state": "on"} | kwargs)
            )

    def test_action_options_defaults(self):
        p = Program.model_validate(
            program({"id": "l", "type": "light", "target": "x", "state": "off"})
        )
        node = p.scripts[0].root
        assert (node.fire_and_forget, node.on_error) == (False, "continue")

    def test_switch_block(self):
        Program.model_validate(
            program({"id": "s", "type": "switch", "target": "prise", "state": "on"})
        )


class TestProgramLevel:
    def test_unknown_block_type_is_rejected(self):
        with pytest.raises(ValidationError, match="type"):
            Program.model_validate(program({"id": "x", "type": "teleport"}))

    def test_unknown_field_is_rejected(self):
        with pytest.raises(ValidationError, match="extra"):
            Program.model_validate(program(wait()) | {"couleur": "rouge"})

    def test_at_least_one_script(self):
        with pytest.raises(ValidationError):
            Program.model_validate({"id": "p", "name": "P", "scripts": []})

    def test_duplicate_node_ids_are_rejected_across_scripts(self):
        raw = {
            "id": "p",
            "name": "P",
            "scripts": [{"id": "s1", "root": wait("n1")}, {"id": "s2", "root": wait("n1")}],
        }
        with pytest.raises(ValidationError, match="n1"):
            Program.model_validate(raw)

    def test_duplicate_script_ids_are_rejected(self):
        raw = {
            "id": "p",
            "name": "P",
            "scripts": [{"id": "s1", "root": wait("a")}, {"id": "s1", "root": wait("b")}],
        }
        with pytest.raises(ValidationError, match="scripts"):
            Program.model_validate(raw)

    def test_unsupported_hat_and_schema(self):
        with pytest.raises(ValidationError):
            Program.model_validate(
                {
                    "id": "p",
                    "name": "P",
                    "scripts": [{"id": "s", "hat": {"type": "on_button"}, "root": wait()}],
                }
            )
        with pytest.raises(ValidationError):
            Program.model_validate(program(wait()) | {"schema": 2})

    @pytest.mark.parametrize("duration", [0, -1])
    def test_max_duration_must_be_positive_when_given(self, duration):
        with pytest.raises(ValidationError):
            Program.model_validate(program(wait(), max_duration_s=duration))

    def test_editor_metadata_is_kept_but_size_limited(self):
        p = Program.model_validate(
            program(wait(), editor={"zoom": 1.5, "positions": {"n1": [0, 0]}})
        )
        assert p.to_json()["editor"]["zoom"] == 1.5
        with pytest.raises(ValidationError, match="Ko"):
            Program.model_validate(program(wait(), editor={"blob": "x" * (300 * 1024)}))

    def test_invalid_ids(self):
        for bad in ("", "a b", "é", "x" * 65):
            with pytest.raises(ValidationError):
                Program.model_validate(program(wait(bad)))
