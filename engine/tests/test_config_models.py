import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from halloween.config import AppConfig, Button, HomeAssistant, Light, Relay, RelayMode, Switch

EXAMPLE = Path(__file__).resolve().parents[2] / "deploy" / "config.example.json"


def relay(**overrides):
    return Relay.model_validate(
        {"id": "fantome", "name": "Fantôme", "pin": 18, "mode": "latched"} | overrides
    )


def test_example_config_is_valid_and_round_trips():
    raw = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    config = AppConfig.model_validate(raw)
    assert {r.id: r.pin for r in config.relays} == {
        "fantome": 18,
        "squelette": 17,
        "epouvantail": 27,
        "orage": 22,
    }
    assert AppConfig.model_validate(config.model_dump(mode="json")) == config


class TestRelay:
    def test_latched_defaults(self):
        r = relay()
        assert r.mode is RelayMode.LATCHED
        assert r.active_low is False
        assert r.max_on_seconds is None
        assert r.pulse_ms is None

    def test_push_gets_default_pulse(self):
        assert relay(mode="push").pulse_ms == 500

    def test_push_keeps_explicit_values(self):
        r = relay(mode="push", pulse_ms=200, animation_s=12.5)
        assert (r.pulse_ms, r.animation_s) == (200, 12.5)

    @pytest.mark.parametrize("extra", [{"pulse_ms": 500}, {"animation_s": 3}])
    def test_latched_rejects_push_fields(self, extra):
        with pytest.raises(ValidationError, match="mode push"):
            relay(**extra)

    def test_push_rejects_max_on_seconds(self):
        with pytest.raises(ValidationError, match="latched"):
            relay(mode="push", max_on_seconds=10)

    def test_latched_accepts_max_on_seconds(self):
        assert relay(max_on_seconds=60).max_on_seconds == 60

    @pytest.mark.parametrize("pin", [-1, 0, 1, 28, 40])
    def test_pin_out_of_range(self, pin):
        with pytest.raises(ValidationError):
            relay(pin=pin)

    @pytest.mark.parametrize("bad", [0, -5])
    def test_durations_must_be_positive(self, bad):
        with pytest.raises(ValidationError):
            relay(max_on_seconds=bad)
        with pytest.raises(ValidationError):
            relay(mode="push", pulse_ms=bad)

    def test_unknown_mode(self):
        with pytest.raises(ValidationError):
            relay(mode="toggle")


class TestCommonFields:
    @pytest.mark.parametrize("bad_id", ["", "Fantome", "a b", "é", "-x", "x" * 65])
    def test_invalid_ids(self, bad_id):
        with pytest.raises(ValidationError):
            relay(id=bad_id)

    @pytest.mark.parametrize("good_id", ["a", "fantome", "bouton_principal", "led-1", "9lives"])
    def test_valid_ids(self, good_id):
        assert relay(id=good_id).id == good_id

    def test_name_required_and_stripped(self):
        assert relay(name="  Fantôme ").name == "Fantôme"
        with pytest.raises(ValidationError):
            relay(name="   ")

    @pytest.mark.parametrize(
        "image",
        ["builtin:ghost", "builtin:led-strip", "fantome.png", "a_b-1.JPG".lower(), "x.webp"],
    )
    def test_valid_images(self, image):
        assert relay(image=image).image == image

    @pytest.mark.parametrize(
        "image",
        [
            "",
            "builtin:",
            "builtin:Ghost",
            "../x.png",
            "a/b.png",
            "x.gif",
            "x.svg",
            "http://x/y.png",
        ],
    )
    def test_invalid_images(self, image):
        with pytest.raises(ValidationError, match="image"):
            relay(image=image)

    def test_image_is_optional(self):
        assert relay().image is None

    def test_unknown_field_is_rejected(self):
        with pytest.raises(ValidationError, match="extra"):
            relay(pinn=3)


class TestButton:
    def test_defaults(self):
        b = Button(id="b", name="B", pin=21)
        assert (b.pull, b.debounce_ms, b.long_press_ms) == ("up", 50, 800)

    def test_invalid_pull(self):
        with pytest.raises(ValidationError):
            Button(id="b", name="B", pin=21, pull="none")


class TestLightsAndSwitches:
    def test_light_capabilities_default_to_off(self):
        light = Light(id="l", name="L", entity_id="light.bandeau_hue")
        assert not (light.supports_color or light.supports_brightness or light.supports_transition)

    @pytest.mark.parametrize(
        "entity", ["bandeau", "switch.prise", "light.", "light.Bandeau", "light.a b"]
    )
    def test_light_entity_must_be_a_light(self, entity):
        with pytest.raises(ValidationError):
            Light(id="l", name="L", entity_id=entity)

    def test_switch_entity_must_be_a_switch(self):
        assert (
            Switch(id="s", name="S", entity_id="switch.prise_salon").entity_id
            == "switch.prise_salon"
        )
        with pytest.raises(ValidationError):
            Switch(id="s", name="S", entity_id="light.x")


class TestHomeAssistant:
    def test_url_is_normalized(self):
        assert (
            HomeAssistant(url=" http://homeassistant.local:8123/ ").url
            == "http://homeassistant.local:8123"
        )

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "homeassistant.local",
            "ftp://x",
            "http://",
            "http:// x",
            "http://ha:abc",
            "http://ha:123456",
        ],
    )
    def test_invalid_url(self, url):
        with pytest.raises(ValidationError):
            HomeAssistant(url=url)

    def test_token_is_not_in_repr(self):
        ha = HomeAssistant(url="http://ha:8123", token="super-secret")
        assert "super-secret" not in repr(ha)
        assert ha.token == "super-secret"


def test_empty_config_is_valid():
    config = AppConfig()
    assert config.relays == [] and config.home_assistant is None
