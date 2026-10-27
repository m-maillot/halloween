import asyncio

from halloween.events import (
    ErrorEvent,
    EventHub,
    NodeStartedEvent,
    RunEndedEvent,
    RunStartedEvent,
    from_run_event,
)
from halloween.program.runs import RunEvent


async def drain(subscription, count):
    items = []
    async for item in subscription:
        items.append(item)
        if len(items) == count:
            break
    return items


async def test_publish_reaches_every_subscriber_as_json():
    hub = EventHub()
    a, b = hub.subscribe(), hub.subscribe()
    hub.publish(RunStartedEvent(run_id="r1", program_id="p"))
    for sub in (a, b):
        (event,) = await drain(sub, 1)
        assert event["type"] == "run_started" and event["run_id"] == "r1" and event["ts"] > 0


async def test_slow_subscriber_loses_the_oldest_events_but_never_blocks_the_engine():
    hub = EventHub(maxsize=3)
    slow = hub.subscribe()
    for i in range(10):
        hub.publish(RunStartedEvent(run_id=f"r{i}", program_id="p"))
    events = await drain(slow, 3)
    assert [e["run_id"] for e in events] == ["r7", "r8", "r9"] and slow.dropped == 7


async def test_close_ends_the_iteration_and_unsubscribe_stops_delivery():
    hub = EventHub()
    kept, left = hub.subscribe(), hub.subscribe()
    left.close()
    hub.publish(RunStartedEvent(run_id="r", program_id="p"))
    hub.close()
    assert [e["run_id"] async for e in kept] == ["r"]  # reçoit puis se termine
    assert hub._subscribers == set()
    assert left._queue.empty()


def test_run_events_are_converted_and_failures_add_an_error_event():
    started = from_run_event(RunEvent("run_started", "r", "p"))
    assert isinstance(started[0], RunStartedEvent)
    node = from_run_event(RunEvent("node_started", "r", "p", "s1", "n3"))[0]
    assert isinstance(node, NodeStartedEvent) and (node.script_id, node.node_id) == ("s1", "n3")
    ok = from_run_event(RunEvent("run_ended", "r", "p", outcome="completed"))
    assert [type(e) for e in ok] == [RunEndedEvent]
    failed = from_run_event(RunEvent("run_ended", "r", "p", outcome="failed", error="HA HS"))
    assert [type(e) for e in failed] == [RunEndedEvent, ErrorEvent]
    assert failed[1].message == "HA HS" and failed[1].source == "run"


def test_hub_needs_no_running_loop_to_publish():
    EventHub().publish(RunStartedEvent(run_id="r", program_id="p"))
    asyncio.run(asyncio.sleep(0))
