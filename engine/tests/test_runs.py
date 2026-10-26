import asyncio
import json
from pathlib import Path

import pytest

from halloween.config import AppConfig
from halloween.drivers import FakeButtonDriver, FakeHAClient, FakeRelayDriver, Recorder
from halloween.program import Program
from halloween.program.runs import AlreadyRunning, RunEvent, RunManager, TooManyRuns
from halloween.program.virtual import run_virtual

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__file__).parent / "data"


def make_config() -> AppConfig:
    raw = json.loads((ROOT / "deploy" / "config.example.json").read_text(encoding="utf-8"))
    raw["relays"].append(
        {"id": "robot", "name": "Robot", "pin": 5, "mode": "push", "animation_s": 4}
    )
    return AppConfig.model_validate(raw)


class Env:
    def __init__(self):
        loop = asyncio.get_running_loop()
        self.loop = loop
        self.rec = Recorder(now=loop.time)
        self.config = make_config()
        self.relays = FakeRelayDriver.from_config(self.config, self.rec)
        self.ha = FakeHAClient(self.rec)
        self.programs: dict[str, Program] = {}
        self.events: list[RunEvent] = []
        self.manager = RunManager(
            self.config,
            self.relays,
            self.ha,
            FakeButtonDriver(["bouton_principal"]),
            self.programs,
            on_event=self.events.append,
        )

    def add(self, id_: str, root: dict, *extra: dict, **kw) -> Program:
        scripts = [{"id": "s1", "root": root}] + [
            {"id": f"s{i + 2}", "root": r} for i, r in enumerate(extra)
        ]
        prog = Program.model_validate({"id": id_, "name": id_, "scripts": scripts, **kw})
        self.programs[id_] = prog
        return prog

    def kinds(self, run_id=None):
        return [e.kind for e in self.events if run_id is None or e.run_id == run_id]

    def rest_calls(self):
        return [c for c in self.ha.calls if c[2].get("brightness") in (60, 150)]


def scenario(test):
    def wrapper():
        async def main():
            env = Env()
            try:
                await test(env)
            finally:
                await env.manager.shutdown()

        run_virtual(main)

    wrapper.__name__ = test.__name__
    return wrapper


def relay(id_, target, state="on"):
    return {"id": id_, "type": "relay", "target": target, "state": state}


def light(id_, target, state="on", **kw):
    return {"id": id_, "type": "light", "target": target, "state": state, **kw}


def wait(id_, seconds=1):
    return {"id": id_, "type": "wait", "seconds": seconds}


def seq(id_, *children):
    return {"id": id_, "type": "sequence", "children": list(children)}


def forever(id_, body):
    return {"id": id_, "type": "repeat", "forever": True, "child": body}


# ------------------------------------------------------------------ cycle de vie


@scenario
async def test_run_completes_and_is_removed(env):
    prog = env.add("p", seq("n", relay("a", "fantome"), wait("w", 3)))
    run = await env.manager.start(prog)
    assert run.state == "running" and env.manager.active == [run]
    await run.done.wait()
    assert (run.state, run.outcome, run.error) == ("ended", "completed", None)
    assert env.manager.active == [] and env.manager.get(run.id) is None
    assert run.ended_at - run.started_at == 3
    assert env.kinds(run.id)[0] == "run_started" and env.kinds(run.id)[-1] == "run_ended"
    assert {"node_started", "node_finished"} <= set(env.kinds(run.id))
    assert env.events[-1].outcome == "completed"


@scenario
async def test_node_events_carry_the_script_id(env):
    run = await env.manager.start(env.add("p", wait("w"), wait("x")))
    await run.done.wait()
    started = {(e.script_id, e.node_id) for e in env.events if e.kind == "node_started"}
    assert started == {("s1", "w"), ("s2", "x")}


@scenario
async def test_stopping_a_run_before_it_took_its_first_step(env):
    run = await env.manager.start(env.add("p", seq("n", relay("a", "fantome"), wait("w", 5))))
    await env.manager.stop(run.id)  # aucune cession entre start et stop : la tâche n'a pas démarré
    assert (run.state, run.outcome) == ("ended", "stopped")
    assert env.manager.active == [] and not env.relays.is_on("fantome")
    other = await env.manager.start(env.add("q", wait("w", 5)))
    await env.manager.stop_all()
    assert other.outcome == "stopped" and env.manager.active == []


@scenario
async def test_failed_run_reports_the_error_and_other_runs_continue(env):
    boom = env.add("boom", light("a", "bandeau", "on", on_error="abort"))
    calm = env.add("calm", forever("r", wait("w", 5)))
    env.ha.fail_entities["light.bandeau_hue"] = RuntimeError("HA HS")
    calm_run = await env.manager.start(calm)
    bad = await env.manager.start(boom)
    await bad.done.wait()
    assert bad.outcome == "failed" and "HA HS" in bad.error
    assert calm_run.state == "running"


@scenario
async def test_max_duration_stops_the_run_with_timeout(env):
    prog = env.add("p", seq("n", relay("a", "fantome"), wait("w", 100)), max_duration_s=10)
    run = await env.manager.start(prog)
    await run.done.wait()
    assert run.outcome == "timeout" and run.ended_at - run.started_at == 10
    assert not env.relays.is_on("fantome")  # reset à la fin


# ------------------------------------------------------------------ concurrence et politiques


@scenario
async def test_ambience_keeps_running_while_a_scenario_runs_and_stops(env):
    ambiance = env.add("ambiance", forever("r", seq("b", light("l", "guirlande"), wait("w", 2))))
    scenario_ = env.add("scenario", seq("n", relay("a", "fantome"), wait("w", 5)))
    amb = await env.manager.start(ambiance)
    sc = await env.manager.start(scenario_)
    assert len(env.manager.active) == 2
    await env.manager.stop(sc.id)
    assert sc.outcome == "stopped" and amb.state == "running"
    assert not env.relays.is_on("fantome")
    await asyncio.sleep(10)
    assert amb.state == "running"


@scenario
async def test_ignore_policy_refuses_a_second_run_of_the_same_program(env):
    prog = env.add("p", wait("w", 10))
    first = await env.manager.start(prog)
    with pytest.raises(AlreadyRunning) as exc:
        await env.manager.start(prog)
    assert exc.value.run is first
    assert len(env.manager.active) == 1


@scenario
async def test_restart_policy_stops_the_old_run_and_starts_a_new_one(env):
    prog = env.add("p", seq("n", wait("w", 10), relay("a", "fantome")))
    first = await env.manager.start(prog)
    await asyncio.sleep(3)
    second = await env.manager.start(prog, "restart")
    assert first.outcome == "stopped" and second.state == "running" and second is not first
    await second.done.wait()
    assert second.started_at == 3 and second.ended_at == 13


@scenario
async def test_queue_policy_runs_after_the_current_one(env):
    prog = env.add("p", seq("n", relay("a", "fantome"), wait("w", 4), relay("b", "fantome", "off")))
    first = await env.manager.start(prog)
    second = await env.manager.start(prog, "queue")
    assert (first.state, second.state) == ("running", "queued")
    with pytest.raises(AlreadyRunning) as exc:  # une seule exécution en file
        await env.manager.start(prog, "queue")
    assert exc.value.run is second
    await second.done.wait()
    assert (first.outcome, second.outcome) == ("completed", "completed")
    assert second.started_at == first.ended_at == 4


@scenario
async def test_stopping_a_queued_run_cancels_it_without_reset_or_events(env):
    prog = env.add("p", wait("w", 4))
    first = await env.manager.start(prog)
    queued = await env.manager.start(prog, "queue")
    await env.manager.stop(queued.id)
    assert queued.outcome == "stopped" and first.state == "running"
    assert "run_started" not in env.kinds(queued.id)


@scenario
async def test_too_many_runs(env):
    for i in range(20):
        await env.manager.start(env.add(f"p{i}", forever("r", wait("w", 1))))
    with pytest.raises(TooManyRuns):
        await env.manager.start(env.add("one-too-many", wait("w")))


# ------------------------------------------------------------------ état de repos


@scenario
async def test_reset_only_touches_components_the_run_still_owns(env):
    scenario_ = env.add(
        "scenario",
        seq("n", relay("a", "fantome"), light("b", "bandeau", rgb_color=[255, 0, 0]), wait("w", 6)),
    )
    taker = env.add(
        "taker", seq("m", wait("tw", 2), light("c", "bandeau", brightness=10), wait("t2", 20))
    )
    sc = await env.manager.start(scenario_)
    await env.manager.start(taker)
    await sc.done.wait()
    assert not env.relays.is_on("fantome")  # propriété du scénario : remis au repos
    bandeau_calls = [c for c in env.ha.calls if c[2]["entity_id"] == "light.bandeau_hue"]
    assert all(c[2].get("brightness") != 60 for c in bandeau_calls)  # le repos n'a pas été appliqué


@scenario
async def test_reset_applies_the_rest_state_of_owned_lights(env):
    run = await env.manager.start(
        env.add("p", seq("n", light("a", "bandeau", rgb_color=[1, 2, 3]), wait("w", 2)))
    )
    await run.done.wait()
    assert env.ha.calls[-1] == (
        "light",
        "turn_on",
        {
            "entity_id": "light.bandeau_hue",
            "rgb_color": [255, 120, 0],
            "brightness": 60,
            "transition": 2,
        },
    )


@scenario
async def test_on_end_keep_leaves_everything_as_is(env):
    run = await env.manager.start(env.add("p", relay("a", "fantome"), on_end="keep"))
    await run.done.wait()
    assert env.relays.is_on("fantome")


@scenario
async def test_component_without_rest_state_is_left_alone(env):
    run = await env.manager.start(
        env.add("p", seq("n", {"id": "s", "type": "light", "target": "bandeau", "state": "off"}))
    )
    await run.done.wait()
    assert env.ha.calls[-1][1] == "turn_on"  # repos du bandeau (défini) appliqué après l'extinction


@scenario
async def test_stopped_run_is_reset_too(env):
    run = await env.manager.start(env.add("p", seq("n", relay("a", "fantome"), wait("w", 50))))
    await asyncio.sleep(1)
    assert env.relays.is_on("fantome")
    await env.manager.stop(run.id)
    assert not env.relays.is_on("fantome")


@scenario
async def test_stop_all_stops_everything_instantly_and_applies_full_rest_state(env):
    a = await env.manager.start(env.add("a", seq("n", relay("x", "fantome"), wait("w", 100))))
    b = await env.manager.start(
        env.add("b", forever("r", seq("s", relay("y", "orage"), wait("w2", 1))))
    )
    await env.manager.start(env.add("c", seq("m", wait("wc", 5), relay("z", "squelette"))))
    await asyncio.sleep(2)
    t0 = env.loop.time()
    await env.manager.stop_all()
    assert env.loop.time() == t0  # aucune attente : effectif immédiatement
    assert (a.outcome, b.outcome) == ("stopped", "stopped")
    assert env.manager.active == []
    assert not any(env.relays.is_on(r.id) for r in env.config.relays)
    assert len(env.rest_calls()) == 2  # bandeau et guirlande remis au repos


@scenario
async def test_reset_all_at_startup(env):
    await env.relays.set("orage", True)
    await env.manager.reset_all()
    assert not env.relays.is_on("orage")
    assert {c[2]["entity_id"] for c in env.rest_calls()} == {
        "light.bandeau_hue",
        "light.twinkly_halloween",
    }


@scenario
async def test_a_failing_device_does_not_prevent_other_resets(env):
    env.ha.fail_entities["light.bandeau_hue"] = RuntimeError("HS")
    await env.relays.set("orage", True)
    await env.manager.reset_all()
    assert not env.relays.is_on("orage")
    assert [c[2]["entity_id"] for c in env.rest_calls()] == ["light.twinkly_halloween"]


@scenario
async def test_stop_of_unknown_or_ended_run_is_a_noop(env):
    await env.manager.stop("nope")
    run = await env.manager.start(env.add("p", wait("w")))
    await run.done.wait()
    await env.manager.stop(run.id)


@scenario
async def test_main_scenario_runs_with_the_manager(env):
    prog = Program.model_validate(
        json.loads((DATA / "scenario_principal.json").read_text(encoding="utf-8"))
    )
    env.programs[prog.id] = prog
    run = await env.manager.start(prog)
    await run.done.wait()
    assert run.outcome == "completed" and run.ended_at - run.started_at == 17
    # fin de run avec on_end=reset : tout est remis au repos, y compris l'épouvantail
    assert not any(env.relays.is_on(r.id) for r in env.config.relays)
