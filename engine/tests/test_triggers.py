import asyncio
import json
from pathlib import Path

import pytest
from gpiozero.pins.mock import MockFactory

from halloween.config import AppConfig, Button
from halloween.drivers import FakeButtonDriver, FakeHAClient, FakeRelayDriver
from halloween.drivers.gpio import GpioButtonDriver
from halloween.program import Program
from halloween.program.runs import RunManager
from halloween.program.virtual import run_virtual
from halloween.triggers import (
    ButtonTrigger,
    TriggerEngine,
    emergency_stop_for,
    parse_triggers,
    validate_triggers,
)

ROOT = Path(__file__).resolve().parents[2]


def make_config() -> AppConfig:
    raw = json.loads((ROOT / "deploy" / "config.example.json").read_text(encoding="utf-8"))
    return AppConfig.model_validate(raw)


def program(id_: str, *children: dict, **kw) -> Program:
    root = {"id": "n", "type": "sequence", "children": list(children)}
    return Program.model_validate(
        {"id": id_, "name": id_, "scripts": [{"id": "s", "root": root}], **kw}
    )


def relay(id_, target, state="on"):
    return {"id": id_, "type": "relay", "target": target, "state": state}


def wait(id_, seconds):
    return {"id": id_, "type": "wait", "seconds": seconds}


def button_trigger(id_="t1", event="short", program_id: str | None = "demo", **kw) -> ButtonTrigger:
    data = {"id": id_, "source": "button", "button": "bouton_principal", "event": event, **kw}
    if program_id:
        data["program"] = program_id
    return ButtonTrigger.model_validate(data)


class Env:
    def __init__(self, triggers=()):
        self.config = make_config()
        self.relays = FakeRelayDriver.from_config(self.config)
        self.buttons = FakeButtonDriver(["bouton_principal", "autre"])
        self.programs: dict[str, Program] = {}
        self.manager = RunManager(
            self.config, self.relays, FakeHAClient(), self.buttons, self.programs
        )
        self.engine = TriggerEngine(self.manager, self.buttons, self.programs, triggers)

    def add(self, prog: Program) -> Program:
        self.programs[prog.id] = prog
        return prog

    async def press(self, event="short", button="bouton_principal"):
        await self.buttons.press(button, event)
        await asyncio.sleep(0.001)  # temps virtuel : toutes les réactions en cours se terminent

    def running(self) -> list[str]:
        return sorted(r.program.id for r in self.manager.active)


def scenario(test):
    def wrapper():
        async def main():
            env = Env()
            await env.engine.start()
            try:
                await test(env)
            finally:
                await env.engine.stop()
                await env.manager.shutdown()

        run_virtual(main)

    wrapper.__name__ = test.__name__
    return wrapper


# ------------------------------------------------------------------ réactions


@scenario
async def test_short_press_launches_the_program(env):
    env.add(program("demo", relay("a", "fantome"), wait("w", 5)))
    env.engine.set_triggers([button_trigger()])
    await env.press("short")
    assert env.running() == ["demo"] and env.relays.is_on("fantome")


@scenario
async def test_long_press_stops_everything_immediately(env):
    env.add(program("demo", relay("a", "fantome"), wait("w", 50)))
    env.add(program("ambiance", relay("b", "orage"), wait("w", 50)))
    env.engine.set_triggers([button_trigger("t1", "short"), emergency_stop_for("bouton_principal")])
    for pid in ("demo", "ambiance"):
        await env.manager.start(env.programs[pid])
    await asyncio.sleep(3)
    t0 = asyncio.get_running_loop().time()
    await env.press("long")
    assert env.running() == [] and asyncio.get_running_loop().time() - t0 < 0.01
    assert not env.relays.is_on("fantome") and not env.relays.is_on("orage")


@scenario
async def test_events_of_other_buttons_and_kinds_are_ignored(env):
    env.add(program("demo", wait("w", 5)))
    env.engine.set_triggers([button_trigger(event="double")])
    await env.press("short")
    await env.press("long")
    await env.press("double", button="autre")
    assert env.running() == []
    await env.press("double")
    assert env.running() == ["demo"]


@scenario
async def test_several_triggers_on_the_same_event_all_fire(env):
    env.add(program("a", wait("w", 5)))
    env.add(program("b", wait("w", 5)))
    env.engine.set_triggers(
        [button_trigger("t1", program_id="a"), button_trigger("t2", program_id="b")]
    )
    await env.press("short")
    assert env.running() == ["a", "b"]


@scenario
async def test_disabled_trigger_is_ignored(env):
    env.add(program("demo", wait("w", 5)))
    env.engine.set_triggers([button_trigger(enabled=False)])
    await env.press("short")
    assert env.running() == []


@scenario
async def test_triggers_can_be_replaced_while_running(env):
    env.add(program("demo", wait("w", 5)))
    await env.press("short")
    assert env.running() == []
    env.engine.set_triggers([button_trigger()])
    await env.press("short")
    assert env.running() == ["demo"]
    env.engine.set_triggers([])
    await env.manager.stop_all()
    await env.press("short")
    assert env.running() == []


# ------------------------------------------------------------------ politiques


@scenario
async def test_policy_ignore_keeps_the_running_program(env):
    env.add(program("demo", wait("w", 20)))
    env.engine.set_triggers([button_trigger(policy="ignore")])
    await env.press("short")
    first = env.manager.active[0]
    await asyncio.sleep(2)
    await env.press("short")
    assert env.manager.active == [first]


@scenario
async def test_policy_restart_replaces_the_running_program(env):
    env.add(program("demo", wait("w", 20)))
    env.engine.set_triggers([button_trigger(policy="restart")])
    await env.press("short")
    first = env.manager.active[0]
    await asyncio.sleep(2)
    await env.press("short")
    assert first.outcome == "stopped" and env.manager.active[0] is not first


@scenario
async def test_policy_queue_runs_it_afterwards(env):
    env.add(program("demo", wait("w", 4)))
    env.engine.set_triggers([button_trigger(policy="queue")])
    await env.press("short")
    await env.press("short")
    assert sorted(r.state for r in env.manager.active) == ["queued", "running"]
    await asyncio.sleep(5)
    assert [r.state for r in env.manager.active] == ["running"]


# ------------------------------------------------------------------ robustesse


@scenario
async def test_unknown_program_does_not_break_the_listener(env):
    env.add(program("demo", wait("w", 5)))
    env.engine.set_triggers([button_trigger("bad", program_id="nope"), button_trigger("ok")])
    await env.press("short")
    assert env.running() == ["demo"]  # l'autre déclencheur a bien fonctionné


@scenario
async def test_no_reaction_after_stop(env):
    env.add(program("demo", wait("w", 5)))
    env.engine.set_triggers([button_trigger()])
    await env.engine.stop()
    await env.press("short")
    assert env.running() == []
    await env.engine.start()
    await env.press("short")
    assert env.running() == ["demo"]


@scenario
async def test_start_is_idempotent(env):
    env.add(program("demo", wait("w", 5)))
    env.engine.set_triggers([button_trigger(policy="queue")])
    await env.engine.start()  # déjà démarré dans le décorateur : pas de double abonnement
    await env.press("short")
    assert len(env.manager.active) == 1


# ------------------------------------------------------------------ du bouton physique à l'arrêt


def test_physical_long_press_stops_a_running_scenario_in_under_a_second():
    """Appui réel (broche simulée) maintenu : l'arrêt est effectif avant 1 s."""

    async def main():
        loop = asyncio.get_running_loop()
        config = make_config()
        factory = MockFactory()
        buttons = GpioButtonDriver(
            [Button.model_validate({"id": "bouton_principal", "name": "B", "pin": 21})], factory
        )
        relays = FakeRelayDriver.from_config(config)
        programs = {"demo": program("demo", relay("a", "fantome"), wait("w", 60))}
        manager = RunManager(config, relays, FakeHAClient(), buttons, programs)
        engine = TriggerEngine(
            manager,
            buttons,
            programs,
            [button_trigger("t1", "short"), emergency_stop_for("bouton_principal")],
        )
        await buttons.start()
        await engine.start()
        pin = factory.pin(21)

        pin.drive_low()  # appui court : lance le scénario (après la fenêtre du double)
        await asyncio.sleep(0.1)
        pin.drive_high()
        await asyncio.sleep(1)
        assert [r.program.id for r in manager.active] == ["demo"] and relays.is_on("fantome")

        pressed_at = loop.time()
        pin.drive_low()  # appui long maintenu
        while manager.active:  # noqa: ASYNC110 - sondage en temps virtuel
            await asyncio.sleep(0.01)
        assert loop.time() - pressed_at < 1.0
        assert not relays.is_on("fantome")
        pin.drive_high()
        await engine.stop()
        await buttons.close()
        await manager.shutdown()

    run_virtual(main)


# ------------------------------------------------------------------ modèles et validation


def test_trigger_needs_exactly_one_of_program_or_action():
    with pytest.raises(ValueError, match="program"):
        ButtonTrigger.model_validate(
            {"id": "t", "source": "button", "button": "b", "event": "short"}
        )
    with pytest.raises(ValueError, match="program"):
        button_trigger(program_id="demo", action="stop")


def test_parse_triggers_reports_each_invalid_entry_without_blocking_the_others():
    raw = [
        {"id": "ok", "source": "button", "button": "b", "event": "long", "action": "stop"},
        {"id": "bad", "source": "button", "button": "b", "event": "triple", "program": "p"},
        {"id": "worse", "source": "wifi"},
        "pas un objet",
    ]
    triggers, issues = parse_triggers(raw)
    assert [t.id for t in triggers] == ["ok"]
    assert [i.component_id for i in issues] == ["bad", "worse", None]
    assert all(i.code == "invalid_trigger" for i in issues)


def test_spec_example_loads():
    raw = [
        {
            "id": "t1",
            "source": "button",
            "button": "bouton_principal",
            "event": "short",
            "program": "scenario-principal",
            "policy": "ignore",
        },
        {
            "id": "t2",
            "source": "button",
            "button": "bouton_principal",
            "event": "long",
            "action": "stop",
        },
        {"id": "t3", "source": "schedule", "cron": "0 18 31 10 *", "program": "ambiance-soir"},
    ]
    triggers, issues = parse_triggers(raw)
    assert len(triggers) == 3 and issues == []


def test_validate_triggers():
    config = make_config()
    triggers, _ = parse_triggers(
        [
            {
                "id": "a",
                "source": "button",
                "button": "bouton_principal",
                "event": "short",
                "program": "demo",
            },
            {
                "id": "b",
                "source": "button",
                "button": "bouton_principal",
                "event": "short",
                "program": "demo",
            },
            {
                "id": "c",
                "source": "button",
                "button": "fantome",
                "event": "short",
                "program": "nope",
            },
            {
                "id": "a",
                "source": "button",
                "button": "bouton_principal",
                "event": "long",
                "action": "stop",
            },
        ]
    )
    issues = validate_triggers(triggers, config, {"demo"})
    by_code = {}
    for issue in issues:
        by_code.setdefault(issue.code, []).append((issue.severity, issue.component_id))
    assert by_code["duplicate_id"] == [("error", "a")]
    assert by_code["unknown_button"] == [("error", "c")]
    assert by_code["unknown_program"] == [("error", "c")]
    assert sorted(by_code["duplicate_trigger"]) == [("warning", "a"), ("warning", "b")]


def test_valid_triggers_have_no_issue():
    config = make_config()
    triggers, _ = parse_triggers(
        [
            {
                "id": "a",
                "source": "button",
                "button": "bouton_principal",
                "event": "short",
                "program": "demo",
            },
            {
                "id": "b",
                "source": "button",
                "button": "bouton_principal",
                "event": "long",
                "action": "stop",
            },
        ]
    )
    assert validate_triggers(triggers, config, {"demo"}) == []


def test_emergency_stop_helper():
    trigger = emergency_stop_for("bouton_principal")
    assert (trigger.event, trigger.action, trigger.button) == ("long", "stop", "bouton_principal")
    assert trigger.program is None and trigger.enabled
