import io
import json
import threading
from pathlib import Path

import pytest
from gpiozero.pins.mock import MockFactory

from halloween import gpio_check
from halloween.cli import Backend, main
from halloween.drivers.dryrun import DryRunHAClient
from halloween.drivers.gpio import GpioButtonDriver, GpioRelayDriver
from halloween.store import Store

ROOT = Path(__file__).resolve().parents[2]


class Setup:
    def __init__(self, tmp_path, active_low=False, double_press_ms=100):
        self.factory = MockFactory()
        raw = json.loads((ROOT / "deploy" / "config.example.json").read_text(encoding="utf-8"))
        for relay in raw["relays"]:
            relay["active_low"] = active_low
        raw["buttons"][0]["double_press_ms"] = double_press_ms
        self.data = tmp_path / "data"
        store = Store(self.data)
        store.initialize()
        (self.data / "config.json").write_text(json.dumps(raw), encoding="utf-8")
        self.backend = Backend(
            lambda config: GpioRelayDriver(config.relays, self.factory),
            lambda config: GpioButtonDriver(config.buttons, self.factory),
            lambda _c, write: DryRunHAClient(write),
        )

    def check(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        code = main(["--data-dir", str(self.data), "gpio-check", *argv], self.backend, out)
        return code, out.getvalue()

    def press_later(self, delay=0.3, hold=0.05):
        pin = self.factory.pin(21)

        def press():
            pin.drive_low()
            threading.Timer(hold, pin.drive_high).start()

        timer = threading.Timer(delay, press)
        timer.start()
        return timer


@pytest.fixture(autouse=True)
def fast_settle(monkeypatch):
    monkeypatch.setattr(gpio_check, "SETTLE_S", 0.01)


def test_passive_check_describes_the_environment_and_commands_nothing(tmp_path):
    setup = Setup(tmp_path)
    code, out = setup.check()
    assert code == 0
    assert "Environnement" in out and "gpiozero" in out and "MockFactory" in out
    assert out.count("OK") == 4 and "au repos" in out
    assert "non testés" in out and "--active" in out
    assert "actif," not in out  # aucun basculement


def test_active_check_toggles_every_relay_and_waits_for_a_button_press(tmp_path):
    setup = Setup(tmp_path)
    timer = setup.press_later()
    try:
        code, out = setup.check("--active", "--press-timeout", "5")
    finally:
        timer.cancel()
    assert code == 0, out
    assert out.count("actif, niveau haut") == 4
    assert "appui short détecté" in out and "Aucun problème" in out


def test_active_low_relays_are_checked_with_the_inverted_level(tmp_path):
    setup = Setup(tmp_path, active_low=True)
    timer = setup.press_later()
    try:
        code, out = setup.check("--active", "--press-timeout", "5")
    finally:
        timer.cancel()
    assert code == 0, out
    assert "au repos, niveau haut" in out and "actif, niveau bas" in out


def test_missing_button_press_is_reported_as_a_failure(tmp_path):
    setup = Setup(tmp_path)
    code, out = setup.check("--active", "--press-timeout", "0.3")
    assert code == 1
    assert "ÉCHEC" in out and "aucun appui détecté" in out and "GND" in out


def test_relays_are_left_off_after_the_check(tmp_path):
    setup = Setup(tmp_path)
    setup.check("--active", "--press-timeout", "0.1")
    assert not any(setup.factory.pin(p).state for p in (18, 17, 27, 22))


def test_unexpected_rest_level_is_a_failure(tmp_path):
    setup = Setup(tmp_path)
    original = GpioRelayDriver.pin_level
    GpioRelayDriver.pin_level = lambda self, relay_id: True  # câblage inversé simulé
    try:
        code, out = setup.check()
    finally:
        GpioRelayDriver.pin_level = original
    assert code == 1 and "ÉCHEC" in out and "active_low" in out


def test_environment_without_gpio_gives_the_hardware_exit_code(tmp_path, capsys):
    setup = Setup(tmp_path)

    def broken(_config):
        raise OSError("pas de GPIO")

    setup.backend.relays = broken
    code, _ = setup.check()
    assert code == 3 and "matériel inutilisable" in capsys.readouterr().err


def test_pi_model_reads_the_device_tree(tmp_path, monkeypatch):
    model = tmp_path / "model"
    model.write_bytes(b"Raspberry Pi 5 Model B Rev 1.0\x00")
    monkeypatch.setattr(gpio_check, "MODEL_FILE", model)
    assert gpio_check.pi_model() == "Raspberry Pi 5 Model B Rev 1.0"
    monkeypatch.setattr(gpio_check, "MODEL_FILE", tmp_path / "absent")
    assert "inconnu" in gpio_check.pi_model()


def test_pi5_without_lgpio_warns(tmp_path, monkeypatch):
    model = tmp_path / "model"
    model.write_text("Raspberry Pi 5 Model B Rev 1.0")
    monkeypatch.setattr(gpio_check, "MODEL_FILE", model)
    code, out = Setup(tmp_path).check()
    assert "lgpio" in out and "ATTENTION" in out  # la fabrique fictive n'est pas LGPIOFactory
