"""Contrat avec Home Assistant : ce que le moteur envoie réellement (faux serveur HTTP)."""

import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from halloween.config import AppConfig
from halloween.drivers import FakeButtonDriver, FakeRelayDriver
from halloween.drivers.homeassistant import HttpHAClient
from halloween.program import Program
from halloween.program.actions import DeviceActions
from halloween.program.models import LightNode, SwitchNode
from halloween.program.runs import RunManager
from halloween.testing.fake_ha import TOKEN, FakeHA

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def ha():
    server = FakeHA().start()
    yield server
    server.stop()


@pytest.fixture
async def stack(ha):
    config = AppConfig.model_validate(
        json.loads((ROOT / "deploy" / "config.example.json").read_text(encoding="utf-8"))
        | {"switches": [{"id": "prise", "name": "Prise", "entity_id": "switch.prise_salon"}]}
    )
    client = HttpHAClient(ha.url, TOKEN, timeout_s=2)
    yield config, client, ha
    await client.close()


def sent(ha: FakeHA) -> list[tuple[str, dict]]:
    return [(r.path.removeprefix("/api/services/"), r.body) for r in ha.posts()]


BANDEAU = "light.bandeau_hue"


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ({"state": "on"}, ("light/turn_on", {"entity_id": BANDEAU})),
        (
            {"state": "on", "rgb_color": [255, 0, 0]},
            ("light/turn_on", {"entity_id": BANDEAU, "rgb_color": [255, 0, 0]}),
        ),
        (
            {"state": "on", "brightness": 40},
            ("light/turn_on", {"entity_id": BANDEAU, "brightness": 40}),
        ),
        (
            {"state": "on", "transition": 2.5},
            ("light/turn_on", {"entity_id": BANDEAU, "transition": 2.5}),
        ),
        (
            {"state": "on", "brightness": 0, "transition": 0},
            ("light/turn_on", {"entity_id": BANDEAU, "brightness": 0, "transition": 0}),
        ),
        (
            {"state": "on", "rgb_color": [1, 2, 3], "brightness": 255, "transition": 1},
            (
                "light/turn_on",
                {"entity_id": BANDEAU, "rgb_color": [1, 2, 3], "brightness": 255, "transition": 1},
            ),
        ),
        # à l'extinction, couleur et luminosité sont ignorées
        (
            {"state": "off", "rgb_color": [1, 2, 3], "brightness": 9},
            ("light/turn_off", {"entity_id": BANDEAU}),
        ),
    ],
)
async def test_light_blocks_send_exactly_the_documented_bodies(stack, node, expected):
    config, client, ha = stack
    actions = DeviceActions(config, FakeRelayDriver.from_config(config), client)
    await actions.execute(LightNode(id="n", type="light", target="bandeau", **node))
    assert sent(ha) == [expected]
    assert ha.posts()[0].token == TOKEN


@pytest.mark.parametrize("state", ["on", "off"])
async def test_switch_blocks(stack, state):
    config, client, ha = stack
    actions = DeviceActions(config, FakeRelayDriver.from_config(config), client)
    await actions.execute(SwitchNode(id="n", type="switch", target="prise", state=state))
    assert sent(ha) == [(f"switch/turn_{state}", {"entity_id": "switch.prise_salon"})]


async def test_full_chain_sends_the_expected_sequence_including_rest_state(stack):
    config, client, ha = stack
    relays = FakeRelayDriver.from_config(config)
    program = Program.model_validate(
        {
            "id": "demo",
            "name": "demo",
            "scripts": [
                {
                    "id": "s",
                    "root": {
                        "id": "n",
                        "type": "sequence",
                        "children": [
                            {
                                "id": "a",
                                "type": "light",
                                "target": "bandeau",
                                "state": "on",
                                "rgb_color": [255, 0, 0],
                                "brightness": 40,
                                "transition": 2,
                            },
                            {"id": "b", "type": "relay", "target": "fantome", "state": "on"},
                            {"id": "w", "type": "wait", "seconds": 0.05},
                            {"id": "c", "type": "switch", "target": "prise", "state": "on"},
                            {"id": "d", "type": "light", "target": "guirlande", "state": "off"},
                        ],
                    },
                }
            ],
        }
    )
    manager = RunManager(
        config, relays, client, FakeButtonDriver(["bouton_principal"]), {"demo": program}
    )
    run = await manager.start(program)
    await run.done.wait()
    await manager.shutdown()
    assert run.outcome == "completed"
    assert sent(ha) == [
        (
            "light/turn_on",
            {"entity_id": BANDEAU, "rgb_color": [255, 0, 0], "brightness": 40, "transition": 2},
        ),
        ("switch/turn_on", {"entity_id": "switch.prise_salon"}),
        ("light/turn_off", {"entity_id": "light.twinkly_halloween"}),
        # fin de run (on_end = reset) : les lumières touchées reviennent à leur état de repos
        (
            "light/turn_on",
            {"entity_id": BANDEAU, "rgb_color": [255, 120, 0], "brightness": 60, "transition": 2},
        ),
        ("light/turn_on", {"entity_id": "light.twinkly_halloween", "brightness": 150}),
        # shutdown : état de repos complet (bandeau et guirlande)
        (
            "light/turn_on",
            {"entity_id": BANDEAU, "rgb_color": [255, 120, 0], "brightness": 60, "transition": 2},
        ),
        ("light/turn_on", {"entity_id": "light.twinkly_halloween", "brightness": 150}),
    ]
    assert {r.token for r in ha.requests} == {TOKEN}


async def test_startup_reset_applies_the_rest_state(stack):
    config, client, ha = stack
    manager = RunManager(
        config, FakeRelayDriver.from_config(config), client, FakeButtonDriver([]), {}
    )
    await manager.reset_all()
    assert [path for path, _ in sent(ha)] == ["light/turn_on", "light/turn_on"]
    await manager.shutdown()


# ------------------------------------------------------------------ le faux serveur lancé seul


def test_fake_server_can_run_standalone():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-m", "halloween.testing.fake_ha", "--port", str(port), "--token", "abc"],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/", headers={"Authorization": "Bearer abc"}
        )
        for _ in range(50):
            try:
                with urllib.request.urlopen(request, timeout=1) as response:
                    assert json.load(response)["message"] == "API running."
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("le faux serveur n'a pas démarré")
    finally:
        process.terminate()
        process.wait(timeout=5)
