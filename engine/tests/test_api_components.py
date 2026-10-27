import json
import logging

import pytest

from api_helpers import AUTH, Pi, call, engine_of, start_run
from halloween.drivers import HAError
from halloween.testing.fake_ha import SAMPLE_STATES, TOKEN, FakeHA


def relay(id_, target, state="on"):
    return {"id": id_, "type": "relay", "target": target, "state": state}


def wait(id_, seconds):
    return {"id": id_, "type": "wait", "seconds": seconds}


@pytest.fixture
def pi(tmp_path) -> Pi:
    return Pi(tmp_path)


@pytest.fixture
def client(pi):
    with pi.client() as c:
        yield c


def saved_config(pi) -> dict:
    return json.loads(pi.store.config_path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ lecture


def test_list_and_get_components(client):
    relays = client.get("/api/components/relays").json()
    assert [r["id"] for r in relays] == ["fantome", "squelette", "epouvantail", "orage"]
    assert relays[0]["pin"] == 18 and relays[0]["image"] == "builtin:ghost"
    assert relays[0]["image_url"] is None  # icône intégrée : résolue par l'interface
    assert client.get("/api/components/relays/orage").json()["pin"] == 22
    assert client.get("/api/components/buttons/bouton_principal").json()["pin"] == 21
    assert client.get("/api/components/lights").json()[0]["supports_color"] is True


def test_unknown_component_is_a_404_with_a_readable_message(client):
    response = client.get("/api/components/relays/nope")
    assert response.status_code == 404 and "inconnu" in response.json()["detail"]["message"]


def test_devices_catalogue(client):
    body = client.get("/api/devices").json()
    assert [k for k in body] == ["relays", "buttons", "lights", "switches", "rest_state"]
    assert len(body["relays"]) == 4 and len(body["lights"]) == 2
    assert body["lights"][0]["supports_transition"] is True
    assert body["rest_state"]["bandeau"]["state"] == "on"


# ------------------------------------------------------------------ création


def test_create_light_generates_an_id_and_persists(client, pi):
    response = client.post(
        "/api/components/lights",
        json={
            "name": "Lampe du Salon é",
            "entity_id": "light.lampe_salon",
            "supports_brightness": True,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["component"]["id"] == "lampe-du-salon-e" and body["issues"] == []
    assert saved_config(pi)["lights"][-1]["entity_id"] == "light.lampe_salon"
    assert any(c["id"] == "lampe-du-salon-e" for c in client.get("/api/devices").json()["lights"])


def test_create_with_a_taken_name_gets_a_unique_id(client):
    first = client.post("/api/components/switches", json={"name": "Prise", "entity_id": "switch.a"})
    second = client.post(
        "/api/components/switches", json={"name": "Prise", "entity_id": "switch.b"}
    )
    assert (first.json()["component"]["id"], second.json()["component"]["id"]) == (
        "prise",
        "prise-2",
    )


def test_create_relay_hardware_is_rebuilt_and_ready(client, pi):
    old_driver = pi.relays
    response = client.post(
        "/api/components/relays", json={"name": "Fumée", "pin": 5, "mode": "latched"}
    )
    assert response.status_code == 201
    assert pi.relays is not old_driver and "fumee" in client.get("/api/status").json()["relays"]


def test_create_conflicts_are_rejected_with_localised_issues(client, pi):
    response = client.post(
        "/api/components/relays", json={"name": "Doublon", "pin": 18, "mode": "latched"}
    )
    assert response.status_code == 422
    issues = response.json()["detail"]["issues"]
    assert {i["code"] for i in issues} == {"duplicate_pin"} and "GPIO 18" in issues[0]["message"]
    assert len(saved_config(pi)["relays"]) == 4  # rien d'enregistré


def test_create_with_an_id_used_by_another_kind_is_a_409(client):
    response = client.post(
        "/api/components/lights", json={"id": "fantome", "name": "X", "entity_id": "light.x"}
    )
    assert response.status_code == 409 and "déjà utilisé" in response.json()["detail"]["message"]


def test_invalid_body_gives_field_level_errors(client):
    response = client.post(
        "/api/components/relays", json={"name": "X", "pin": 99, "mode": "latched"}
    )
    assert response.status_code == 422
    assert any(error["loc"][-1] == "pin" for error in response.json()["detail"])


# ------------------------------------------------------------------ modification


def test_cosmetic_update_does_not_interrupt_running_scenarios(client, pi):
    pi.program("long", relay("a", "fantome"), wait("w", 600), on_end="keep")
    pi.store.load_programs()
    call(
        client, engine_of(client).apply_config, engine_of(client).config
    )  # recharge les programmes
    run = start_run(client, "long")
    old_driver = pi.relays
    response = client.put(
        "/api/components/relays/fantome",
        json={"name": "Fantôme du grenier", "pin": 18, "mode": "latched", "image": "builtin:skull"},
    )
    assert response.status_code == 200
    assert run.state == "running" and pi.relays is old_driver  # ni arrêt, ni reconstruction
    assert saved_config(pi)["relays"][0]["name"] == "Fantôme du grenier"


def test_structural_update_needs_confirmation_when_scenarios_run(client, pi):
    pi.program("long", relay("a", "fantome"), wait("w", 600), on_end="keep")
    call(client, engine_of(client).apply_config, engine_of(client).config)
    run = start_run(client, "long")
    body = {"name": "Fantôme", "pin": 23, "mode": "latched"}
    refused = client.put("/api/components/relays/fantome", json=body)
    assert refused.status_code == 409 and "long" in refused.json()["detail"]["message"]
    assert run.state == "running" and saved_config(pi)["relays"][0]["pin"] == 18
    accepted = client.put("/api/components/relays/fantome?stop_runs=true", json=body)
    assert accepted.status_code == 200
    assert run.state == "ended" and run.outcome == "stopped"
    assert saved_config(pi)["relays"][0]["pin"] == 23


def test_update_cannot_change_the_id_and_unknown_is_a_404(client):
    body = {"id": "autre", "name": "X", "pin": 18, "mode": "latched"}
    assert client.put("/api/components/relays/fantome", json=body).status_code == 422
    assert client.put("/api/components/relays/nope", json={**body, "id": None}).status_code == 404


def test_mode_change_reports_the_programs_it_breaks(client, pi):
    pi.program("scene", relay("a", "fantome"), wait("w", 1))
    call(client, engine_of(client).apply_config, engine_of(client).config)
    assert "scene" in engine_of(client).programs
    response = client.put(
        "/api/components/relays/fantome", json={"name": "Fantôme", "pin": 18, "mode": "push"}
    )
    assert response.status_code == 200
    messages = " ".join(i["message"] for i in response.json()["issues"])
    assert "scene" in messages and "impulsion" in messages
    assert "scene" not in engine_of(client).programs  # écarté tant qu'il est incompatible


def test_unknown_uploaded_image_is_refused(client):
    body = {"name": "Fantôme", "pin": 18, "mode": "latched", "image": "inconnue.webp"}
    response = client.put("/api/components/relays/fantome", json=body)
    assert (
        response.status_code == 422 and "image introuvable" in response.json()["detail"]["message"]
    )


# ------------------------------------------------------------------ suppression


def test_delete_unused_component(client, pi):
    client.post("/api/components/switches", json={"name": "Prise", "entity_id": "switch.p"})
    assert client.delete("/api/components/switches/prise").status_code == 204
    assert client.get("/api/components/switches").json() == []
    assert saved_config(pi)["switches"] == []


def test_delete_is_refused_while_a_program_uses_the_component(client, pi):
    pi.program("scene", relay("a", "fantome"), wait("w", 1))
    call(client, engine_of(client).apply_config, engine_of(client).config)
    response = client.delete("/api/components/relays/fantome")
    assert response.status_code == 409
    message = response.json()["detail"]["message"]
    assert "programme" in message and "scene" in message and "bloc a" in message
    assert len(saved_config(pi)["relays"]) == 4


def test_delete_is_refused_while_a_trigger_uses_the_button(client, pi):
    pi.store.save_triggers(
        [
            {
                "id": "t1",
                "source": "button",
                "button": "bouton_principal",
                "event": "long",
                "action": "stop",
            }
        ]
    )
    call(client, engine_of(client).apply_config, engine_of(client).config)
    response = client.delete("/api/components/buttons/bouton_principal")
    assert (
        response.status_code == 409 and "déclencheur `t1`" in response.json()["detail"]["message"]
    )


def test_delete_is_refused_for_a_light_with_a_rest_state(client):
    response = client.delete("/api/components/lights/bandeau")
    assert response.status_code == 409 and "état de repos" in response.json()["detail"]["message"]


# ------------------------------------------------------------------ test manuel


def test_manual_relay_test(client, pi):
    assert (
        client.post("/api/components/relays/fantome/test", json={"action": "on"}).status_code == 200
    )
    assert pi.relays.is_on("fantome")
    client.post("/api/components/relays/fantome/test", json={"action": "off"})
    assert not pi.relays.is_on("fantome")


def test_manual_relay_mode_mismatches_are_explained(client):
    on = client.post("/api/components/relays/fantome/test", json={"action": "trigger"})
    assert on.status_code == 422 and "on / off" in on.json()["detail"]["message"]
    bad = client.post("/api/components/relays/fantome/test", json={"action": "press"})
    assert bad.status_code == 422


def test_manual_push_relay_pulse(client, pi):
    client.post(
        "/api/components/relays", json={"name": "Robot", "pin": 5, "mode": "push", "pulse_ms": 100}
    )
    response = client.post("/api/components/relays/robot/test", json={"action": "trigger"})
    assert response.status_code == 200 and not pi.relays.is_on("robot")  # impulsion terminée
    refused = client.post("/api/components/relays/robot/test", json={"action": "on"})
    assert refused.status_code == 422


def test_manual_light_test_sends_the_documented_body(client, pi):
    response = client.post(
        "/api/components/lights/bandeau/test",
        json={"action": "on", "rgb_color": [255, 0, 0], "brightness": 40, "transition": 2},
    )
    assert response.status_code == 200
    assert pi.ha.calls[-1] == (
        "light",
        "turn_on",
        {
            "entity_id": "light.bandeau_hue",
            "rgb_color": [255, 0, 0],
            "brightness": 40,
            "transition": 2,
        },
    )
    client.post("/api/components/lights/bandeau/test", json={"action": "off"})
    assert pi.ha.calls[-1][1] == "turn_off"


def test_manual_light_test_refuses_unsupported_parameters(client):
    response = client.post(
        "/api/components/lights/guirlande/test", json={"action": "on", "rgb_color": [1, 2, 3]}
    )
    assert response.status_code == 422 and "couleur" in response.json()["detail"]["message"]


def test_manual_switch_test(client, pi):
    client.post("/api/components/switches", json={"name": "Prise", "entity_id": "switch.p"})
    assert (
        client.post("/api/components/switches/prise/test", json={"action": "on"}).status_code == 200
    )
    assert pi.ha.calls[-1] == ("switch", "turn_on", {"entity_id": "switch.p"})


def test_manual_test_reports_a_device_failure_as_502(client, pi):
    pi.ha.fail_with = HAError("Home Assistant injoignable")
    response = client.post("/api/components/lights/bandeau/test", json={"action": "on"})
    assert response.status_code == 502 and "injoignable" in response.json()["detail"]["message"]


def test_manual_button_press_reaches_the_subscribers(client, pi):
    received = []
    pi.buttons.subscribe(received.append)
    response = client.post(
        "/api/components/buttons/bouton_principal/test", json={"action": "press", "event": "long"}
    )
    assert response.status_code == 200
    assert [(e.button_id, e.event) for e in received] == [("bouton_principal", "long")]


def test_manual_test_of_an_unknown_component(client):
    response = client.post("/api/components/relays/nope/test", json={"action": "on"})
    assert response.status_code == 404


# ------------------------------------------------------------------ Home Assistant


@pytest.fixture
def fake_ha():
    server = FakeHA(states=[dict(s) for s in SAMPLE_STATES]).start()
    yield server
    server.stop()


def test_ha_config_has_no_token_at_first_and_never_returns_it_afterwards(client, pi, caplog):
    assert client.get("/api/config/home-assistant").json() == {
        "configured": True,
        "url": "http://homeassistant.local:8123",
        "timeout_s": 5.0,
        "token_set": False,
        "token_source": "none",
    }
    with caplog.at_level(logging.DEBUG):
        response = client.put(
            "/api/config/home-assistant",
            json={"url": "http://ha.local:8123/", "token": "super-secret-token", "timeout_s": 3},
        )
    assert response.status_code == 200
    assert "super-secret-token" not in response.text
    assert "super-secret-token" not in client.get("/api/config/home-assistant").text
    body = client.get("/api/config/home-assistant").json()
    assert (
        body["url"] == "http://ha.local:8123"
        and body["token_set"]
        and body["token_source"] == "config"
    )
    assert saved_config(pi)["home_assistant"]["token"] == "super-secret-token"  # stocké côté Pi
    assert "super-secret-token" not in caplog.text


def test_ha_token_can_be_kept_or_cleared(client, pi):
    client.put("/api/config/home-assistant", json={"url": "http://ha:8123", "token": "abc"})
    client.put(
        "/api/config/home-assistant", json={"url": "http://ha:9999"}
    )  # jeton absent : conservé
    assert saved_config(pi)["home_assistant"] == {
        "url": "http://ha:9999",
        "token": "abc",
        "timeout_s": 5.0,
    }
    client.put("/api/config/home-assistant", json={"url": "http://ha:9999", "token": ""})
    assert saved_config(pi)["home_assistant"]["token"] == ""
    assert client.get("/api/config/home-assistant").json()["token_set"] is False


def test_ha_token_from_the_environment_is_reported(client, monkeypatch):
    client.put("/api/config/home-assistant", json={"url": "http://ha:8123", "token": "abc"})
    monkeypatch.setenv("HALLOWEEN_HA_TOKEN", "depuis-l-env")
    body = client.get("/api/config/home-assistant").json()
    assert body["token_source"] == "env" and body["token_set"] is True


def test_ha_config_rejects_a_bad_url(client):
    response = client.put("/api/config/home-assistant", json={"url": "pas une url"})
    assert response.status_code == 422 and "URL invalide" in response.json()["detail"]["message"]


def test_ha_connection_test_success_and_failures(client, fake_ha):
    ok = client.post(
        "/api/config/home-assistant/test", json={"url": fake_ha.url, "token": TOKEN}
    ).json()
    assert ok["ok"] is True and ok["message"] == "API running." and ok["latency_ms"] >= 0
    refused = client.post(
        "/api/config/home-assistant/test", json={"url": fake_ha.url, "token": "faux"}
    ).json()
    assert (
        refused["ok"] is False
        and refused["error_type"] == "HAAuthError"
        and "jeton refusé" in refused["message"]
    )
    down = client.post(
        "/api/config/home-assistant/test", json={"url": "http://127.0.0.1:1", "token": "x"}
    ).json()
    assert down["ok"] is False and down["error_type"] == "HAUnreachable"
    nothing = client.post("/api/config/home-assistant/test", json={}).json()
    assert nothing["ok"] is False and "aucun jeton" in nothing["message"]


def test_ha_connection_test_uses_the_saved_settings_by_default(client, fake_ha):
    client.put("/api/config/home-assistant", json={"url": fake_ha.url, "token": TOKEN})
    assert client.post("/api/config/home-assistant/test", json={}).json()["ok"] is True


def test_ha_entities_with_inferred_capabilities(client, fake_ha):
    client.put("/api/config/home-assistant", json={"url": fake_ha.url, "token": TOKEN})
    lights = client.get("/api/ha/entities?domain=light").json()
    assert [e["entity_id"] for e in lights] == ["light.bandeau_hue", "light.twinkly_halloween"]
    assert lights[0]["capabilities"] == {"color": True, "brightness": True, "transition": True}
    assert lights[1]["capabilities"] == {"color": True, "brightness": True, "transition": False}
    everything = client.get("/api/ha/entities").json()
    assert {e["domain"] for e in everything} == {"light", "switch"}
    assert everything[-1]["capabilities"] is None  # un interrupteur n'a pas de capacités de lumière


def test_ha_entities_errors(client, fake_ha):
    assert client.get("/api/ha/entities").status_code == 409  # pas configuré
    client.put("/api/config/home-assistant", json={"url": "http://127.0.0.1:1", "token": "x"})
    response = client.get("/api/ha/entities")
    assert response.status_code == 502 and "injoignable" in response.json()["detail"]["message"]


# ------------------------------------------------------------------ authentification et attente


def test_component_routes_need_the_token(pi):
    from fastapi.testclient import TestClient

    with TestClient(pi.app()) as anonymous:
        for method, path in (
            ("get", "/api/components/relays"),
            ("get", "/api/devices"),
            ("get", "/api/config/home-assistant"),
            ("get", "/api/ha/entities"),
        ):
            assert getattr(anonymous, method)(path).status_code == 401
        assert (
            anonymous.post("/api/components/relays/fantome/test", json={"action": "on"}).status_code
            == 401
        )
        assert (
            anonymous.post(
                "/api/images", content=b"x", headers={"Content-Type": "image/png"}
            ).status_code
            == 401
        )
    assert AUTH["Authorization"].startswith("Bearer")
