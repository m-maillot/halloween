import json
from pathlib import Path

import pytest

from halloween.config import AppConfig
from halloween.drivers import (
    ButtonEvent,
    FakeButtonDriver,
    FakeHAClient,
    FakeRelayDriver,
    HAClient,
    HAError,
    Recorder,
    RelayDriver,
)

EXAMPLE = Path(__file__).resolve().parents[2] / "deploy" / "config.example.json"


def test_interfaces_are_abstract():
    for cls in (RelayDriver, HAClient):
        with pytest.raises(TypeError):
            cls()


class TestFakeRelayDriver:
    async def test_set_and_state(self):
        driver = FakeRelayDriver(["a", "b"])
        assert not driver.is_on("a")
        await driver.set("a", True)
        assert driver.is_on("a") and not driver.is_on("b")
        await driver.set("a", False)
        assert not driver.is_on("a")

    async def test_unknown_relay(self):
        driver = FakeRelayDriver(["a"])
        with pytest.raises(KeyError, match="zzz"):
            await driver.set("zzz", True)
        with pytest.raises(KeyError):
            driver.is_on("zzz")

    async def test_records_timeline_with_injected_clock(self):
        now = [0.0]
        rec = Recorder(now=lambda: now[0])
        driver = FakeRelayDriver(["a"], rec)
        await driver.set("a", True)
        now[0] = 2.5
        await driver.set("a", False)
        assert rec.timeline() == [(0.0, "a", "on"), (2.5, "a", "off")]

    async def test_all_off_only_touches_relays_that_are_on(self):
        rec = Recorder()
        driver = FakeRelayDriver(["a", "b", "c"], rec)
        await driver.set("a", True)
        await driver.set("c", True)
        rec.entries.clear()
        await driver.all_off()
        assert not any(driver.is_on(r) for r in "abc")
        assert sorted(e.component for e in rec.entries) == ["a", "c"]

    async def test_injected_failure(self):
        driver = FakeRelayDriver(["a"])
        driver.fail_on["a"] = RuntimeError("GPIO HS")
        with pytest.raises(RuntimeError):
            await driver.set("a", True)
        assert not driver.is_on("a")

    def test_from_config(self):
        config = AppConfig.model_validate(json.loads(EXAMPLE.read_text(encoding="utf-8")))
        driver = FakeRelayDriver.from_config(config)
        assert not driver.is_on("fantome") and not driver.is_on("orage")


class TestFakeButtonDriver:
    async def test_subscribers_receive_events(self):
        driver = FakeButtonDriver(["b"])
        got: list[ButtonEvent] = []
        driver.subscribe(got.append)
        await driver.press("b", "long")
        assert got == [ButtonEvent("b", "long")]

    async def test_async_handler_and_unsubscribe(self):
        driver = FakeButtonDriver(["b"])
        got = []

        async def handler(event):
            got.append(event.event)

        unsubscribe = driver.subscribe(handler)
        await driver.press("b")
        unsubscribe()
        unsubscribe()  # sans effet la seconde fois
        await driver.press("b", "double")
        assert got == ["short"]

    async def test_failing_subscriber_does_not_block_the_others(self):
        driver = FakeButtonDriver(["b"])
        got = []

        def broken(_):
            raise RuntimeError("boum")

        driver.subscribe(broken)
        driver.subscribe(got.append)
        await driver.press("b")
        assert len(got) == 1

    async def test_unknown_button(self):
        with pytest.raises(KeyError):
            await FakeButtonDriver(["b"]).press("x")


class TestHAClientHelpers:
    async def test_light_on_sends_only_given_parameters(self):
        ha = FakeHAClient()
        await ha.light_on("light.bandeau", rgb_color=(255, 0, 0), brightness=40, transition=2)
        await ha.light_on("light.bandeau")
        assert ha.calls == [
            (
                "light",
                "turn_on",
                {
                    "entity_id": "light.bandeau",
                    "rgb_color": [255, 0, 0],
                    "brightness": 40,
                    "transition": 2,
                },
            ),
            ("light", "turn_on", {"entity_id": "light.bandeau"}),
        ]

    async def test_zero_values_are_sent(self):
        ha = FakeHAClient()
        await ha.light_on("light.x", brightness=0, transition=0)
        assert ha.calls[0][2] == {"entity_id": "light.x", "brightness": 0, "transition": 0}

    async def test_light_off_and_switches(self):
        ha = FakeHAClient()
        await ha.light_off("light.x")
        await ha.switch_on("switch.prise")
        await ha.switch_off("switch.prise")
        assert [(d, s) for d, s, _ in ha.calls] == [
            ("light", "turn_off"),
            ("switch", "turn_on"),
            ("switch", "turn_off"),
        ]
        assert all(set(data) == {"entity_id"} for _, _, data in ha.calls)

    async def test_failure_injection_wraps_errors_in_ha_error(self):
        ha = FakeHAClient()
        ha.fail_with = ConnectionError("injoignable")
        with pytest.raises(HAError, match="injoignable"):
            await ha.light_off("light.x")
        assert ha.calls == []

    async def test_failure_can_target_one_entity(self):
        ha = FakeHAClient()
        ha.fail_entities["light.cassee"] = HAError("404")
        await ha.light_off("light.ok")
        with pytest.raises(HAError):
            await ha.light_off("light.cassee")
        assert len(ha.calls) == 1

    async def test_calls_are_recorded_in_the_timeline(self):
        rec = Recorder(now=lambda: 1.0)
        ha = FakeHAClient(rec)
        await ha.light_on("light.x", brightness=10)
        assert rec.entries[0].component == "light.x"
        assert rec.entries[0].action == "light.turn_on"
        assert rec.entries[0].data == {"brightness": 10}
