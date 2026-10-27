import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api_helpers import AUTH, TOKEN, Pi, engine_of
from halloween.drivers import HAError


def relay(id_, target, state="on"):
    return {"id": id_, "type": "relay", "target": target, "state": state}


def wait(id_, seconds):
    return {"id": id_, "type": "wait", "seconds": seconds}


def program(id_, *children, **kw) -> dict:
    root = {"id": "n", "type": "sequence", "children": list(children)}
    return {"schema": 1, "id": id_, "name": id_, "scripts": [{"id": "s", "root": root}], **kw}


@pytest.fixture
def pi(tmp_path) -> Pi:
    return Pi(tmp_path)


@pytest.fixture
def client(pi):
    with pi.client() as c:
        yield c


def connect(client, token: str | None = TOKEN):
    suffix = f"?token={token}" if token else ""
    return client.websocket_connect(f"/api/events{suffix}", headers={})


def receive_until(ws, predicate, limit=200):
    """Reçoit des événements jusqu'à ce que `predicate` soit vrai ; retourne tous ceux reçus."""
    seen = []
    for _ in range(limit):
        event = ws.receive_json()
        seen.append(event)
        if predicate(event):
            return seen
    raise AssertionError(f"événement attendu non reçu : {[e['type'] for e in seen]}")


def types(events):
    return [e["type"] for e in events]


def save(client, prog):
    assert client.put(f"/api/programs/{prog['id']}", json=prog).status_code in (200, 201)


# ------------------------------------------------------------------ authentification


def test_websocket_requires_the_token(pi):
    with TestClient(pi.app()) as anonymous:
        for url, headers in (
            ("/api/events", {}),
            ("/api/events?token=mauvais", {}),
            ("/api/events", {"Authorization": "Bearer mauvais"}),
        ):
            with pytest.raises(WebSocketDisconnect):
                with anonymous.websocket_connect(url, headers=headers) as ws:
                    ws.receive_json()


def test_websocket_accepts_the_token_in_the_query_or_the_header(client):
    with client.websocket_connect(f"/api/events?token={TOKEN}") as ws:
        assert ws.receive_json()["type"] == "snapshot"
    with client.websocket_connect("/api/events", headers=AUTH) as ws:
        assert ws.receive_json()["type"] == "snapshot"


# ------------------------------------------------------------------ instantané


def test_first_message_is_a_snapshot_of_the_current_state(client, pi):
    save(client, program("scene", relay("a", "fantome"), wait("w", 600)))
    client.post("/api/runs", json={"program_id": "scene"})
    deadline = time.time() + 3
    while not pi.relays.is_on("fantome") and time.time() < deadline:
        time.sleep(0.02)
    with connect(client) as ws:
        snapshot = ws.receive_json()
    assert snapshot["type"] == "snapshot" and snapshot["ts"] > 0
    assert [r["program_id"] for r in snapshot["runs"]] == ["scene"]
    assert snapshot["relays"]["fantome"] is True and snapshot["locked"] is False
    client.post("/api/runs/stop")


# ------------------------------------------------------------------ suivi d'un scénario


def test_a_websocket_client_follows_a_scenario_live(client, pi):
    save(client, program("scene", relay("a", "fantome"), wait("w", 0.1), relay("b", "orage")))
    with connect(client) as ws:
        assert ws.receive_json()["type"] == "snapshot"
        run_id = client.post("/api/runs", json={"program_id": "scene"}).json()["run_id"]
        events = receive_until(ws, lambda e: e["type"] == "run_ended")

    assert types(events)[0] == "run_started" and events[-1]["outcome"] == "completed"
    assert all(e.get("run_id", run_id) == run_id for e in events)
    # chaque bloc est annoncé (début puis fin), avec script et programme
    started = [e["node_id"] for e in events if e["type"] == "node_started"]
    finished = [e["node_id"] for e in events if e["type"] == "node_finished"]
    assert started == ["n", "a", "w", "b"] and sorted(finished) == sorted(started)
    first = next(e for e in events if e["type"] == "node_started")
    assert first["script_id"] == "s" and first["program_id"] == "scene"
    # les relais annoncent leur changement d'état, dans l'ordre
    relay_events = [
        (e["component_id"], e["state"]) for e in events if e["type"] == "component_changed"
    ]
    assert relay_events[:2] == [("fantome", "on"), ("orage", "on")]
    assert ("fantome", "off") in relay_events  # remise au repos de fin de scénario
    assert types(events).index("node_started") > types(events).index("run_started")


def test_light_changes_are_announced_with_their_parameters(client):
    with connect(client) as ws:
        ws.receive_json()
        client.post(
            "/api/components/lights/bandeau/test",
            json={"action": "on", "rgb_color": [255, 0, 0], "brightness": 40, "transition": 2},
        )
        event = receive_until(ws, lambda e: e["type"] == "component_changed")[-1]
    assert (
        event["kind"] == "light" and event["component_id"] == "bandeau" and event["state"] == "on"
    )
    assert event["details"] == {"rgb_color": [255, 0, 0], "brightness": 40, "transition": 2}


def test_button_presses_are_announced(client):
    with connect(client) as ws:
        ws.receive_json()
        client.post(
            "/api/components/buttons/bouton_principal/test",
            json={"action": "press", "event": "double"},
        )
        event = receive_until(ws, lambda e: e["type"] == "button_event")[-1]
    assert (event["button_id"], event["event"]) == ("bouton_principal", "double")


def test_catalogue_changes_are_announced(client):
    with connect(client) as ws:
        ws.receive_json()
        client.post("/api/components/switches", json={"name": "Prise", "entity_id": "switch.p"})
        event = receive_until(
            ws, lambda e: e["type"] == "component_changed" and e["kind"] == "catalog"
        )[-1]
    assert event["component_id"] is None


# ------------------------------------------------------------------ erreurs


def test_an_action_failure_is_an_error_event_and_the_run_goes_on(client, pi):
    light = {"id": "l", "type": "light", "target": "bandeau", "state": "on"}
    save(client, program("scene", light, wait("w", 0.05), relay("a", "fantome")))
    pi.ha.fail_with = HAError("Home Assistant injoignable")
    with connect(client) as ws:
        ws.receive_json()
        client.post("/api/runs", json={"program_id": "scene"})
        events = receive_until(ws, lambda e: e["type"] == "run_ended")
    error = next(e for e in events if e["type"] == "error")
    assert (
        error["source"] == "action"
        and error["node_id"] == "l"
        and error["component_id"] == "bandeau"
    )
    assert "injoignable" in error["message"] and error["run_id"]
    assert events[-1]["outcome"] == "completed"


def test_a_failed_run_ends_with_run_ended_and_an_error(client, pi):
    light = {"id": "l", "type": "light", "target": "bandeau", "state": "on", "on_error": "abort"}
    save(client, program("scene", light, wait("w", 0.05)))
    pi.ha.fail_with = HAError("Home Assistant injoignable")
    with connect(client) as ws:
        ws.receive_json()
        client.post("/api/runs", json={"program_id": "scene"})
        events = receive_until(ws, lambda e: e["type"] == "run_ended")
        run_errors = [e for e in events if e["type"] == "error"]
        follow_up = ws.receive_json()
    assert events[-1]["outcome"] == "failed" and run_errors[0]["source"] == "action"
    assert follow_up["type"] == "error" and follow_up["source"] == "run"


# ------------------------------------------------------------------ plusieurs clients et nettoyage


def test_several_clients_receive_the_same_events(client):
    with connect(client) as first, connect(client) as second:
        first.receive_json()
        second.receive_json()
        client.post("/api/components/buttons/bouton_principal/test", json={"action": "press"})
        a = receive_until(first, lambda e: e["type"] == "button_event")[-1]
        b = receive_until(second, lambda e: e["type"] == "button_event")[-1]
    assert a["button_id"] == b["button_id"] == "bouton_principal"


def test_a_disconnected_client_is_cleaned_up(client):
    hub = engine_of(client).hub
    with connect(client) as ws:
        ws.receive_json()
        assert len(hub._subscribers) == 1
    deadline = time.time() + 3
    while hub._subscribers and time.time() < deadline:
        time.sleep(0.02)
    assert hub._subscribers == set()


def test_events_survive_a_hot_reconfiguration(client):
    with connect(client) as ws:
        ws.receive_json()
        client.put(
            "/api/components/relays/fantome", json={"name": "F", "pin": 23, "mode": "latched"}
        )
        receive_until(ws, lambda e: e["type"] == "component_changed" and e["kind"] == "catalog")
        client.post("/api/components/buttons/bouton_principal/test", json={"action": "press"})
        receive_until(
            ws, lambda e: e["type"] == "button_event"
        )  # la connexion est restée utilisable
