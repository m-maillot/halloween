import asyncio
import json
from pathlib import Path

import pytest

from halloween.config import AppConfig
from halloween.drivers import FakeButtonDriver, FakeHAClient, FakeRelayDriver, HAError, Recorder
from halloween.program import Program
from halloween.program.actions import ActionFailed, DeviceActions
from halloween.program.conditions import Conditions
from halloween.program.interpreter import ExecutionError, Interpreter, RunContext
from halloween.program.virtual import run_virtual

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__file__).parent / "data"


def make_config() -> AppConfig:
    raw = json.loads((ROOT / "deploy" / "config.example.json").read_text(encoding="utf-8"))
    raw["relays"] += [
        {
            "id": "robot",
            "name": "Robot",
            "pin": 5,
            "mode": "push",
            "pulse_ms": 200,
            "animation_s": 8,
        },
        {"id": "sirene", "name": "Sirène", "pin": 6, "mode": "push"},
    ]
    raw["switches"] = [{"id": "prise", "name": "Prise", "entity_id": "switch.prise_salon"}]
    return AppConfig.model_validate(raw)


class SlowHA(FakeHAClient):
    async def call_service(self, domain, service, data):
        await asyncio.sleep(2)
        await super().call_service(domain, service, data)


class Env:
    def __init__(self, ha_cls=FakeHAClient):
        loop = asyncio.get_running_loop()
        self.rec = Recorder(now=loop.time)
        self.config = make_config()
        self.relays = FakeRelayDriver.from_config(self.config, self.rec)
        self.ha = ha_cls(self.rec)
        self.actions = DeviceActions(self.config, self.relays, self.ha)
        self.conditions = Conditions(self.relays, FakeButtonDriver([]))
        self.ctx = RunContext("run", self.actions, self.conditions)

    async def run(self, root: dict, *extra: dict):
        scripts = [{"id": "s1", "root": root}] + [
            {"id": f"s{i + 2}", "root": r} for i, r in enumerate(extra)
        ]
        prog = Program.model_validate({"id": "p", "name": "P", "scripts": scripts})
        await Interpreter(self.ctx).run_program(prog)

    async def close(self):
        await self.actions.aclose()
        self.conditions.close()


def scenario(test):
    """Décorateur : exécute le test async en temps virtuel avec un environnement neuf."""

    def wrapper():
        async def main():
            env = Env(getattr(test, "ha_cls", FakeHAClient))
            try:
                await test(env)
            finally:
                await env.close()

        run_virtual(main)

    wrapper.__name__ = test.__name__
    return wrapper


def with_ha(cls):
    def deco(fn):
        fn.ha_cls = cls
        return fn

    return deco


def relay(id_, target, **kw):
    return {"id": id_, "type": "relay", "target": target} | (kw or {"state": "on"})


def light(id_, target, **kw):
    return {"id": id_, "type": "light", "target": target} | (kw or {"state": "on"})


def wait(id_, seconds):
    return {"id": id_, "type": "wait", "seconds": seconds}


def seq(id_, *children):
    return {"id": id_, "type": "sequence", "children": list(children)}


# ------------------------------------------------------------------ relais maintenus


@scenario
async def test_latched_relay_on_off(env):
    await env.run(seq("n", relay("a", "fantome"), wait("w", 2), relay("b", "fantome", state="off")))
    assert env.rec.timeline() == [(0, "fantome", "on"), (2, "fantome", "off")]


# ------------------------------------------------------------------ relais impulsion


@scenario
async def test_push_relay_pulses_for_pulse_ms(env):
    await env.run(seq("n", relay("a", "robot", action="trigger"), relay("b", "fantome")))
    assert env.rec.timeline() == [(0, "robot", "on"), (0.2, "robot", "off"), (0.2, "fantome", "on")]


@scenario
async def test_push_relay_default_pulse_is_500ms(env):
    await env.run(relay("a", "sirene", action="trigger"))
    assert env.rec.timeline() == [(0, "sirene", "on"), (0.5, "sirene", "off")]


@scenario
async def test_second_trigger_during_animation_is_ignored(env):
    await env.run(
        seq(
            "n",
            relay("a", "robot", action="trigger"),
            wait("w1", 1),
            relay("b", "robot", action="trigger"),
            wait("w2", 8),
            relay("c", "robot", action="trigger"),
        )
    )
    pulses = [(t, a) for t, c, a in env.rec.timeline() if c == "robot" and a == "on"]
    assert pulses == [(0, "on"), (9.2, "on")]  # le déclenchement à 1,2 s est ignoré


@scenario
async def test_wait_for_end_waits_until_the_animation_ends(env):
    await env.run(
        seq("n", relay("a", "robot", action="trigger", wait_for_end=True), relay("b", "fantome"))
    )
    assert (8, "fantome", "on") in env.rec.timeline()


@scenario
async def test_wait_for_end_on_a_busy_object_waits_for_the_running_animation(env):
    await env.run(
        seq(
            "n",
            relay("a", "robot", action="trigger"),
            wait("w", 3),
            relay("b", "robot", action="trigger", wait_for_end=True),
            relay("c", "fantome"),
        )
    )
    assert [e for e in env.rec.timeline() if e[1] == "robot"] == [
        (0, "robot", "on"),
        (0.2, "robot", "off"),
    ]
    assert (8, "fantome", "on") in env.rec.timeline()


@scenario
async def test_pulse_is_closed_when_the_run_is_cancelled(env):
    task = asyncio.ensure_future(env.run(relay("a", "sirene", action="trigger")))
    await asyncio.sleep(0.1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert not env.relays.is_on("sirene")


# ------------------------------------------------------------------ Home Assistant


@scenario
async def test_light_and_switch_calls(env):
    await env.run(
        seq(
            "n",
            light("a", "bandeau", state="on", rgb_color=[255, 0, 0], brightness=40, transition=2),
            light("b", "bandeau", state="off"),
            {"id": "c", "type": "switch", "target": "prise", "state": "on"},
            {"id": "d", "type": "switch", "target": "prise", "state": "off"},
        )
    )
    assert env.ha.calls == [
        (
            "light",
            "turn_on",
            {
                "entity_id": "light.bandeau_hue",
                "rgb_color": [255, 0, 0],
                "brightness": 40,
                "transition": 2,
            },
        ),
        ("light", "turn_off", {"entity_id": "light.bandeau_hue"}),
        ("switch", "turn_on", {"entity_id": "switch.prise_salon"}),
        ("switch", "turn_off", {"entity_id": "switch.prise_salon"}),
    ]


@scenario
async def test_ha_failure_is_logged_and_the_run_continues_by_default(env):
    env.ha.fail_with = HAError("injoignable")
    await env.run(seq("n", light("a", "bandeau"), relay("b", "fantome")))
    assert env.relays.is_on("fantome")


@scenario
async def test_ha_failure_aborts_the_run_when_asked(env):
    env.ha.fail_with = HAError("injoignable")
    with pytest.raises(ActionFailed, match="a"):
        await env.run(
            seq("n", light("a", "bandeau", state="on", on_error="abort"), relay("b", "fantome"))
        )
    assert not env.relays.is_on("fantome")


@scenario
async def test_relay_driver_failure_follows_the_same_policy(env):
    env.relays.fail_on["fantome"] = OSError("GPIO")
    await env.run(seq("n", relay("a", "fantome"), relay("b", "orage")))
    assert env.relays.is_on("orage")
    with pytest.raises(ActionFailed):
        await env.run(relay("c", "fantome", state="on", on_error="abort"))


@scenario
@with_ha(SlowHA)
async def test_blocking_ha_call_delays_the_sequence(env):
    await env.run(seq("n", light("a", "bandeau"), relay("b", "fantome")))
    assert (2, "fantome", "on") in env.rec.timeline()


@scenario
@with_ha(SlowHA)
async def test_fire_and_forget_does_not_wait_for_ha(env):
    await env.run(
        seq("n", light("a", "bandeau", state="on", fire_and_forget=True), relay("b", "fantome"))
    )
    assert (0, "fantome", "on") in env.rec.timeline()
    assert env.ha.calls == []  # l'appel est encore en cours
    await asyncio.sleep(3)
    assert len(env.ha.calls) == 1


@scenario
async def test_fire_and_forget_failure_is_only_logged(env):
    env.ha.fail_with = HAError("boum")
    await env.run(light("a", "bandeau", state="on", fire_and_forget=True, on_error="abort"))
    await asyncio.sleep(0.1)  # ne lève pas


@scenario
@with_ha(SlowHA)
async def test_aclose_cancels_pending_background_calls(env):
    await env.run(light("a", "bandeau", state="on", fire_and_forget=True))
    await env.actions.aclose()
    await asyncio.sleep(5)
    assert env.ha.calls == []


# ------------------------------------------------------------------ incohérences à l'exécution


@scenario
async def test_unknown_components_raise_execution_errors(env):
    for node in (
        relay("a", "nope"),
        light("b", "nope"),
        {"id": "c", "type": "switch", "target": "nope", "state": "on"},
    ):
        with pytest.raises(ExecutionError, match="inconnu"):
            await env.run(node)


@scenario
async def test_mode_mismatch_raises_even_with_continue_policy(env):
    with pytest.raises(ExecutionError, match="impulsion"):
        await env.run(relay("a", "robot", state="on"))
    with pytest.raises(ExecutionError, match="maintenu"):
        await env.run(relay("b", "fantome", action="trigger"))


# ------------------------------------------------------------------ bout en bout


@scenario
async def test_main_scenario_end_to_end(env):
    prog = Program.model_validate(
        json.loads((DATA / "scenario_principal.json").read_text(encoding="utf-8"))
    )
    await Interpreter(env.ctx).run_program(prog)
    relay_events = [e for e in env.rec.timeline() if not e[1].startswith("light.")]
    assert sorted(relay_events[:2]) == [(3, "fantome", "on"), (3, "orage", "on")]
    assert (11, "squelette", "on") in relay_events and (17, "squelette", "off") in relay_events
    assert relay_events[-1] == (17, "epouvantail", "on")
    assert env.ha.calls[0][2]["rgb_color"] == [255, 0, 0]
    assert [r for r in ("fantome", "squelette", "orage", "epouvantail") if env.relays.is_on(r)] == [
        "epouvantail"
    ]


@scenario
async def test_failed_pulse_does_not_mark_the_object_busy(env):
    env.relays.fail_on["robot"] = OSError("GPIO")
    await env.run(relay("a", "robot", action="trigger"))
    del env.relays.fail_on["robot"]
    await env.run(relay("b", "robot", action="trigger"))
    robot = [e for e in env.rec.timeline() if e[1] == "robot"]
    assert robot == [(0, "robot", "on"), (0.2, "robot", "off")]


@scenario
async def test_background_errors_never_reach_the_loop_handler(env):
    unhandled = []
    asyncio.get_running_loop().set_exception_handler(lambda _loop, ctx: unhandled.append(ctx))
    await env.run(light("a", "nope", state="on", fire_and_forget=True))
    await asyncio.sleep(0.1)
    import gc

    gc.collect()
    assert unhandled == []
