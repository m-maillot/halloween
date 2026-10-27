import json
import time

import pytest

from api_helpers import Pi


def relay(id_, target, state="on"):
    return {"id": id_, "type": "relay", "target": target, "state": state}


def wait(id_, seconds):
    return {"id": id_, "type": "wait", "seconds": seconds}


def program(id_, *children, **kw) -> dict:
    return {
        "schema": 1,
        "id": id_,
        "name": id_,
        "scripts": [
            {"id": "s", "root": {"id": "n", "type": "sequence", "children": list(children)}}
        ],
        **kw,
    }


@pytest.fixture
def pi(tmp_path) -> Pi:
    return Pi(tmp_path)


@pytest.fixture
def client(pi):
    with pi.client() as c:
        yield c


def save(client, prog: dict):
    response = client.put(f"/api/programs/{prog['id']}", json=prog)
    assert response.status_code in (200, 201), response.text


def eventually(check, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return False


def running_ids(client) -> list[str]:
    return sorted(r["program_id"] for r in client.get("/api/runs").json())


# ------------------------------------------------------------------ runs


def test_start_list_and_status(client, pi):
    save(client, program("scene", relay("a", "fantome"), wait("w", 600)))
    response = client.post("/api/runs", json={"program_id": "scene"})
    assert response.status_code == 201
    run = response.json()
    assert run["program_id"] == "scene" and run["state"] == "running" and run["outcome"] is None
    assert eventually(lambda: pi.relays.is_on("fantome"))
    assert [r["run_id"] for r in client.get("/api/runs").json()] == [run["run_id"]]
    status = client.get("/api/status").json()
    assert [r["run_id"] for r in status["runs"]] == [run["run_id"]] and status["relays"][
        "fantome"
    ] is True


def test_several_programs_run_together_and_stop_individually_or_globally(client, pi):
    save(client, program("ambiance", relay("a", "orage"), wait("w", 600)))
    save(client, program("scene", relay("b", "fantome"), wait("w", 600)))
    ids = {
        pid: client.post("/api/runs", json={"program_id": pid}).json()["run_id"]
        for pid in ("ambiance", "scene")
    }
    assert running_ids(client) == ["ambiance", "scene"]

    stopped = client.post(f"/api/runs/{ids['scene']}/stop")
    assert stopped.status_code == 200 and stopped.json()["outcome"] == "stopped"
    assert running_ids(client) == ["ambiance"]  # l'ambiance continue
    assert pi.relays.is_on("orage") and not pi.relays.is_on("fantome")

    again = client.post("/api/runs", json={"program_id": "scene"}).json()["run_id"]
    assert eventually(lambda: pi.relays.is_on("fantome"))
    result = client.post("/api/runs/stop")
    assert result.status_code == 200 and result.json() == {"stopped": 2}
    assert client.get("/api/runs").json() == []
    assert not pi.relays.is_on("orage") and not pi.relays.is_on("fantome")
    assert again != ids["scene"]


def test_stop_global_applies_the_full_rest_state(client, pi):
    save(client, program("scene", relay("a", "fantome"), wait("w", 600)))
    client.post("/api/runs", json={"program_id": "scene"})
    before = len(pi.ha.calls)
    client.post("/api/runs/stop")
    assert [c[2]["entity_id"] for c in pi.ha.calls[before:]] == [
        "light.bandeau_hue",
        "light.twinkly_halloween",
    ]


def test_ignore_policy_gives_a_409_with_the_running_run(client):
    save(client, program("scene", wait("w", 600)))
    first = client.post("/api/runs", json={"program_id": "scene"}).json()
    second = client.post("/api/runs", json={"program_id": "scene"})
    assert second.status_code == 409 and second.json()["detail"]["run_id"] == first["run_id"]
    assert len(client.get("/api/runs").json()) == 1


def test_restart_and_queue_policies(client):
    save(client, program("scene", wait("w", 600)))
    first = client.post("/api/runs", json={"program_id": "scene"}).json()
    restarted = client.post("/api/runs", json={"program_id": "scene", "policy": "restart"}).json()
    assert restarted["run_id"] != first["run_id"] and running_ids(client) == ["scene"]
    queued = client.post("/api/runs", json={"program_id": "scene", "policy": "queue"}).json()
    assert queued["state"] == "queued"
    assert sorted(r["state"] for r in client.get("/api/runs").json()) == ["queued", "running"]
    client.post("/api/runs/stop")


def test_unknown_and_invalid_programs(client, pi):
    assert client.post("/api/runs", json={"program_id": "nope"}).status_code == 404
    save(client, program("scene", relay("a", "fantome")))
    # le relais devient impulsion : le programme est écarté, pas lancé
    client.put(
        "/api/components/relays/fantome", json={"name": "Fantôme", "pin": 18, "mode": "push"}
    )
    response = client.post("/api/runs", json={"program_id": "scene"})
    assert response.status_code == 422 and "écarté" in response.json()["detail"]["message"]


def test_a_finished_program_disappears_from_the_runs(client):
    save(client, program("court", wait("w", 0.05)))
    client.post("/api/runs", json={"program_id": "court"})
    assert eventually(lambda: client.get("/api/runs").json() == [])


def test_stop_of_unknown_run_is_a_404_and_global_stop_with_nothing_running_is_fine(client):
    assert client.post("/api/runs/inconnu/stop").status_code == 404
    assert client.post("/api/runs/stop").json() == {"stopped": 0}


def test_bad_policy_is_rejected(client):
    assert client.post("/api/runs", json={"program_id": "x", "policy": "foo"}).status_code == 422


# ------------------------------------------------------------------ déclencheurs


BUTTON_GO = {
    "id": "go",
    "source": "button",
    "button": "bouton_principal",
    "event": "short",
    "program": "scene",
}
BUTTON_STOP = {
    "id": "halt",
    "source": "button",
    "button": "bouton_principal",
    "event": "long",
    "action": "stop",
}


def press(client, event):
    response = client.post(
        "/api/components/buttons/bouton_principal/test", json={"action": "press", "event": event}
    )
    assert response.status_code == 200


def test_triggers_are_empty_at_first(client):
    assert client.get("/api/triggers").json() == {"triggers": [], "issues": []}


def test_put_triggers_persists_and_takes_effect_immediately(client, pi):
    save(client, program("scene", relay("a", "fantome"), wait("w", 600)))
    response = client.put("/api/triggers", json=[BUTTON_GO, BUTTON_STOP])
    assert response.status_code == 200 and len(response.json()["triggers"]) == 2
    saved = json.loads(pi.store.triggers_path.read_text(encoding="utf-8"))
    assert [t["id"] for t in saved] == ["go", "halt"] and saved[0]["policy"] == "ignore"

    press(client, "short")  # le bouton lance le scénario...
    assert eventually(lambda: running_ids(client) == ["scene"] and pi.relays.is_on("fantome"))
    press(client, "long")  # ...et l'appui long l'arrête
    assert eventually(lambda: client.get("/api/runs").json() == [])
    assert not pi.relays.is_on("fantome")


def test_replacing_with_an_empty_list_disables_the_button(client):
    save(client, program("scene", wait("w", 600)))
    client.put("/api/triggers", json=[BUTTON_GO])
    client.put("/api/triggers", json=[])
    press(client, "short")
    time.sleep(0.2)
    assert client.get("/api/runs").json() == []


def test_schedule_triggers_are_accepted_and_returned(client):
    save(client, program("scene", wait("w", 5)))
    schedule = {"id": "soir", "source": "schedule", "cron": "0 18 31 10 *", "program": "scene"}
    body = client.put("/api/triggers", json=[schedule]).json()
    assert body["triggers"][0]["cron"] == "0 18 31 10 *"
    assert client.get("/api/triggers").json()["triggers"][0]["id"] == "soir"


def test_invalid_triggers_refuse_the_whole_replacement(client, pi):
    save(client, program("scene", wait("w", 5)))
    client.put("/api/triggers", json=[BUTTON_GO])
    bad = [
        BUTTON_STOP,
        {"id": "x", "source": "schedule", "cron": "0 18 31", "program": "scene"},
        {
            "id": "y",
            "source": "button",
            "button": "bouton_principal",
            "event": "triple",
            "program": "scene",
        },
    ]
    response = client.put("/api/triggers", json=bad)
    assert response.status_code == 422
    messages = " ".join(i["message"] for i in response.json()["detail"]["issues"])
    assert "n°2" in messages and "cron invalide" in messages and "n°3" in messages
    assert [t["id"] for t in client.get("/api/triggers").json()["triggers"]] == ["go"]  # inchangé


def test_triggers_must_reference_existing_buttons_and_programs(client):
    response = client.put(
        "/api/triggers",
        json=[
            {
                "id": "a",
                "source": "button",
                "button": "nope",
                "event": "short",
                "program": "inconnu",
            },
        ],
    )
    codes = {i["code"] for i in response.json()["detail"]["issues"]}
    assert response.status_code == 422 and codes == {"unknown_button", "unknown_program"}


def test_duplicate_triggers_are_only_a_warning(client):
    save(client, program("scene", wait("w", 5)))
    twin = {**BUTTON_GO, "id": "go2"}
    response = client.put("/api/triggers", json=[BUTTON_GO, twin])
    assert response.status_code == 200
    assert {i["code"] for i in response.json()["issues"]} == {"duplicate_trigger"}


def test_triggers_must_be_a_json_list(client):
    assert client.put("/api/triggers", json={"a": 1}).status_code == 422
    assert (
        client.put(
            "/api/triggers", content=b"[", headers={"Content-Type": "application/json"}
        ).status_code
        == 400
    )


def test_trigger_whose_program_becomes_invalid_is_reported(client):
    save(client, program("scene", relay("a", "fantome")))
    client.put("/api/triggers", json=[BUTTON_GO])
    client.put(
        "/api/components/relays/fantome", json={"name": "Fantôme", "pin": 18, "mode": "push"}
    )
    body = client.get("/api/triggers").json()
    assert any(i["code"] == "unknown_program" for i in body["issues"])  # écarté, pas supprimé
    assert len(body["triggers"]) == 1


def test_run_and_trigger_routes_need_the_token(pi):
    from fastapi.testclient import TestClient

    with TestClient(pi.app()) as anonymous:
        assert anonymous.get("/api/runs").status_code == 401
        assert anonymous.post("/api/runs", json={"program_id": "x"}).status_code == 401
        assert anonymous.post("/api/runs/stop").status_code == 401
        assert anonymous.get("/api/triggers").status_code == 401
        assert anonymous.put("/api/triggers", json=[]).status_code == 401
