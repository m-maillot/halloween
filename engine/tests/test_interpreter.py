import asyncio
import io
import json
import random

import pytest

from halloween.drivers import FakeButtonDriver, FakeRelayDriver
from halloween.log import setup_logging
from halloween.program import Program
from halloween.program.conditions import Conditions
from halloween.program.interpreter import (
    ActionRunner,
    ExecutionError,
    Interpreter,
    NodeEvent,
    RunContext,
)
from halloween.program.virtual import SimulationDeadlock, run_virtual


class Recording(ActionRunner):
    """Enregistre (temps virtuel, id du bloc) à chaque action ; peut échouer sur un bloc."""

    def __init__(self, fail_on: str | None = None):
        self.log: list[tuple[float, str]] = []
        self.fail_on = fail_on

    async def execute(self, node):
        if node.id == self.fail_on:
            raise RuntimeError(f"échec sur {node.id}")
        self.log.append((asyncio.get_running_loop().time(), node.id))


def act(id_: str) -> dict:
    return {"id": id_, "type": "relay", "target": "r", "state": "on"}


def wait(id_: str, seconds: float = 1) -> dict:
    return {"id": id_, "type": "wait", "seconds": seconds}


def seq(id_: str, *children: dict) -> dict:
    return {"id": id_, "type": "sequence", "children": list(children)}


def program(root: dict, *extra_roots: dict, id_: str = "p") -> Program:
    scripts = [{"id": "s1", "root": root}] + [
        {"id": f"s{i + 2}", "root": r} for i, r in enumerate(extra_roots)
    ]
    return Program.model_validate({"id": id_, "name": "P", "scripts": scripts})


class Run:
    """Résultat d'une exécution simulée."""

    def __init__(self):
        self.actions = Recording()
        self.events: list[NodeEvent] = []
        self.elapsed = 0.0
        self.relays = FakeRelayDriver(["r", "r2"])
        self.buttons = FakeButtonDriver(["b"])

    @property
    def times(self) -> dict[str, float]:
        return {node_id: t for t, node_id in self.actions.log}

    @property
    def ids(self) -> list[str]:
        return [node_id for _, node_id in self.actions.log]


def execute(prog: Program, *, seed=0, programs=None, fail_on=None, side=None, timeout=None) -> Run:
    """Exécute `prog` en temps virtuel. `side(run)` : coroutine jouée en parallèle (ex. appuis)."""
    run = Run()
    run.actions.fail_on = fail_on

    async def main():
        rng = random.Random(seed)
        conditions = Conditions(run.relays, run.buttons, rng)
        ctx = RunContext(
            "run-1", run.actions, conditions, programs or {}, rng, emit=run.events.append
        )
        loop = asyncio.get_running_loop()
        start = loop.time()
        side_task = asyncio.ensure_future(side(run)) if side else None
        try:
            coro = Interpreter(ctx).run_program(prog)
            await (asyncio.wait_for(coro, timeout) if timeout else coro)
        finally:
            run.elapsed = loop.time() - start
            conditions.close()
            if side_task:
                side_task.cancel()

    run_virtual(main)
    return run


# ------------------------------------------------------------------ temps virtuel


def test_virtual_time_is_instant_and_exact():
    async def main():
        loop = asyncio.get_running_loop()
        await asyncio.gather(asyncio.sleep(3600), asyncio.sleep(10))
        return loop.time()

    assert run_virtual(main) == 3600


def test_deadlock_is_reported_instead_of_hanging():
    async def main():
        await asyncio.Event().wait()

    with pytest.raises(SimulationDeadlock):
        run_virtual(main)


# ------------------------------------------------------------------ séquence / parallèle


def test_sequence_runs_in_order_with_waits():
    run = execute(program(seq("n", wait("w1", 2), act("a"), wait("w2", 3), act("b"))))
    assert run.times == {"a": 2, "b": 5}
    assert run.elapsed == 5


def test_empty_sequence_and_parallel_do_nothing():
    run = execute(program(seq("n", {"id": "p", "type": "parallel", "children": []})))
    assert run.ids == [] and run.elapsed == 0


def test_parallel_all_waits_for_the_slowest_branch():
    par = {
        "id": "par",
        "type": "parallel",
        "children": [seq("b1", wait("w1", 1), act("a")), seq("b2", wait("w2", 3), act("b"))],
    }
    run = execute(program(seq("n", par, act("after"))))
    assert run.times == {"a": 1, "b": 3, "after": 3}


def test_parallel_first_stops_the_other_branches():
    par = {
        "id": "par",
        "type": "parallel",
        "until": "first",
        "children": [seq("b1", wait("w1", 1), act("fast")), seq("b2", wait("w2", 5), act("slow"))],
    }
    run = execute(program(seq("n", par, act("after"))))
    assert run.times == {"fast": 1, "after": 1}
    assert run.elapsed == 1


def test_error_in_one_branch_cancels_the_others_and_propagates():
    par = {
        "id": "par",
        "type": "parallel",
        "children": [seq("b1", wait("w1", 1), act("boom")), seq("b2", wait("w2", 5), act("late"))],
    }
    with pytest.raises(RuntimeError, match="boom"):
        execute(program(par), fail_on="boom")


def test_simultaneous_branch_failures_leave_no_unretrieved_exception():
    import gc

    unhandled = []
    par = {"id": "par", "type": "parallel", "children": [act("boom1"), act("boom2")]}

    class FailAll(Recording):
        async def execute(self, node):
            raise RuntimeError(node.id)

    async def main():
        asyncio.get_running_loop().set_exception_handler(lambda _loop, ctx: unhandled.append(ctx))
        run = Run()
        conditions = Conditions(run.relays, run.buttons)
        ctx = RunContext("r", FailAll(), conditions)
        with pytest.raises(RuntimeError):
            await Interpreter(ctx).run_program(program(par))
        conditions.close()
        gc.collect()

    run_virtual(main)
    assert unhandled == []


def test_scripts_run_in_parallel():
    run = execute(program(seq("a", wait("w1", 5), act("x")), seq("b", wait("w2", 2), act("y"))))
    assert run.times == {"y": 2, "x": 5}
    assert run.elapsed == 5


def test_error_in_one_script_cancels_the_other():
    p = program(seq("a", wait("w1", 1), act("boom")), seq("b", wait("w2", 5), act("late")))
    with pytest.raises(RuntimeError):
        execute(p, fail_on="boom")


def test_cancellation_stops_pending_actions():
    p = program(seq("n", wait("w1", 1), act("a"), wait("w2", 10), act("never")))
    with pytest.raises(TimeoutError):
        execute(p, timeout=5)


# ------------------------------------------------------------------ répétition


def test_repeat_times():
    loop_body = seq("body", wait("w"), act("a"))
    run = execute(program({"id": "r", "type": "repeat", "times": 3, "child": loop_body}))
    assert [t for t, _ in run.actions.log] == [1, 2, 3]


def test_repeat_forever_is_stopped_by_timeout():
    loop_body = seq("body", wait("w"), act("a"))
    with pytest.raises(TimeoutError):
        execute(
            program({"id": "r", "type": "repeat", "forever": True, "child": loop_body}),
            timeout=10.5,
        )


def test_busy_forever_loop_yields_to_other_tasks():
    async def main():
        run = Run()
        conditions = Conditions(run.relays, run.buttons)
        ctx = RunContext("r", run.actions, conditions)
        prog = program({"id": "r", "type": "repeat", "forever": True, "child": act("a")})
        task = asyncio.ensure_future(Interpreter(ctx).run_program(prog))
        for _ in range(50):
            await asyncio.sleep(0)  # ne rend la main que si la boucle cède
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        conditions.close()
        return len(run.actions.log)

    assert run_virtual(main) > 10


# ------------------------------------------------------------------ attentes et hasard


def test_random_wait_is_within_bounds_and_reproducible():
    node = {"id": "w", "type": "wait", "min": 1, "max": 3}
    first = execute(program(seq("n", node, act("a"))), seed=7)
    again = execute(program(seq("n", node, act("a"))), seed=7)
    other = execute(program(seq("n", node, act("a"))), seed=8)
    assert 1 <= first.times["a"] <= 3
    assert first.times == again.times
    assert first.times != other.times


def test_random_choice_follows_weights():
    node = {
        "id": "rc",
        "type": "random_choice",
        "choices": [
            {"weight": 1000, "child": act("often")},
            {"weight": 1, "child": act("rare")},
        ],
    }
    run = execute(program({"id": "r", "type": "repeat", "times": 50, "child": node}), seed=3)
    assert run.ids.count("often") >= 45
    assert run.ids.count("often") + run.ids.count("rare") == 50


# ------------------------------------------------------------------ conditions


@pytest.mark.parametrize(("probability", "expected"), [(1.0, "yes"), (0.0, "no")])
def test_if_random_picks_a_branch(probability, expected):
    node = {
        "id": "i",
        "type": "if",
        "condition": {"type": "random", "probability": probability},
        "then": act("yes"),
        "else": act("no"),
    }
    assert execute(program(node)).ids == [expected]


def test_if_without_else_does_nothing_when_false():
    node = {
        "id": "i",
        "type": "if",
        "condition": {"type": "random", "probability": 0},
        "then": act("yes"),
    }
    assert execute(program(node)).ids == []


def test_if_relay_is_reads_the_commanded_state():
    node = {
        "id": "i",
        "type": "if",
        "condition": {"type": "relay_is", "id": "r", "state": "on"},
        "then": act("on"),
        "else": act("off"),
    }

    async def turn_on(run):
        await run.relays.set("r", True)

    assert execute(program(seq("n", wait("w", 1), node)), side=turn_on).ids == ["on"]
    assert execute(program(seq("n", wait("w", 1), node))).ids == ["off"]


def test_if_button_is_true_when_pressed_since_run_start():
    cond = {"type": "button", "id": "b", "event": "short"}
    node = {"id": "i", "type": "if", "condition": cond, "then": act("pressed"), "else": act("not")}

    async def press_at_1(run):
        await asyncio.sleep(1)
        await run.buttons.press("b", "short")

    late = program(seq("n", wait("w", 2), node))
    assert execute(late, side=press_at_1).ids == ["pressed"]
    early = program(seq("n", wait("w", 0.5), node))
    assert execute(early, side=press_at_1).ids == ["not"]


def test_wait_until_button_waits_for_the_next_press():
    cond = {"type": "button", "id": "b", "event": "long"}
    p = program(seq("n", {"id": "u", "type": "wait_until", "condition": cond}, act("go")))

    async def presses(run):
        await asyncio.sleep(1)
        await run.buttons.press("b", "short")  # autre événement : ignoré
        await asyncio.sleep(3)
        await run.buttons.press("b", "long")

    run = execute(p, side=presses)
    assert run.times == {"go": 4}


def test_wait_until_does_not_see_presses_from_before_the_block():
    cond = {"type": "button", "id": "b", "event": "short"}
    p = program(
        seq(
            "n",
            wait("w", 2),
            {"id": "u", "type": "wait_until", "condition": cond, "timeout_s": 3},
            act("go"),
        )
    )

    async def early_press(run):
        await asyncio.sleep(1)
        await run.buttons.press("b", "short")

    assert execute(p, side=early_press).times == {"go": 5}  # a attendu le délai complet


def test_wait_until_timeout_continues_with_the_next_block():
    cond = {"type": "button", "id": "b", "event": "short"}
    p = program(
        seq("n", {"id": "u", "type": "wait_until", "condition": cond, "timeout_s": 2}, act("go"))
    )
    assert execute(p).times == {"go": 2}


def test_wait_until_relay_state():
    cond = {"type": "relay_is", "id": "r", "state": "on"}
    p = program(seq("n", {"id": "u", "type": "wait_until", "condition": cond}, act("go")))

    async def turn_on(run):
        await asyncio.sleep(1)
        await run.relays.set("r", True)

    t = execute(p, side=turn_on).times["go"]
    assert 1 <= t <= 1.1


def test_wait_until_without_timeout_and_no_event_is_a_deadlock():
    cond = {"type": "button", "id": "b", "event": "short"}
    p = program({"id": "u", "type": "wait_until", "condition": cond})
    with pytest.raises(SimulationDeadlock):
        execute(p)


# ------------------------------------------------------------------ appels, journal, événements


def test_call_runs_the_other_program_inline():
    sub = program(seq("s", wait("sw", 2), act("sub-action")), id_="sub")
    caller = program(seq("n", {"id": "c", "type": "call", "program_id": "sub"}, act("after")))
    run = execute(caller, programs={"sub": sub})
    assert run.times == {"sub-action": 2, "after": 2}


def test_call_unknown_program():
    with pytest.raises(ExecutionError, match="inconnu"):
        execute(program({"id": "c", "type": "call", "program_id": "nope"}))


def test_runtime_guard_against_endless_recursion():
    loop = program({"id": "c", "type": "call", "program_id": "loop"}, id_="loop")
    with pytest.raises(ExecutionError, match="profonds"):
        execute(loop, programs={"loop": loop})


def test_log_block_writes_a_json_line_with_context():
    stream = io.StringIO()
    setup_logging("INFO", stream)
    try:
        execute(program({"id": "l1", "type": "log", "message": "coucou"}))
    finally:
        setup_logging()
    (line,) = [json.loads(x) for x in stream.getvalue().splitlines() if "coucou" in x]
    assert line["node_id"] == "l1" and line["script_id"] == "s1"


def test_node_events_are_emitted_in_order_with_script_ids():
    run = execute(program(seq("n", wait("w"), act("a")), wait("other", 1)))
    s1 = [(e.kind, e.node_id) for e in run.events if e.script_id == "s1"]
    assert s1 == [
        ("started", "n"),
        ("started", "w"),
        ("finished", "w"),
        ("started", "a"),
        ("finished", "a"),
        ("finished", "n"),
    ]
    assert {e.script_id for e in run.events} == {"s1", "s2"}


def test_finished_is_emitted_for_cancelled_blocks():
    p = program(seq("n", wait("w", 10)))
    events: list[NodeEvent] = []
    run = Run()

    async def main():
        conditions = Conditions(run.relays, run.buttons)
        ctx = RunContext("r", Recording(), conditions, emit=events.append)
        try:
            await asyncio.wait_for(Interpreter(ctx).run_program(p), 1)
        except TimeoutError:
            pass
        conditions.close()

    run_virtual(main)
    assert [(e.kind, e.node_id) for e in events] == [
        ("started", "n"),
        ("started", "w"),
        ("finished", "w"),
        ("finished", "n"),
    ]
