"""Recette du jalon A : un test de bout en bout, par l'API, pour les critères de la spec 1 §11.

Matériel simulé (broches fictives, Home Assistant fictif) : ces tests prouvent la logique, pas le
câblage. La correspondance critère → tests détaillés est dans `docs/recette-jalon-a.md`.
Le critère 9 (suite sans matériel) est démontré par l'exécution même de cette suite, le 10
(verrouillage) est couvert par `test_api_lock.py`.
"""

from __future__ import annotations

import time

import pytest

from api_helpers import Pi, engine_of
from halloween.drivers import HAUnreachable


def eventually(check, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.01)
    return False


def program(id_, *scripts, **kw):
    return {
        "schema": 1,
        "id": id_,
        "name": id_,
        "scripts": [
            {"id": sid, "root": {"id": f"{sid}-n", "type": "sequence", "children": list(nodes)}}
            for sid, nodes in scripts
        ],
        **kw,
    }


def relay(id_, target, state="on"):
    return {"id": id_, "type": "relay", "target": target, "state": state}


def wait(id_, seconds):
    return {"id": id_, "type": "wait", "seconds": seconds}


def save(client, prog):
    response = client.put(f"/api/programs/{prog['id']}", json=prog)
    assert response.status_code in (200, 201), response.text


def run(client, program_id):
    response = client.post("/api/runs", json={"program_id": program_id})
    assert response.status_code == 201, response.text
    return response.json()["run_id"]


def active(client):
    return sorted(r["program_id"] for r in client.get("/api/runs").json())


@pytest.fixture
def pi(tmp_path):
    return Pi(tmp_path)


@pytest.fixture
def client(pi):
    with pi.client() as c:
        yield c


# 1 ------------------------------------------------------------------------------------------


def test_c1_the_installation_is_built_from_the_api_and_every_object_is_testable(tmp_path):
    pi = Pi(tmp_path, {"relays": [], "buttons": [], "lights": [], "rest_state": {}})
    wiring = (("Fantôme", 18), ("Squelette", 17), ("Épouvantail", 27), ("Orage", 22))
    with pi.client() as client:
        ids = []
        for name, pin in wiring:
            created = client.post(
                "/api/components/relays",
                json={"name": name, "pin": pin, "mode": "latched", "image": "builtin:ghost"},
            )
            assert created.status_code == 201, created.text
            ids.append(created.json()["component"]["id"])
        button = client.post(
            "/api/components/buttons",
            json={"name": "Bouton d'entrée", "pin": 21, "image": "builtin:button"},
        )
        assert button.status_code == 201, button.text
        devices = client.get("/api/devices").json()
        assert [(r["name"], r["pin"], r["image"]) for r in devices["relays"]] == [
            (name, pin, "builtin:ghost") for name, pin in wiring
        ]
        assert devices["buttons"][0]["pin"] == 21 and devices["buttons"][0]["name"]
        for relay_id in ids:
            on = client.post(f"/api/components/relays/{relay_id}/test", json={"action": "on"})
            assert on.status_code == 200 and pi.relays.is_on(relay_id)
            client.post(f"/api/components/relays/{relay_id}/test", json={"action": "off"})
            assert not pi.relays.is_on(relay_id)
        button_id = button.json()["component"]["id"]
        press = client.post(f"/api/components/buttons/{button_id}/test", json={"action": "press"})
        assert press.status_code == 200


# 2 ------------------------------------------------------------------------------------------


def test_c2_latched_stays_closed_until_off_and_push_pulses_once_per_animation(tmp_path):
    pi = Pi(tmp_path)
    with pi.client() as client:
        client.post(
            "/api/components/relays",
            json={"name": "Robot", "pin": 5, "mode": "push", "pulse_ms": 80, "animation_s": 0.4},
        )
        client.post("/api/components/relays/fantome/test", json={"action": "on"})
        time.sleep(0.3)
        assert pi.relays.is_on("fantome")  # maintenu : rien ne l'éteint
        client.post("/api/components/relays/fantome/test", json={"action": "off"})
        assert not pi.relays.is_on("fantome")

        trigger = {"id": "t", "type": "relay", "target": "robot", "action": "trigger"}
        steps = [trigger, wait("w1", 0.1), {**trigger, "id": "t2"}, wait("w2", 0.5)]
        save(client, program("anim", ("s", [*steps, {**trigger, "id": "t3"}])))
        run(client, "anim")
        assert eventually(lambda: active(client) == [])
        pulses = [c for _, c, a in pi.relays.recorder.timeline() if c == "robot" and a == "on"]
        # 3 déclenchements, dont le deuxième (0,1 s, pendant l'animation de 0,4 s) est ignoré.
        assert len(pulses) == 2


# 3 ------------------------------------------------------------------------------------------


def test_c3_home_assistant_receives_only_the_authorised_parameters(client, pi):
    client.post("/api/components/switches", json={"name": "Prise", "entity_id": "switch.prise"})
    full = {
        "id": "l1",
        "type": "light",
        "target": "bandeau",
        "state": "on",
        "rgb_color": [255, 0, 0],
        "brightness": 40,
        "transition": 2,
    }
    switch = {"id": "s1", "type": "switch", "target": "prise", "state": "on"}
    save(client, program("ha", ("s", [full, switch])))
    already = len(pi.ha.calls)  # appels de remise au repos du démarrage
    run(client, "ha")
    assert eventually(lambda: len(pi.ha.calls) >= already + 2)
    sent = pi.ha.calls[already:]
    assert sent[0] == (
        "light",
        "turn_on",
        {
            "entity_id": "light.bandeau_hue",
            "rgb_color": [255, 0, 0],
            "brightness": 40,
            "transition": 2,
        },
    )
    assert sent[1] == ("switch", "turn_on", {"entity_id": "switch.prise"})

    # Une lumière qui ne gère pas la couleur : le programme est refusé, rien n'est envoyé.
    forbidden = {**full, "target": "guirlande"}
    response = client.put("/api/programs/nope", json=program("nope", ("s", [forbidden])))
    issues = response.json()["detail"]["issues"]
    assert response.status_code == 422
    assert {(i["code"], i["node_id"]) for i in issues} == {("unsupported_parameter", "l1")}
    assert any("couleur" in i["message"] for i in issues)
    assert client.get("/api/programs/nope").status_code == 404


# 4 ------------------------------------------------------------------------------------------


def test_c4_parallel_drives_a_relay_and_a_light_at_the_same_time(client, pi):
    light = {"id": "l", "type": "light", "target": "bandeau", "state": "on", "brightness": 50}
    branches = {
        "id": "p",
        "type": "parallel",
        "children": [
            {"id": "a", "type": "sequence", "children": [relay("r", "fantome"), wait("wa", 30)]},
            {"id": "b", "type": "sequence", "children": [light, wait("wb", 30)]},
        ],
    }
    save(client, program("duo", ("s", [branches])))
    run(client, "duo")
    # Les deux effets sont présents alors que le programme est encore en cours.
    assert eventually(lambda: pi.relays.is_on("fantome") and len(pi.ha.calls) >= 1)
    assert active(client) == ["duo"]
    client.post("/api/runs/stop")


# 5 ------------------------------------------------------------------------------------------


def test_c5_short_press_starts_the_scenario_long_press_stops_it_within_a_second(client, pi):
    save(client, program("scene", ("s", [relay("a", "fantome"), wait("w", 60)])))
    triggers = [
        {"id": "go", "source": "button", "button": "bouton_principal", "event": "short",
         "program": "scene"},
        {"id": "halt", "source": "button", "button": "bouton_principal", "event": "long",
         "action": "stop"},
    ]  # fmt: skip
    assert client.put("/api/triggers", json=triggers).status_code == 200

    def press(kind):
        url = "/api/components/buttons/bouton_principal/test"
        client.post(url, json={"action": "press", "event": kind})

    press("short")
    assert eventually(lambda: active(client) == ["scene"] and pi.relays.is_on("fantome"))
    started = time.monotonic()
    press("long")
    assert eventually(lambda: active(client) == [] and not pi.relays.is_on("fantome"), 1.0)
    assert time.monotonic() - started < 1.0
    # État de repos des lumières appliqué (bandeau et guirlande reviennent à leur repos).
    assert pi.ha.calls[-1][0] == "light"


# 6 ------------------------------------------------------------------------------------------


def test_c6_home_assistant_cut_during_a_run_leaves_relays_fine_and_traces_the_error(client, pi):
    light = {"id": "l", "type": "light", "target": "bandeau", "state": "on"}
    save(client, program("scene", ("s", [relay("a", "fantome"), wait("w", 0.2), light])))
    pi.ha.fail_with = HAUnreachable("Home Assistant injoignable : connexion refusée")
    run(client, "scene")
    assert eventually(lambda: pi.relays.is_on("fantome"))  # le relais fonctionne malgré la panne
    assert eventually(lambda: active(client) == [])  # le run se termine (pas de blocage)
    problems = client.get("/api/status").json()["recent_problems"]
    assert any(p["message"] == "action en échec" for p in problems)  # erreur tracée


# 7 ------------------------------------------------------------------------------------------


def test_c7_after_a_pi_restart_relays_are_off_and_config_and_triggers_are_reloaded(tmp_path):
    pi = Pi(tmp_path)
    with pi.client() as client:
        client.post("/api/components/relays", json={"name": "Fumée", "pin": 5, "mode": "latched"})
        save(client, program("scene", ("s", [relay("a", "fantome"), wait("w", 60)])))
        trigger = {"id": "go", "source": "button", "button": "bouton_principal",
                   "event": "short", "program": "scene"}  # fmt: skip
        client.put("/api/triggers", json=[trigger])
        client.post("/api/components/relays/fumee/test", json={"action": "on"})
        assert pi.relays.is_on("fumee")
    # Redémarrage brutal : on repart des fichiers, avec des relais restés « collés » allumés.
    with pi.client() as client:
        assert engine_of(client).relays is pi.relays
        assert not any(client.get("/api/status").json()["relays"].values())
        assert [r["id"] for r in client.get("/api/devices").json()["relays"]][-1] == "fumee"
        assert [t["id"] for t in client.get("/api/triggers").json()["triggers"]] == ["go"]
        assert client.get("/api/status").json()["triggers"] == 1


# 8 ------------------------------------------------------------------------------------------


def test_c8_invalid_programs_and_configs_are_rejected_with_a_located_error(client, pi):
    bad = program("bad", ("s", [relay("a", "fantome"), {**wait("w", 1), "seconds": -5}]))
    response = client.put("/api/programs/bad", json=bad)
    assert response.status_code == 422
    assert [i["node_id"] for i in response.json()["detail"]["issues"]] == ["w"]
    assert client.get("/api/programs/bad").status_code == 404

    unknown = program("bad2", ("s", [relay("a", "inconnu")]))
    issues = client.put("/api/programs/bad2", json=unknown).json()["detail"]["issues"]
    assert (issues[0]["code"], issues[0]["node_id"]) == ("unknown_component", "a")

    config = client.post(
        "/api/components/relays", json={"name": "Doublon", "pin": 18, "mode": "latched"}
    )
    assert config.status_code == 422
    assert config.json()["detail"]["issues"][0]["code"] == "duplicate_pin"
    field = client.post("/api/components/relays", json={"name": "X", "pin": 99, "mode": "latched"})
    assert any(e["loc"][-1] == "pin" for e in field.json()["detail"])


# 11 -----------------------------------------------------------------------------------------


def test_c11_show_programs_are_listed_in_order_and_builtin_images_are_kept(client):
    save(client, program("zeta", ("s", [wait("w", 1)]), show=True, show_order=2))
    save(client, program("alpha", ("s", [wait("w", 1)]), show=True, show_order=1))
    save(client, program("cache", ("s", [wait("w", 1)])))
    listed = client.get("/api/programs").json()
    shown = sorted((p for p in listed if p["show"]), key=lambda p: p["show_order"])
    assert [p["id"] for p in shown] == ["alpha", "zeta"]
    assert [p["show_order"] for p in shown] == [1, 2]
    assert not next(p for p in listed if p["id"] == "cache")["show"]
    created = client.post(
        "/api/components/switches",
        json={"name": "Prise", "entity_id": "switch.p", "image": "builtin:ghost"},
    )
    assert created.status_code == 201
    assert created.json()["component"]["image"] == "builtin:ghost"  # restitué tel quel
    assert client.get("/api/components/relays/fantome").json()["image"] == "builtin:ghost"


# 12 -----------------------------------------------------------------------------------------


def test_c12_parallelism_ambiance_scenario_and_stops(client, pi):
    # Deux blocs début dans un même programme : les deux scripts tournent ensemble.
    two = program("deux", ("s1", [relay("a", "fantome"), wait("wa", 60)]),
                  ("s2", [relay("b", "squelette"), wait("wb", 60)]))  # fmt: skip
    save(client, two)
    run(client, "deux")
    assert eventually(lambda: pi.relays.is_on("fantome") and pi.relays.is_on("squelette"))
    client.post("/api/runs/stop")
    assert eventually(lambda: active(client) == [])

    # Ambiance : boucle infinie, sans max_duration_s ; scénario déclenché pendant ce temps.
    ambiance = program(
        "ambiance",
        ("s", [{"id": "loop", "type": "repeat", "forever": True,
                "child": {"id": "body", "type": "sequence",
                          "children": [relay("on", "fantome"), wait("pause", 0.05)]}}]),
    )  # fmt: skip
    scene = program("scene", ("s", [relay("a", "orage"), wait("w", 60)]))
    save(client, ambiance)
    save(client, scene)
    run(client, "ambiance")
    scene_id = run(client, "scene")
    assert eventually(lambda: active(client) == ["ambiance", "scene"] and pi.relays.is_on("orage"))

    # Arrêter le scénario seul : son relais revient au repos, l'ambiance continue et garde le sien.
    assert client.post(f"/api/runs/{scene_id}/stop").status_code == 200
    assert eventually(lambda: not pi.relays.is_on("orage") and active(client) == ["ambiance"])
    time.sleep(0.15)
    assert pi.relays.is_on("fantome") and active(client) == ["ambiance"]

    # STOP global : tout s'arrête en moins d'une seconde.
    run(client, "scene")
    started = time.monotonic()
    assert client.post("/api/runs/stop").json()["stopped"] == 2
    assert eventually(lambda: active(client) == [] and not pi.relays.is_on("fantome"), 1.0)
    assert time.monotonic() - started < 1.0
