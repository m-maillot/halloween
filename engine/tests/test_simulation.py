import json
import time
from pathlib import Path

from halloween.config import AppConfig
from halloween.program import Program
from halloween.program.simulation import simulate

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__file__).parent / "data"


def config() -> AppConfig:
    raw = json.loads((ROOT / "deploy" / "config.example.json").read_text(encoding="utf-8"))
    raw["relays"].append(
        {
            "id": "robot",
            "name": "Robot",
            "pin": 5,
            "mode": "push",
            "pulse_ms": 200,
            "animation_s": 4,
        }
    )
    return AppConfig.model_validate(raw)


def prog(root: dict, *extra: dict, **kw) -> Program:
    scripts = [{"id": "s1", "root": root}] + [
        {"id": f"s{i + 2}", "root": r} for i, r in enumerate(extra)
    ]
    return Program.model_validate({"id": "p", "name": "P", "scripts": scripts, **kw})


def relay(id_, target, state="on"):
    return {"id": id_, "type": "relay", "target": target, "state": state}


def wait(id_, seconds=1):
    return {"id": id_, "type": "wait", "seconds": seconds}


def seq(id_, *children):
    return {"id": id_, "type": "sequence", "children": list(children)}


def ticks(result):
    return [(e.t, e.component, e.action) for e in result.timeline]


def test_main_scenario_timeline():
    main = Program.model_validate(
        json.loads((DATA / "scenario_principal.json").read_text(encoding="utf-8"))
    )
    result = simulate(main, config())
    assert result.status == "completed" and result.error is None
    assert result.duration_s == 17
    timeline = ticks(result)
    assert timeline[0] == (0, "bandeau", "on")  # entity_id remplacé par l'id du composant
    assert result.timeline[0].data == {"rgb_color": [255, 0, 0], "brightness": 40, "transition": 2}
    assert (3, "orage", "on") in timeline and (3, "fantome", "on") in timeline
    assert timeline[-1] == (17, "epouvantail", "on")
    assert result.still_on == ["epouvantail"]


def test_simulation_is_instant_whatever_the_virtual_duration():
    started = time.monotonic()
    result = simulate(
        prog(seq("n", relay("a", "fantome"), wait("w", 86_400), relay("b", "fantome", "off"))),
        config(),
        horizon_s=1e6,
    )
    assert result.duration_s == 86_400 and result.status == "completed"
    assert time.monotonic() - started < 2


def test_same_seed_same_timeline_other_seed_differs():
    random_wait = prog(
        seq("n", {"id": "w", "type": "wait", "min": 1, "max": 100}, relay("a", "fantome"))
    )
    assert ticks(simulate(random_wait, config(), seed=1)) == ticks(
        simulate(random_wait, config(), seed=1)
    )
    assert ticks(simulate(random_wait, config(), seed=1)) != ticks(
        simulate(random_wait, config(), seed=2)
    )


def test_push_relay_pulse_appears_in_the_timeline():
    trigger = {"id": "t", "type": "relay", "target": "robot", "action": "trigger"}
    assert ticks(simulate(prog(trigger), config())) == [(0, "robot", "on"), (0.2, "robot", "off")]


def test_max_duration_stops_a_forever_loop():
    loop = {
        "id": "r",
        "type": "repeat",
        "forever": True,
        "child": seq("b", relay("a", "fantome"), wait("w", 2)),
    }
    result = simulate(prog(loop, max_duration_s=10), config())
    assert result.status == "timeout" and result.duration_s == 10


def test_horizon_stops_a_forever_loop_without_max_duration():
    loop = {"id": "r", "type": "repeat", "forever": True, "child": wait("w", 5)}
    result = simulate(prog(loop), config(), horizon_s=100)
    assert result.status == "horizon" and result.duration_s == 100


def test_busy_loop_is_truncated_instead_of_hanging():
    busy = {"id": "r", "type": "repeat", "forever": True, "child": relay("a", "fantome")}
    result = simulate(prog(busy), config(), max_events=1_000)
    assert result.status == "truncated"


def test_waiting_for_a_button_nobody_presses_is_a_deadlock_with_partial_timeline():
    cond = {"type": "button", "id": "bouton_principal", "event": "short"}
    p = prog(
        seq(
            "n",
            relay("a", "fantome"),
            {"id": "u", "type": "wait_until", "condition": cond},
            relay("b", "orage"),
        )
    )
    result = simulate(p, config())
    assert result.status == "deadlock" and "rien" in result.error
    assert ticks(result) == [(0, "fantome", "on")]


def test_scripted_button_presses_unblock_the_wait():
    cond = {"type": "button", "id": "bouton_principal", "event": "short"}
    p = prog(seq("n", {"id": "u", "type": "wait_until", "condition": cond}, relay("b", "orage")))
    result = simulate(p, config(), button_presses=[(4.0, "bouton_principal", "short")])
    assert result.status == "completed" and ticks(result) == [(4, "orage", "on")]


def test_inconsistent_program_fails_with_a_message():
    result = simulate(prog(relay("a", "inconnu")), config())
    assert result.status == "failed" and "inconnu" in result.error


def test_called_programs_are_simulated():
    sub = Program.model_validate(
        {
            "id": "sub",
            "name": "S",
            "scripts": [{"id": "s1", "root": seq("s", wait("sw", 2), relay("sa", "orage"))}],
        }
    )
    caller = prog(seq("n", {"id": "c", "type": "call", "program_id": "sub"}, relay("a", "fantome")))
    result = simulate(caller, config(), {"sub": sub})
    assert ticks(result) == [(2, "orage", "on"), (2, "fantome", "on")]


def test_to_json_is_serializable():
    result = simulate(prog(seq("n", relay("a", "fantome"), wait("w", 1.5))), config())
    data = json.loads(json.dumps(result.to_json()))
    assert data["status"] == "completed" and data["duration_s"] == 1.5
    assert data["timeline"] == [{"t": 0, "component": "fantome", "action": "on", "data": {}}]


def test_unexpected_error_is_reported_as_failed(monkeypatch):
    from halloween.program import simulation

    def boom(*_args, **_kwargs):
        raise ValueError("pas prévu")

    monkeypatch.setattr(simulation, "Interpreter", boom)
    result = simulate(prog(relay("a", "fantome")), config())
    assert result.status == "failed" and "ValueError: pas prévu" in result.error
