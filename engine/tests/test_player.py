"""Lecteur de vidéos (Shield + Kodi) : composant `player`, bloc `player`, repos, API."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from api_helpers import Pi
from halloween.config import AppConfig
from halloween.config.models import LOCAL_MEDIA, Player
from halloween.drivers import FakeButtonDriver, FakeHAClient, FakeRelayDriver, Recorder
from halloween.events import ComponentChangedEvent
from halloween.program import Program
from halloween.program.runs import RunManager
from halloween.program.simulation import simulate
from halloween.program.validation import validate_program
from halloween.program.virtual import run_virtual

ROOT = Path(__file__).resolve().parents[2]

SCRIPT = "script.lire_video_shield"
PLAYER = {
    "id": "retro",
    "name": "Rétroprojecteur",
    "script": SCRIPT,
    "videos": [
        {"id": "noir", "name": "Écran noir", "source": "black_screen.mp4", "duration_s": 10},
        {"id": "fete", "name": "Fête", "source": "halloween_video.mp4", "duration_s": 21},
        {"id": "ghost", "name": "Fantôme", "source": "media-source://media_source/local/g.mkv"},
    ],
    "rest_video": "noir",
}


def config(**player) -> AppConfig:
    raw = json.loads((ROOT / "deploy" / "config.example.json").read_text(encoding="utf-8"))
    raw["players"] = [{**PLAYER, **player}]
    return AppConfig.model_validate(raw)


def node(**kw) -> dict:
    return {"id": "p1", "type": "player", "target": "retro", "action": "play"} | kw


def seq(*children: dict) -> dict:
    return {"id": "n", "type": "sequence", "children": list(children)}


def program(root: dict, **kw) -> Program:
    return Program.model_validate(
        {"id": "p", "name": "P", "scripts": [{"id": "s", "root": root}], **kw}
    )


def played(ha: FakeHAClient) -> list[tuple]:
    """Appels du script du lecteur (la config d'exemple a aussi des lumières au repos)."""
    return [c for c in ha.calls if c[0] == "script"]


def call(file: str, loop: bool) -> tuple:
    return ("script", "lire_video_shield", {"video": LOCAL_MEDIA + file, "boucle": loop})


# ----------------------------------------------------------------------------- configuration


def test_a_bare_file_name_designates_the_local_media_folder():
    player = Player.model_validate(PLAYER)
    assert player.video("fete").media == "media-source://media_source/local/halloween_video.mp4"
    assert player.video("ghost").media == "media-source://media_source/local/g.mkv"  # inchangé
    other = {**PLAYER["videos"][1], "source": "http://nas/film.mp4"}
    assert (
        Player.model_validate({**PLAYER, "videos": [other], "rest_video": None}).videos[0].media
        == "http://nas/film.mp4"
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"rest_video": "inconnue"},
        {"videos": []},
        {"script": "light.bandeau"},
        {"videos": [PLAYER["videos"][0], PLAYER["videos"][0]]},
    ],
)
def test_an_inconsistent_player_is_refused(patch):
    with pytest.raises(ValidationError):
        Player.model_validate({**PLAYER, **patch})


def test_a_player_id_cannot_be_shared_with_another_component():
    from halloween.config.validation import validate_config

    raw = config().model_dump()
    raw["players"][0]["id"] = "fantome"  # id d'un relais
    issues = validate_config(AppConfig.model_validate(raw))
    assert [i.code for i in issues] == ["duplicate_id"]


# ----------------------------------------------------------------------------- bloc


@pytest.mark.parametrize(
    "bad",
    [
        node(video=None),  # play sans vidéo
        node(video="fete", loop=True, wait_for_end=True),
        node(video="fete", wait_for_end=True, fire_and_forget=True),
        node(action="rest", video="fete"),
        node(action="rest", loop=True),
    ],
)
def test_a_player_block_must_be_coherent(bad):
    with pytest.raises(ValidationError):
        program(bad)


def codes(root: dict, cfg: AppConfig | None = None) -> list[str]:
    return [i.code for i in validate_program(program(root), cfg or config())]


def test_validation_against_the_configuration():
    assert codes(node(video="fete", wait_for_end=True)) == []
    assert codes(node(action="rest")) == []
    assert codes(node(target="nope", video="fete")) == ["unknown_component"]
    assert codes(node(target="fantome", video="fete")) == ["unknown_component"]
    assert codes(node(video="nope")) == ["unknown_video"]
    assert codes(node(video="ghost", wait_for_end=True)) == ["wait_for_end"]  # pas de durée
    assert codes(node(action="rest"), config(rest_video=None)) == ["no_rest_video"]


# ----------------------------------------------------------------------------- exécution


class Env:
    def __init__(self, cfg: AppConfig | None = None):
        loop = asyncio.get_running_loop()
        self.loop = loop
        self.rec = Recorder(now=loop.time)
        self.config = cfg or config()
        self.ha = FakeHAClient(self.rec)
        self.manager = RunManager(
            self.config,
            FakeRelayDriver.from_config(self.config, self.rec),
            self.ha,
            FakeButtonDriver([]),
            {},
        )

    async def run(self, root: dict, **kw):
        run = await self.manager.start(program(root, **kw))
        await run.done.wait()
        return run


def scenario(test):
    def wrapper():
        async def main():
            env = Env(getattr(wrapper, "cfg", None))
            try:
                await test(env)
            finally:
                await env.manager.shutdown()

        run_virtual(main)

    wrapper.__name__ = test.__name__
    return wrapper


@scenario
async def test_play_calls_the_script_with_the_video_and_the_loop_flag(env):
    await env.run(seq(node(video="fete"), node(id="p2", video="ghost", loop=True)), on_end="keep")
    assert env.ha.calls == [call("halloween_video.mp4", False), call("g.mkv", True)]


@scenario
async def test_rest_plays_the_rest_video_in_a_loop(env):
    await env.run(node(action="rest"), on_end="keep")
    assert env.ha.calls == [call("black_screen.mp4", True)]


@scenario
async def test_wait_for_end_waits_the_duration_of_the_video(env):
    t0 = env.loop.time()
    await env.run(seq(node(video="fete", wait_for_end=True), node(id="p2", action="rest")))
    # La vidéo dure 21 s : le retour à l'écran noir est demandé juste après.
    assert [e.t - t0 for e in env.rec.entries if e.data["video"].endswith("black_screen.mp4")] == [
        21.0,
        21.0,  # le bloc, puis la remise au repos de fin de scénario
    ]


@scenario
async def test_the_end_of_a_scenario_puts_the_player_back_on_the_black_screen(env):
    await env.run(node(video="fete"))
    assert env.ha.calls == [call("halloween_video.mp4", False), call("black_screen.mp4", True)]


@scenario
async def test_startup_and_global_stop_show_the_black_screen_without_any_scenario(env):
    assert "retro" not in await env.manager.reset_all()
    assert played(env.ha) == [call("black_screen.mp4", True)]


def without_rest_video() -> AppConfig:
    return config(rest_video=None)


@scenario
async def test_a_player_without_rest_video_is_left_alone(env):
    await env.run(node(video="fete"))
    await env.manager.reset_all()
    assert played(env.ha) == [call("halloween_video.mp4", False)]


test_a_player_without_rest_video_is_left_alone.cfg = without_rest_video()  # type: ignore[attr-defined]


@scenario
async def test_an_unreachable_home_assistant_does_not_stop_the_scenario(env):
    env.ha.fail_with = RuntimeError("HA hors ligne")
    run = await env.run(seq(node(video="fete"), node(id="p2", video="ghost")))
    assert run.outcome == "completed"
    assert "retro" in await env.manager.reset_all()  # à refaire quand HA répond


@scenario
async def test_on_error_abort_stops_the_scenario(env):
    env.ha.fail_with = RuntimeError("HA hors ligne")
    run = await env.run(seq(node(video="fete", on_error="abort"), node(id="p2", video="ghost")))
    assert run.outcome == "failed"


def test_simulation_shows_a_video_as_on_and_the_black_screen_as_off():
    result = simulate(
        program(seq(node(video="fete", wait_for_end=True), node(id="b", video="noir"))), config()
    )
    assert [(e.t, e.component, e.action, e.data) for e in result.timeline] == [
        (0.0, "retro", "on", {"video": "fete", "loop": False}),
        (21.0, "retro", "off", {"video": "noir", "loop": False}),
    ]


# ----------------------------------------------------------------------------- API


@pytest.fixture
def pi(tmp_path) -> Pi:
    return Pi(tmp_path, {"players": [PLAYER]})


@pytest.fixture
def client(pi):
    with pi.client() as c:
        yield c


def test_the_catalogue_lists_the_player(client):
    (player,) = client.get("/api/devices").json()["players"]
    assert player["id"] == "retro" and player["rest_video"] == "noir"
    assert [v["id"] for v in player["videos"]] == ["noir", "fete", "ghost"]


def test_create_update_and_delete_a_player(client):
    body = {**PLAYER, "id": None, "name": "Écran du salon"}
    created = client.post("/api/components/players", json=body)
    assert created.status_code == 201, created.text
    assert created.json()["component"]["id"] == "ecran-du-salon"
    bad = client.post("/api/components/players", json={**body, "rest_video": "x"})
    assert bad.status_code == 422
    assert client.delete("/api/components/players/ecran-du-salon").status_code == 204


def test_a_player_used_by_a_scenario_cannot_be_deleted(client, pi):
    pi.program("demo", node(video="fete"))
    response = client.delete("/api/components/players/retro")
    assert response.status_code == 409 and "demo" in response.json()["detail"]["message"]


def test_renaming_a_video_does_not_rebuild_the_engine(client):
    renamed = json.loads(json.dumps(PLAYER))
    renamed["videos"][1]["name"] = "Autre nom"
    response = client.put("/api/components/players/retro", json=renamed)
    assert response.status_code == 200, response.text


def test_manual_test_plays_a_video_then_the_black_screen(client, pi):
    url = "/api/components/players/retro/test"
    assert played(pi.ha) == [call("black_screen.mp4", True)]  # écran noir dès le démarrage
    pi.ha.calls.clear()
    assert (
        client.post(url, json={"action": "play", "video": "fete", "loop": True}).status_code == 200
    )
    assert client.post(url, json={"action": "rest"}).status_code == 200
    assert played(pi.ha) == [call("halloween_video.mp4", True), call("black_screen.mp4", True)]


def test_manual_test_refuses_a_missing_or_unknown_video(client):
    url = "/api/components/players/retro/test"
    assert client.post(url, json={"action": "play"}).status_code == 422
    assert client.post(url, json={"action": "play", "video": "nope"}).status_code == 422
    assert client.post(url, json={"action": "on"}).status_code == 422


def test_home_assistant_refusal_is_a_502(client, pi):
    from halloween.drivers import HAError

    pi.ha.fail_with = HAError("script refusé")
    response = client.post(
        "/api/components/players/retro/test", json={"action": "play", "video": "fete"}
    )
    assert response.status_code == 502


def test_a_script_call_publishes_the_player_state(client, pi):
    engine = client.app.state.engine
    published: list[ComponentChangedEvent] = []
    engine.hub.publish = published.append  # type: ignore[method-assign]
    engine._on_ha_change(
        "script",
        "lire_video_shield",
        {"video": LOCAL_MEDIA + "halloween_video.mp4", "boucle": False},
    )
    engine._on_ha_change(
        "script", "lire_video_shield", {"video": LOCAL_MEDIA + "black_screen.mp4", "boucle": True}
    )
    assert [(e.component_id, e.state, e.details["video"]) for e in published] == [
        ("retro", "on", "fete"),
        ("retro", "off", "noir"),
    ]
