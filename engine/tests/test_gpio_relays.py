import asyncio

import pytest
from gpiozero.pins.mock import MockFactory

from halloween.config.models import Relay
from halloween.drivers.gpio import GpioRelayDriver
from halloween.program.virtual import run_virtual


def relay(id_="fantome", pin=18, **kw) -> Relay:
    return Relay.model_validate({"id": id_, "name": id_, "pin": pin, "mode": "latched", **kw})


@pytest.fixture
def factory() -> MockFactory:
    return MockFactory()


def level(factory, pin) -> bool:
    """Niveau électrique de la broche (True = haut)."""
    return bool(factory.pin(pin).state)


async def test_active_high_relay_goes_high_when_on(factory):
    driver = GpioRelayDriver([relay()], factory)
    assert level(factory, 18) is False and not driver.is_on("fantome")  # repos dès la création
    await driver.set("fantome", True)
    assert level(factory, 18) is True and driver.is_on("fantome")
    await driver.set("fantome", False)
    assert level(factory, 18) is False and not driver.is_on("fantome")


async def test_active_low_module_is_driven_high_at_rest_and_low_when_on(factory):
    driver = GpioRelayDriver([relay(active_low=True)], factory)
    assert level(factory, 18) is True and not driver.is_on("fantome")  # haut = repos
    await driver.set("fantome", True)
    assert level(factory, 18) is False and driver.is_on(
        "fantome"
    )  # bas = actif, état logique « on »


async def test_all_outputs_start_at_rest_even_with_several_relays(factory):
    GpioRelayDriver([relay("a", 18), relay("b", 17, active_low=True), relay("c", 27)], factory)
    assert (level(factory, 18), level(factory, 17), level(factory, 27)) == (False, True, False)


async def test_all_off(factory):
    driver = GpioRelayDriver([relay("a", 18), relay("b", 17)], factory)
    await driver.set("a", True)
    await driver.set("b", True)
    await driver.all_off()
    assert not driver.is_on("a") and not driver.is_on("b")
    assert (level(factory, 18), level(factory, 17)) == (False, False)


async def test_unknown_relay(factory):
    driver = GpioRelayDriver([relay()], factory)
    with pytest.raises(KeyError, match="inconnu"):
        await driver.set("nope", True)
    with pytest.raises(KeyError):
        driver.is_on("nope")


async def test_close_turns_everything_off_and_releases_pins(factory):
    driver = GpioRelayDriver([relay("a", 18)], factory)
    await driver.set("a", True)
    await driver.close()
    assert level(factory, 18) is False
    # les broches sont libres : un autre pilote peut les reprendre
    GpioRelayDriver([relay("a", 18)], factory)


def test_failure_while_creating_releases_the_pins_already_taken(factory):
    with pytest.raises(Exception):  # noqa: B017 - la même broche demandée deux fois
        GpioRelayDriver([relay("a", 18), relay("b", 18)], factory)
    GpioRelayDriver([relay("a", 18)], factory)  # la broche 18 n'est pas restée occupée


def test_max_on_seconds_cuts_the_relay_by_itself(factory):
    async def main():
        driver = GpioRelayDriver([relay(max_on_seconds=5)], factory)
        await driver.set("fantome", True)
        await asyncio.sleep(4)
        assert driver.is_on("fantome")
        await asyncio.sleep(2)
        assert not driver.is_on("fantome")

    run_virtual(main)


def test_turning_off_cancels_the_watchdog_and_turning_on_again_restarts_it(factory):
    async def main():
        driver = GpioRelayDriver([relay(max_on_seconds=5)], factory)
        await driver.set("fantome", True)
        await asyncio.sleep(3)
        await driver.set("fantome", False)
        await driver.set("fantome", True)  # nouveau délai de 5 s à partir de maintenant
        await asyncio.sleep(4)
        assert driver.is_on("fantome")
        await asyncio.sleep(2)
        assert not driver.is_on("fantome")

    run_virtual(main)


def test_no_limit_means_the_relay_stays_on(factory):
    async def main():
        driver = GpioRelayDriver([relay()], factory)
        await driver.set("fantome", True)
        await asyncio.sleep(86_400)
        assert driver.is_on("fantome")

    run_virtual(main)


async def test_works_as_the_relay_driver_of_the_run_manager(factory):
    """Branché sur les actions du moteur : un bloc `relay` pilote bien la broche."""
    from halloween.config import AppConfig
    from halloween.drivers import FakeHAClient
    from halloween.program.actions import DeviceActions
    from halloween.program.models import RelayNode

    config = AppConfig(relays=[relay()])
    driver = GpioRelayDriver(config.relays, factory)
    actions = DeviceActions(config, driver, FakeHAClient())
    await actions.execute(RelayNode(id="n", type="relay", target="fantome", state="on"))
    assert level(factory, 18) is True
