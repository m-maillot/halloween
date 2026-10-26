import asyncio

from gpiozero.pins.mock import MockFactory

from halloween.config.models import Button
from halloween.drivers.base import ButtonEvent
from halloween.drivers.gpio import GpioButtonDriver
from halloween.program.virtual import run_virtual


def button(id_="bouton_principal", pin=21, **kw) -> Button:
    return Button.model_validate({"id": id_, "name": id_, "pin": pin, **kw})


def drive(factory: MockFactory, buttons: list[Button], script):
    """Joue un scénario d'appuis sur les broches simulées ; retourne les événements reçus."""
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


def test_pull_up_button_press_is_low():
    factory = MockFactory()
    received = drive(factory, [button()], [(0, 21, "low"), (0.1, 21, "high")])
    assert received == [(0.5, ButtonEvent("bouton_principal", "short"))]


def test_long_press():
    factory = MockFactory()
    received = drive(factory, [button()], [(0, 21, "low"), (2, 21, "high")])
    assert received == [(0.8, ButtonEvent("bouton_principal", "long"))]


def test_double_press():
    factory = MockFactory()
    script = [(0, 21, "low"), (0.1, 21, "high"), (0.3, 21, "low"), (0.4, 21, "high")]
    assert drive(factory, [button()], script) == [(0.3, ButtonEvent("bouton_principal", "double"))]


def test_pull_down_button_press_is_high():
    factory = MockFactory()
    received = drive(factory, [button(pull="down")], [(0, 21, "high"), (0.1, 21, "low")])
    assert received == [(0.5, ButtonEvent("bouton_principal", "short"))]


def test_thresholds_come_from_the_configuration():
    factory = MockFactory()
    custom = button(long_press_ms=300, double_press_ms=150)
    received = drive(factory, [custom], [(0, 21, "low"), (1, 21, "high")])
    assert received == [(0.3, ButtonEvent("bouton_principal", "long"))]


def test_two_buttons_are_independent():
    factory = MockFactory()
    buttons = [button("a", 21), button("b", 20)]
    script = [(0, 21, "low"), (0.1, 21, "high"), (1, 20, "low"), (3, 20, "high")]
    received = drive(factory, buttons, script)
    assert [(e.button_id, e.event) for _, e in received] == [("a", "short"), ("b", "long")]


def test_no_event_after_close_and_pins_are_released():
    factory = MockFactory()
    received: list[ButtonEvent] = []

    async def main():
        driver = GpioButtonDriver([button()], factory)
        driver.subscribe(received.append)
        await driver.start()
        await driver.close()
        # les broches sont libres : un nouveau pilote peut les reprendre, l'ancien ne réagit plus
        second = GpioButtonDriver([button()], factory)
        await second.start()
        factory.pin(21).drive_low()
        await asyncio.sleep(2)
        await second.close()

    run_virtual(main)
    assert received == []


def test_failure_while_starting_releases_the_pins_already_taken():
    factory = MockFactory()

    async def main():
        driver = GpioButtonDriver([button("a", 21), button("b", 21)], factory)
        try:
            await driver.start()
        except Exception:
            return "failed"
        return "started"

    assert run_virtual(main) == "failed"

    async def again():
        driver = GpioButtonDriver([button("a", 21)], factory)
        await driver.start()
        await driver.close()

    run_virtual(again)  # la broche 21 n'est pas restée occupée
