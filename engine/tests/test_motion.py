"""Détecteur de mouvement PIR : un bouton de type `motion` dont l'événement est `motion`."""

import asyncio

import pytest
from gpiozero.pins.mock import MockFactory
from pydantic import ValidationError

from halloween.config import AppConfig, Button
from halloween.drivers import FakeHAClient, FakeRelayDriver
from halloween.drivers.base import ButtonEvent
from halloween.drivers.gpio import GpioButtonDriver
from halloween.program import Program
from halloween.program.runs import RunManager
from halloween.program.validation import validate_program
from halloween.program.virtual import run_virtual
from halloween.triggers import TriggerEngine, parse_triggers, validate_triggers


def sensor(**kw) -> Button:
    return Button.model_validate({"id": "pir", "name": "PIR", "pin": 26, "kind": "motion", **kw})


def drive(factory: MockFactory, buttons: list[Button], script):
    """Joue des niveaux sur les broches simulées ; retourne (temps, événement) reçus."""
    received: list[tuple[float, ButtonEvent]] = []

    async def main():
        loop = asyncio.get_running_loop()
        driver = GpioButtonDriver(buttons, factory)
        driver.subscribe(lambda event: received.append((round(loop.time(), 3), event)))
        await driver.start()
        for t, pin, level in script:
            await asyncio.sleep(max(0.0, t - loop.time()))
            getattr(factory.pin(pin), f"drive_{level}")()
        await asyncio.sleep(5)
        await driver.close()

    run_virtual(main)
    return received


# ----------------------------------------------------------------------------- configuration


def test_a_motion_sensor_pulls_down_by_default_and_a_button_still_pulls_up():
    assert sensor().pull == "down" and sensor().warmup_s == 60
    assert Button(id="b", name="B", pin=21).pull == "up"
    assert Button(id="b", name="B", pin=21).kind == "button"


def test_an_explicit_pull_is_kept():
    assert sensor(pull="up").pull == "up"


def test_warmup_is_bounded():
    with pytest.raises(ValidationError):
        sensor(warmup_s=601)


# ----------------------------------------------------------------------------- pilote GPIO


def test_a_detection_emits_one_motion_event_on_the_rising_edge_only():
    factory = MockFactory()
    script = [(0, 26, "high"), (3, 26, "low")]  # le niveau haut dure tant que le PIR détecte
    received = drive(factory, [sensor(warmup_s=0)], script)
    assert received == [(0.0, ButtonEvent("pir", "motion"))]


def test_detections_during_warmup_are_ignored():
    factory = MockFactory()
    script = [(10, 26, "high"), (11, 26, "low"), (70, 26, "high"), (71, 26, "low")]
    received = drive(factory, [sensor(warmup_s=60)], script)
    assert received == [(70.0, ButtonEvent("pir", "motion"))]


def test_a_sensor_and_a_button_work_side_by_side():
    factory = MockFactory()
    button = Button(id="bouton", name="Bouton", pin=21)
    script = [(0, 21, "low"), (0.1, 21, "high"), (1, 26, "high")]
    received = drive(factory, [button, sensor(warmup_s=0)], script)
    assert [e for _, e in received] == [
        ButtonEvent("bouton", "short"),
        ButtonEvent("pir", "motion"),
    ]


# ----------------------------------------------------------------------------- validation


def config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "relays": [{"id": "fantome", "name": "Fantôme", "pin": 18, "mode": "latched"}],
            "buttons": [
                {"id": "bouton", "name": "Bouton", "pin": 21},
                {"id": "pir", "name": "PIR", "pin": 26, "kind": "motion"},
            ],
        }
    )


def trigger(button: str, event: str) -> dict:
    return {"id": f"t-{button}-{event}", "source": "button", "button": button, "event": event,
            "program": "demo"}  # fmt: skip


@pytest.mark.parametrize(
    ("button", "event", "valid"),
    [("pir", "motion", True), ("pir", "short", False), ("bouton", "motion", False)],
)
def test_a_trigger_must_use_an_event_its_input_can_produce(button, event, valid):
    triggers, _ = parse_triggers([trigger(button, event)])
    issues = validate_triggers(triggers, config(), {"demo"})
    assert [i.code for i in issues] == ([] if valid else ["button_event"])


def program(button: str, event: str) -> Program:
    condition = {"type": "button", "id": button, "event": event}
    root = {
        "id": "r",
        "type": "sequence",
        "children": [{"id": "w", "type": "wait_until", "condition": condition}],
    }
    return Program.model_validate(
        {"id": "demo", "name": "demo", "scripts": [{"id": "s", "root": root}]}
    )


def test_a_scenario_condition_is_checked_the_same_way():
    assert validate_program(program("pir", "motion"), config()) == []
    codes = [i.code for i in validate_program(program("pir", "double"), config())]
    assert codes == ["button_event"]
    codes = [i.code for i in validate_program(program("bouton", "motion"), config())]
    assert codes == ["button_event"]


# ----------------------------------------------------------------------------- de bout en bout


def test_a_detection_starts_the_scenario_it_is_wired_to():
    factory = MockFactory()
    cfg = config()
    triggers, _ = parse_triggers([trigger("pir", "motion")])

    async def main():
        buttons = GpioButtonDriver([sensor(warmup_s=0)], factory)
        relays = FakeRelayDriver.from_config(cfg)
        root = {
            "id": "r",
            "type": "sequence",
            "children": [
                {"id": "a", "type": "relay", "target": "fantome", "state": "on"},
                {"id": "w", "type": "wait", "seconds": 60},
            ],
        }
        programs = {
            "demo": Program.model_validate(
                {"id": "demo", "name": "demo", "scripts": [{"id": "s", "root": root}]}
            )
        }
        manager = RunManager(cfg, relays, FakeHAClient(), buttons, programs)
        engine = TriggerEngine(manager, buttons, programs, triggers)
        await buttons.start()
        await engine.start()
        factory.pin(26).drive_high()
        await asyncio.sleep(0.1)
        started = [r.program.id for r in manager.active]
        await engine.stop()
        await manager.shutdown()
        await buttons.close()
        return started

    assert run_virtual(main) == ["demo"]
