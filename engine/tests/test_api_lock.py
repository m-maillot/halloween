"""Verrouillage par code (spec 1 §6.4) : 423 sur les écritures, code pour lancer, STOP libre."""

from __future__ import annotations

import json
import re
import time

import pytest

from api_helpers import AUTH, Pi, call, engine_of, start_run
from halloween.api.deps import SAFE_METHODS
from halloween.lock import LOCK_FILE

CODE = "4242"


def eventually(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


@pytest.fixture
def pi(tmp_path):
    return Pi(tmp_path)


def locked_client(pi, *, with_program=True):
    if with_program:
        pi.program("rien", {"id": "w", "type": "wait", "seconds": 60})
    client = pi.client()
    client.__enter__()
    assert client.put("/api/lock/code", json={"new_code": CODE}).status_code == 200
    assert client.post("/api/lock").status_code == 200
    return client


def test_initial_state_is_unlocked_without_code(pi):
    with pi.client() as client:
        assert client.get("/api/lock").json() == {
            "locked": False,
            "has_code": False,
            "retry_after_s": None,
        }
        assert client.post("/api/lock").status_code == 409  # pas de code, pas de verrou


def test_set_code_validates_format(pi):
    with pi.client() as client:
        for bad in ("123", "123456789", "12a4", ""):
            assert client.put("/api/lock/code", json={"new_code": bad}).status_code == 422
        assert not client.get("/api/lock").json()["has_code"]


def test_change_code_needs_old_code(pi):
    with pi.client() as client:
        client.put("/api/lock/code", json={"new_code": CODE})
        assert client.put("/api/lock/code", json={"new_code": "9999"}).status_code == 401
        wrong = {"new_code": "9999", "old_code": "0000"}
        assert client.put("/api/lock/code", json=wrong).status_code == 401
        ok = {"new_code": "9999", "old_code": CODE}
        assert client.put("/api/lock/code", json=ok).status_code == 200
        assert client.post("/api/unlock", json={"code": "9999"}).status_code == 200


def test_lock_unlock_cycle_and_events(pi):
    with pi.client() as client:
        client.put("/api/lock/code", json={"new_code": CODE})
        with client.websocket_connect(f"/api/events?token={AUTH['Authorization'][7:]}") as ws:
            assert ws.receive_json()["locked"] is False
            client.post("/api/lock")
            event = ws.receive_json()
            assert (event["type"], event["locked"]) == ("lock_changed", True)
            client.post("/api/unlock", json={"code": CODE})
            event = ws.receive_json()
            assert (event["type"], event["locked"]) == ("lock_changed", False)
        client.post("/api/lock")
        assert client.get("/api/lock").json()["locked"] is True
        assert client.post("/api/unlock", json={"code": "0000"}).status_code == 401
        assert client.get("/api/lock").json()["locked"] is True
        assert client.post("/api/unlock", json={"code": CODE}).json()["locked"] is False


def test_unlock_without_code_defined(pi):
    with pi.client() as client:
        assert client.post("/api/unlock", json={"code": CODE}).status_code == 409


# Les seules écritures qui ne répondent pas 423 verrouillé (liste écrite en dur, indépendante du
# code qui décide) : lancement (qui exige le code lui-même), arrêts, verrou, lectures déguisées.
OPEN_WHEN_LOCKED = {
    ("POST", "/api/runs"),
    ("POST", "/api/runs/stop"),
    ("POST", "/api/runs/{run_id}/stop"),
    ("POST", "/api/lock"),
    ("POST", "/api/unlock"),
    ("POST", "/api/simulate"),
    ("POST", "/api/programs/validate"),
}


def test_every_write_route_answers_423_when_locked_except_the_documented_ones(pi):
    client = locked_client(pi)
    with client:
        spec = client.get("/api/openapi.json" if False else "/openapi.json").json()
        writes = [
            (method.upper(), path)
            for path, item in spec["paths"].items()
            for method in item
            if method.upper() not in SAFE_METHODS and path.startswith("/api")
        ]
        assert len(writes) >= 20  # garde-fou : l'énumération trouve bien les routes
        open_ones = set()
        for method, path in writes:
            response = client.request(method, re.sub(r"\{[^}]+\}", "x", path), json={})
            if response.status_code != 423 or "verrouillé" not in response.text:
                open_ones.add((method, path))
        assert open_ones == OPEN_WHEN_LOCKED


def test_writes_work_again_after_unlock(pi):
    client = locked_client(pi)
    with client:
        body = {"id": "p2", "name": "P2", "scripts": []}
        assert client.put("/api/programs/p2", json=body).status_code == 423
        client.post("/api/unlock", json={"code": CODE})
        assert client.put("/api/programs/p2", json=body).status_code != 423


def test_reads_stay_open_when_locked(pi):
    client = locked_client(pi)
    with client:
        for path in ("/api/status", "/api/devices", "/api/programs", "/api/runs", "/api/lock"):
            assert client.get(path).status_code == 200, path


def test_validate_and_simulate_stay_open(pi):
    client = locked_client(pi)
    with client:
        # Elles ne modifient rien : aucun 423 (le contenu de la requête peut, lui, être refusé).
        assert client.post("/api/programs/validate", json={}).status_code != 423
        assert client.post("/api/simulate", json={}).status_code != 423


def test_run_requires_code_when_locked(pi):
    client = locked_client(pi)
    with client:
        assert client.post("/api/runs", json={"program_id": "rien"}).status_code == 423
        wrong = client.post("/api/runs", json={"program_id": "rien", "code": "0000"})
        assert wrong.status_code == 401
        assert client.get("/api/runs").json() == []
        ok = client.post("/api/runs", json={"program_id": "rien", "code": CODE})
        assert ok.status_code == 201
        # Le code ne vaut que pour ce lancement : le suivant le redemande.
        again = client.post("/api/runs", json={"program_id": "rien", "policy": "restart"})
        assert again.status_code == 423


def test_run_needs_no_code_when_unlocked(pi):
    pi.program("rien", {"id": "w", "type": "wait", "seconds": 60})
    with pi.client() as client:
        client.put("/api/lock/code", json={"new_code": CODE})
        assert client.post("/api/runs", json={"program_id": "rien"}).status_code == 201


def test_stop_is_always_free(pi):
    client = locked_client(pi)
    with client:
        run = start_run(client, "rien")
        assert client.post(f"/api/runs/{run.id}/stop").status_code == 200
        start_run(client, "rien")
        assert client.post("/api/runs/stop").json() == {"stopped": 1}


def test_physical_triggers_keep_working_when_locked(pi):
    pi.program(
        "rien",
        {"id": "r", "type": "relay", "target": "fantome", "state": "on"},
        {"id": "w", "type": "wait", "seconds": 60},
    )
    pi.store.save_triggers(
        [
            {
                "id": "t1",
                "source": "button",
                "button": "bouton_principal",
                "event": "short",
                "program": "rien",
            }
        ]
    )
    client = locked_client(pi, with_program=False)
    with client:
        call(client, pi.buttons.press, "bouton_principal", "short")
        assert eventually(lambda: pi.relays.is_on("fantome"))


def test_lock_survives_restart(pi):
    with pi.client() as client:
        client.put("/api/lock/code", json={"new_code": CODE})
        client.post("/api/lock")
    with pi.client() as client:
        assert client.get("/api/lock").json()["locked"] is True
        assert client.put("/api/config/rest-state", json={}).status_code == 423
        assert client.post("/api/unlock", json={"code": CODE}).status_code == 200


def test_status_and_snapshot_report_lock(pi):
    client = locked_client(pi)
    with client:
        assert client.get("/api/status").json()["lock"] == {
            "locked": True,
            "has_code": True,
            "retry_after_s": None,
        }
        with client.websocket_connect(f"/api/events?token={AUTH['Authorization'][7:]}") as ws:
            assert ws.receive_json()["locked"] is True


def test_code_is_never_stored_or_returned_in_clear(pi, caplog):
    client = locked_client(pi)
    with client:
        text = (pi.store.root / LOCK_FILE).read_text(encoding="utf-8")
        assert CODE not in text
        data = json.loads(text)
        assert data["code"]["algo"] == "scrypt" and data["locked"] is True
        assert (pi.store.root / LOCK_FILE).stat().st_mode & 0o777 == 0o600
        client.post("/api/runs", json={"program_id": "rien", "code": "7777"})
        assert "7777" not in caplog.text and CODE not in caplog.text
        for path in ("/api/lock", "/api/status"):
            assert CODE not in client.get(path).text
            assert "hash" not in client.get(path).text and "salt" not in client.get(path).text


def test_same_salt_never_reused(pi):
    with pi.client() as client:
        client.put("/api/lock/code", json={"new_code": CODE})
        first = json.loads((pi.store.root / LOCK_FILE).read_text())["code"]
        client.put("/api/lock/code", json={"new_code": CODE, "old_code": CODE})
        second = json.loads((pi.store.root / LOCK_FILE).read_text())["code"]
        assert first["salt"] != second["salt"] and first["hash"] != second["hash"]


def test_unreadable_lock_file_fails_closed(pi):
    with pi.client() as client:
        (pi.store.root / LOCK_FILE).write_text("pas du json")
        assert client.get("/api/lock").json()["locked"] is True
        assert engine_of(client).lock.verify(CODE) is False
