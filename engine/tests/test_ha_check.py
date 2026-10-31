import copy
import io
import json
from pathlib import Path

import pytest

from halloween.cli import Backend, gpio_backend, main
from halloween.config import AppConfig
from halloween.drivers import FakeButtonDriver, FakeRelayDriver
from halloween.drivers.homeassistant import HttpHAClient
from halloween.ha_check import Capabilities, infer_capabilities, run_ha_check
from halloween.program import Program
from halloween.store import Store
from halloween.testing.fake_ha import SAMPLE_STATES, TOKEN, FakeHA

ROOT = Path(__file__).resolve().parents[2]

HUE = {"supported_color_modes": ["color_temp", "xy"], "supported_features": 40}
TWINKLY = {"supported_color_modes": ["rgb"], "supported_features": 4}


# ------------------------------------------------------------------ capacités


@pytest.mark.parametrize(
    ("attributes", "expected"),
    [
        (HUE, Capabilities(color=True, brightness=True, transition=True)),
        (TWINKLY, Capabilities(color=True, brightness=True, transition=False)),
        ({"supported_color_modes": ["onoff"]}, Capabilities(False, False, False)),
        ({"supported_color_modes": ["brightness"]}, Capabilities(False, True, False)),
        ({"supported_color_modes": ["color_temp"]}, Capabilities(False, True, False)),
        (
            {"supported_color_modes": ["rgbww"], "supported_features": 32},
            Capabilities(True, True, True),
        ),
        ({"supported_color_modes": ["hs", "color_temp"]}, Capabilities(True, True, False)),
        ({}, Capabilities(False, False, False)),
        (
            {"supported_color_modes": None, "supported_features": None},
            Capabilities(False, False, False),
        ),
        ({"supported_features": 32 | 4 | 8}, Capabilities(False, False, True)),
    ],
)
def test_infer_capabilities(attributes, expected):
    assert infer_capabilities(attributes) == expected


# ------------------------------------------------------------------ vérification


def make_config(**light_overrides) -> AppConfig:
    raw = json.loads((ROOT / "deploy" / "config.example.json").read_text(encoding="utf-8"))
    raw["switches"] = [{"id": "prise", "name": "Prise", "entity_id": "switch.prise_salon"}]
    for light in raw["lights"]:
        light.update(light_overrides.get(light["id"], {}))
    return AppConfig.model_validate(raw)


@pytest.fixture
def ha():
    server = FakeHA(states=copy.deepcopy(SAMPLE_STATES)).start()
    yield server
    server.stop()


async def check(ha, config=None, active=False, token=TOKEN, url=None):
    config = config or make_config()
    client = HttpHAClient(url or ha.url, token, timeout_s=2)
    out = io.StringIO()
    try:
        code = await run_ha_check(config, client, out, active=active, pause_s=0)
    finally:
        await client.close()
    return code, out.getvalue()


async def test_passive_check_lists_entities_and_compares_capabilities(ha):
    code, out = await check(ha)
    assert code == 0
    assert "connexion" in out and "API running." in out
    assert (
        "light.bandeau_hue" in out and "[config : bandeau]" in out and "switch.prise_salon" in out
    )
    assert "bandeau : transition (config : oui, Home Assistant : oui)" in out
    # Twinkly gère la couleur (rgb) mais la config d'exemple ne l'utilise pas : simple avertissement
    assert "ATTENTION" in out and "guirlande : couleur (config : non, Home Assistant : oui)" in out
    assert "Test actif non lancé" in out
    assert [r.method for r in ha.requests] == ["GET", "GET"]  # lecture seule


async def test_config_claiming_an_unsupported_capability_fails(ha):
    config = make_config(guirlande={"supports_transition": True})
    code, out = await check(ha, config)
    assert code == 1
    assert "ÉCHEC" in out and "guirlande : transition (config : oui, Home Assistant : non)" in out


async def test_unknown_entity_suggests_close_matches(ha):
    config = make_config(bandeau={"entity_id": "light.bandeau_hu"})
    code, out = await check(ha, config)
    assert code == 1
    assert "`light.bandeau_hu` introuvable" in out and "light.bandeau_hue" in out


async def test_wrong_token_gives_an_actionable_hint(ha):
    code, out = await check(ha, token="mauvais")
    assert code == 1 and "jeton refusé" in out and "jeton longue durée" in out
    assert "mauvais" not in out


async def test_unreachable_home_assistant_gives_a_hint():
    code, out = await check(None, url="http://127.0.0.1:1")
    assert code == 1 and "injoignable" in out and "Vérifier l'URL" in out


async def test_active_check_exercises_every_supported_parameter_then_restores(ha):
    config = make_config(bandeau={"supports_color": True})
    code, out = await check(ha, config, active=True)
    assert code == 0, out
    bodies = [(r.path.removeprefix("/api/services/"), r.body) for r in ha.posts()]
    bandeau = "light.bandeau_hue"
    assert bodies[:5] == [
        ("light/turn_on", {"entity_id": bandeau}),
        ("light/turn_on", {"entity_id": bandeau, "brightness": 128}),
        ("light/turn_on", {"entity_id": bandeau, "rgb_color": [255, 0, 0]}),
        ("light/turn_on", {"entity_id": bandeau, "rgb_color": [0, 255, 0]}),
        ("light/turn_on", {"entity_id": bandeau, "transition": 2, "rgb_color": [0, 0, 255]}),
    ]
    assert ("light/turn_off", {"entity_id": bandeau}) in bodies  # était éteint : restauré éteint
    assert "Latence des appels : moyenne" in out and "ms" in out


async def test_active_check_only_uses_capabilities_the_config_declares(ha):
    config = make_config(bandeau={"supports_color": False, "supports_transition": False})
    await check(ha, config, active=True)
    bandeau_bodies = [r.body for r in ha.posts() if r.body["entity_id"] == "light.bandeau_hue"]
    assert all("rgb_color" not in b and "transition" not in b for b in bandeau_bodies)


async def test_active_check_restores_a_light_that_was_on(ha):
    ha.states[0] = {
        **ha.states[0],
        "state": "on",
        "attributes": {**ha.states[0]["attributes"], "brightness": 200, "rgb_color": [10, 20, 30]},
    }
    await check(ha, make_config(), active=True)
    last = [r for r in ha.posts() if r.body["entity_id"] == "light.bandeau_hue"][-1]
    assert last.path.endswith("light/turn_on")
    assert last.body == {
        "entity_id": "light.bandeau_hue",
        "rgb_color": [10, 20, 30],
        "brightness": 200,
    }


async def test_active_check_reports_a_refused_parameter_and_still_restores(ha):
    ha.overrides[("POST", "/api/services/light/turn_on")] = (400, {"message": "bad"})
    code, out = await check(ha, make_config(), active=True)
    assert code == 1 and "refusé" in out
    assert any(r.path.endswith("light/turn_off") for r in ha.posts())


async def test_active_check_toggles_switches_and_restores_them(ha):
    await check(ha, make_config(), active=True)
    switch_calls = [r.path.removeprefix("/api/services/") for r in ha.posts() if "switch" in r.path]
    assert switch_calls == ["switch/turn_on", "switch/turn_off"]  # était éteint : restauré éteint


# ------------------------------------------------------------------ via la CLI


class Cli:
    def __init__(self, tmp_path, ha_settings):
        raw = json.loads((ROOT / "deploy" / "config.example.json").read_text(encoding="utf-8"))
        raw["home_assistant"] = ha_settings
        self.data = tmp_path / "data"
        self.store = Store(self.data)
        self.store.initialize()
        self.store.save_config(AppConfig.model_validate(raw))
        self.config = self.store.load_config()
        self.relays = None
        self.backend = Backend(
            lambda config: self._relays(config),
            lambda config: FakeButtonDriver(b.id for b in config.buttons),
            gpio_backend().ha,
        )

    def _relays(self, config):
        self.relays = FakeRelayDriver.from_config(config)
        return self.relays

    def run(self, *argv):
        out = io.StringIO()
        code = main(["--data-dir", str(self.data), *argv], self.backend, out)
        return code, out.getvalue()


def test_cli_ha_check_without_a_home_assistant_section(tmp_path, capsys):
    cli = Cli(tmp_path, None)
    code, _ = cli.run("ha-check")
    assert code == 2 and "home_assistant" in capsys.readouterr().err


def test_cli_ha_check_without_a_token(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("HALLOWEEN_HA_TOKEN", raising=False)
    cli = Cli(tmp_path, {"url": "http://127.0.0.1:1"})
    code, _ = cli.run("ha-check")
    assert code == 2 and "aucun jeton" in capsys.readouterr().err


def test_cli_ha_check_uses_the_token_from_the_environment(tmp_path, ha, monkeypatch):
    monkeypatch.setenv("HALLOWEEN_HA_TOKEN", TOKEN)
    cli = Cli(tmp_path, {"url": ha.url})
    code, out = cli.run("ha-check")
    assert code == 0 and "API running." in out


def program_json():
    return Program.model_validate(
        {
            "id": "demo",
            "name": "demo",
            "on_end": "keep",
            "scripts": [
                {
                    "id": "s",
                    "root": {
                        "id": "n",
                        "type": "light",
                        "target": "bandeau",
                        "state": "on",
                        "brightness": 40,
                    },
                }
            ],
        }
    )


def test_cli_run_sends_real_calls_when_home_assistant_is_configured(tmp_path, ha):
    cli = Cli(tmp_path, {"url": ha.url, "token": TOKEN})
    cli.store.save_program(program_json())
    code, out = cli.run("run", "demo")
    assert code == 0 and "appels réels" in out and "simulé" not in out
    assert {"brightness": 40, "entity_id": "light.bandeau_hue"} in [r.body for r in ha.posts()]


def test_cli_run_ha_dry_run_sends_nothing(tmp_path, ha):
    cli = Cli(tmp_path, {"url": ha.url, "token": TOKEN})
    cli.store.save_program(program_json())
    code, out = cli.run("run", "demo", "--ha-dry-run")
    assert code == 0 and "[Home Assistant simulé]" in out
    assert ha.requests == []


def test_cli_run_without_token_falls_back_to_simulation(tmp_path, monkeypatch):
    monkeypatch.delenv("HALLOWEEN_HA_TOKEN", raising=False)
    cli = Cli(tmp_path, {"url": "http://127.0.0.1:1"})
    cli.store.save_program(program_json())
    code, out = cli.run("run", "demo")
    assert code == 0 and "aucun jeton" in out and "[Home Assistant simulé]" in out


def with_player(script: str) -> AppConfig:
    raw = make_config().model_dump()
    video = {"id": "noir", "name": "Noir", "source": "black_screen.mp4"}
    raw["players"] = [{"id": "retro", "name": "Rétro", "script": script, "videos": [video]}]
    return AppConfig.model_validate(raw)


async def test_the_script_of_a_player_is_checked(ha):
    code, out = await check(ha, with_player("script.lire_video_shield"))
    assert code == 0 and "retro : script `script.lire_video_shield` existe" in out
    code, out = await check(ha, with_player("script.lire_video_shiel"))
    assert code == 1 and "`script.lire_video_shiel` introuvable" in out
    assert "script.lire_video_shield" in out  # proposé parmi les noms proches
