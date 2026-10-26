"""Garde-fous sur la configuration d'exemple (`deploy/config.example.json`).

Le fichier est validé par les modèles dans `test_config_models.py` ; ces tests vérifient en plus
les valeurs de l'installation réelle.
"""

import json
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[2] / "deploy" / "config.example.json"


@pytest.fixture(scope="module")
def config() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_relays_match_the_real_wiring(config):
    pins = {r["id"]: r["pin"] for r in config["relays"]}
    assert pins == {"fantome": 18, "squelette": 17, "epouvantail": 27, "orage": 22}


def test_relays_are_latched_active_high_without_time_limit(config):
    for relay in config["relays"]:
        assert relay["mode"] == "latched"
        assert relay["active_low"] is False  # `high()` active le relais
        assert "max_on_seconds" not in relay  # pas de limite d'allumage


def test_button_is_on_pin_21_with_pull_up(config):
    (button,) = config["buttons"]
    assert (button["id"], button["pin"], button["pull"]) == ("bouton_principal", 21, "up")


def test_ids_and_pins_are_unique(config):
    ids = [c["id"] for kind in ("relays", "buttons", "lights", "switches") for c in config[kind]]
    assert len(ids) == len(set(ids))
    pins = [c["pin"] for kind in ("relays", "buttons") for c in config[kind]]
    assert len(pins) == len(set(pins))


def test_lights_declare_their_capabilities(config):
    for light in config["lights"]:
        assert light["entity_id"].startswith("light.")
        for capability in ("supports_color", "supports_brightness", "supports_transition"):
            assert isinstance(light[capability], bool)


def test_example_contains_no_secret(config):
    assert config["home_assistant"]["token"] == ""


def test_example_program_is_valid_against_the_example_config():
    from halloween.config import AppConfig
    from halloween.config.validation import validate_config
    from halloween.issues import errors
    from halloween.program import Program
    from halloween.program.validation import validate_program

    config = AppConfig.model_validate(json.loads(EXAMPLE.read_text(encoding="utf-8")))
    program_file = EXAMPLE.parent / "programs-example" / "scenario-principal.json"
    program = Program.model_validate(json.loads(program_file.read_text(encoding="utf-8")))
    assert program.id == program_file.stem
    assert errors(validate_config(config)) == []
    assert errors(validate_program(program, config)) == []
