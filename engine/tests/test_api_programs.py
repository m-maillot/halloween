import copy
import json
from pathlib import Path

import pytest

from api_helpers import Pi, call, engine_of, start_run

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def main_program() -> dict:
    return json.loads((DATA / "scenario_principal.json").read_text(encoding="utf-8"))


def simple(id_="demo", seconds=1, **kw) -> dict:
    return {
        "schema": 1,
        "id": id_,
        "name": id_,
        "scripts": [
            {
                "id": "s1",
                "root": {
                    "id": "n",
                    "type": "sequence",
                    "children": [
                        {"id": "a", "type": "relay", "target": "fantome", "state": "on"},
                        {"id": "w", "type": "wait", "seconds": seconds},
                    ],
                },
            }
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


def put(client, program: dict, if_match: str | None = None, **kw):
    headers = {"If-Match": if_match} if if_match is not None else {}
    return client.put(f"/api/programs/{program['id']}", json=program, headers=headers, **kw)


# ------------------------------------------------------------------ création et lecture


def test_create_then_read_with_etag(client):
    created = put(client, simple())
    assert created.status_code == 201 and created.headers["ETag"] == '"1"'
    body = created.json()
    assert (
        body["program"]["revision"] == 1
        and body["program"]["schema"] == 1
        and body["warnings"] == []
    )
    read = client.get("/api/programs/demo")
    assert read.status_code == 200 and read.headers["ETag"] == '"1"'
    assert read.json()["scripts"][0]["root"]["children"][0]["target"] == "fantome"
    assert "schema" in read.json() and "schema_version" not in read.json()


def test_the_scenario_of_the_spec_is_accepted(client):
    response = put(client, main_program())
    assert response.status_code == 201, response.text


def test_list_programs_sorted_for_the_show_mode(client):
    put(client, simple("zeta", show=True, show_order=2))
    put(client, simple("alpha", show=True, show_order=1))
    put(client, simple("autre"))
    listing = client.get("/api/programs").json()
    assert [p["id"] for p in listing] == ["alpha", "zeta", "autre"]
    assert listing[0] | {"valid": True} == {
        "id": "alpha",
        "name": "alpha",
        "revision": 1,
        "show": True,
        "show_order": 1,
        "max_duration_s": None,
        "scripts": 1,
        "valid": True,
        "running": False,
    }


def test_unknown_program_is_a_404(client):
    assert client.get("/api/programs/nope").status_code == 404
    assert client.delete("/api/programs/nope").status_code == 404


# ------------------------------------------------------------------ révisions


def test_update_needs_the_current_revision(client):
    put(client, simple())
    assert put(client, simple(seconds=2)).status_code == 428  # If-Match obligatoire
    ok = put(client, simple(seconds=2), '"1"')
    assert (
        ok.status_code == 200
        and ok.json()["program"]["revision"] == 2
        and ok.headers["ETag"] == '"2"'
    )
    assert (
        client.get("/api/programs/demo").json()["scripts"][0]["root"]["children"][1]["seconds"] == 2
    )


def test_stale_revision_is_a_412_with_the_current_revision(client):
    put(client, simple())
    put(client, simple(seconds=2), '"1"')
    stale = put(client, simple(seconds=9), '"1"')
    assert stale.status_code == 412
    assert stale.json()["detail"]["current_revision"] == 2
    assert (
        client.get("/api/programs/demo").json()["scripts"][0]["root"]["children"][1]["seconds"] == 2
    )


@pytest.mark.parametrize("header", ["1", 'W/"1"', ' "1" '])
def test_if_match_formats(client, header):
    put(client, simple())
    assert put(client, simple(seconds=3), header).status_code == 200


def test_if_match_must_be_a_revision_number(client):
    put(client, simple())
    assert put(client, simple(), "abc").status_code == 400


def test_creation_with_a_revision_is_refused_but_zero_means_create(client):
    assert put(client, simple("a"), '"3"').status_code == 412
    assert put(client, simple("b"), "0").status_code == 201


def test_body_id_must_match_the_url(client):
    response = client.put("/api/programs/autre", json=simple("demo"))
    assert (
        response.status_code == 422 and "ne correspond pas" in response.json()["detail"]["message"]
    )


def test_invalid_json_is_a_400(client):
    response = client.put(
        "/api/programs/demo", content=b"{pas du json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400


# ------------------------------------------------------------------ validation


def test_invalid_shape_is_refused_with_errors_located_on_the_block(client):
    bad = simple()
    bad["scripts"][0]["root"]["children"][1]["seconds"] = -5
    response = put(client, bad)
    assert response.status_code == 422
    issues = response.json()["detail"]["issues"]
    assert [i["node_id"] for i in issues] == ["w"] and issues[0]["severity"] == "error"
    assert client.get("/api/programs/demo").status_code == 404  # rien d'écrit


def test_semantic_errors_are_refused_with_the_faulty_block(client):
    bad = simple()
    bad["scripts"][0]["root"]["children"][0]["target"] = "composant-inconnu"
    response = put(client, bad)
    issues = response.json()["detail"]["issues"]
    assert (
        response.status_code == 422
        and issues[0]["code"] == "unknown_component"
        and issues[0]["node_id"] == "a"
    )


def test_relay_mode_and_light_capabilities_are_checked(client):
    bad = simple()
    bad["scripts"][0]["root"]["children"] = [
        {"id": "a", "type": "relay", "target": "fantome", "action": "trigger"},  # relais maintenu
        {"id": "b", "type": "light", "target": "guirlande", "state": "on", "rgb_color": [1, 2, 3]},
    ]
    issues = put(client, bad).json()["detail"]["issues"]
    assert {(i["code"], i["node_id"]) for i in issues} == {
        ("relay_mode", "a"),
        ("unsupported_parameter", "b"),
    }


def test_warnings_do_not_block_saving_and_are_returned(client):
    program = simple()
    program["scripts"].append(
        {"id": "s2", "root": {"id": "m", "type": "relay", "target": "fantome", "state": "off"}}
    )
    response = put(client, program)
    assert response.status_code == 201
    assert {w["code"] for w in response.json()["warnings"]} == {"parallel_conflict"}


def test_calls_are_checked_against_stored_programs(client):
    caller = simple("appelant")
    caller["scripts"][0]["root"]["children"].append(
        {"id": "c", "type": "call", "program_id": "absent"}
    )
    assert put(client, caller).json()["detail"]["issues"][0]["code"] == "unknown_program"
    put(client, simple("sous-programme"))
    caller["scripts"][0]["root"]["children"][-1]["program_id"] = "sous-programme"
    assert put(client, caller).status_code == 201


def test_validate_endpoint_always_answers_200_with_the_issues(client):
    good = client.post("/api/programs/validate", json=simple())
    assert good.status_code == 200 and good.json() == {"valid": True, "issues": []}

    shape = simple()
    shape["scripts"][0]["root"]["children"][1]["seconds"] = -1
    body = client.post("/api/programs/validate", json=shape).json()
    assert body["valid"] is False and body["issues"][0]["node_id"] == "w"

    semantic = simple()
    semantic["scripts"][0]["root"]["children"][0]["target"] = "nope"
    body = client.post("/api/programs/validate", json=semantic).json()
    assert body["valid"] is False and body["issues"][0]["code"] == "unknown_component"
    assert client.get("/api/programs/demo").status_code == 404  # validate n'enregistre rien


def test_validate_reports_warnings_without_invalidating(client):
    program = simple()
    program["scripts"].append(
        {"id": "s2", "root": {"id": "m", "type": "relay", "target": "fantome", "state": "off"}}
    )
    body = client.post("/api/programs/validate", json=program).json()
    assert body["valid"] is True and {i["severity"] for i in body["issues"]} == {"warning"}


# ------------------------------------------------------------------ suppression


def test_delete_a_program(client, pi):
    put(client, simple())
    assert client.delete("/api/programs/demo").status_code == 204
    assert client.get("/api/programs").json() == []
    assert not (pi.store.programs_dir / "demo.json").exists()


def test_delete_is_refused_while_running(client):
    put(client, simple(seconds=600))
    run = start_run(client, "demo")
    response = client.delete("/api/programs/demo")
    assert response.status_code == 409 and "en cours" in response.json()["detail"]["message"]
    call(client, engine_of(client).manager.stop, run.id)
    assert client.delete("/api/programs/demo").status_code == 204


def test_delete_is_refused_while_used_by_a_trigger_or_a_call(client, pi):
    put(client, simple("sous"))
    caller = simple("appelant")
    caller["scripts"][0]["root"]["children"].append(
        {"id": "c", "type": "call", "program_id": "sous"}
    )
    put(client, caller)
    pi.store.save_triggers(
        [
            {
                "id": "t1",
                "source": "button",
                "button": "bouton_principal",
                "event": "short",
                "program": "sous",
            }
        ]
    )
    engine_of(client).reload_content()
    message = client.delete("/api/programs/sous").json()["detail"]["message"]
    assert "déclencheur `t1`" in message and "appelant" in message


# ------------------------------------------------------------------ effets sur le moteur


def test_saved_program_is_immediately_runnable_and_listed_as_valid(client):
    put(client, simple())
    assert "demo" in engine_of(client).programs
    run = start_run(client, "demo")
    assert client.get("/api/programs").json()[0]["running"] is True
    call(client, engine_of(client).manager.stop, run.id)


def test_a_running_program_is_not_disturbed_by_saving_a_new_revision(client):
    put(client, simple(seconds=600))
    run = start_run(client, "demo")
    put(client, simple(seconds=1), '"1"')
    assert run.state == "running"
    call(client, engine_of(client).manager.stop, run.id)


# ------------------------------------------------------------------ simulation


def test_simulate_a_stored_program(client):
    put(client, main_program())
    body = client.post("/api/simulate", json={"program_id": "scenario-principal"}).json()
    assert body["status"] == "completed" and body["duration_s"] == 17
    first = body["timeline"][0]
    assert first["component"] == "bandeau" and first["action"] == "on"
    assert first["data"] == {"rgb_color": [255, 0, 0], "brightness": 40, "transition": 2}
    assert body["timeline"][-1] == {"t": 17, "component": "epouvantail", "action": "on", "data": {}}
    assert body["still_on"] == ["epouvantail"]


def test_simulate_a_draft_without_saving_it(client):
    body = client.post("/api/simulate", json={"program": simple(seconds=5)}).json()
    assert body["status"] == "completed" and body["duration_s"] == 5
    assert client.get("/api/programs/demo").status_code == 404


def test_simulate_with_scripted_button_presses(client):
    program = simple()
    program["scripts"][0]["root"] = {
        "id": "u",
        "type": "wait_until",
        "condition": {"type": "button", "id": "bouton_principal", "event": "short"},
    }
    stuck = client.post("/api/simulate", json={"program": program}).json()
    assert stuck["status"] == "deadlock"
    freed = client.post(
        "/api/simulate",
        json={"program": program, "button_presses": [{"t": 4, "button": "bouton_principal"}]},
    ).json()
    assert freed["status"] == "completed" and freed["duration_s"] == 4


def test_simulate_refuses_invalid_input(client):
    assert client.post("/api/simulate", json={}).status_code == 422
    assert (
        client.post("/api/simulate", json={"program_id": "a", "program": simple()}).status_code
        == 422
    )
    assert client.post("/api/simulate", json={"program_id": "nope"}).status_code == 404
    bad = copy.deepcopy(simple())
    bad["scripts"][0]["root"]["children"][0]["target"] = "nope"
    response = client.post("/api/simulate", json={"program": bad})
    assert response.status_code == 422 and response.json()["detail"]["issues"][0]["node_id"] == "a"


def test_simulate_does_not_touch_the_hardware(client, pi):
    put(client, simple())
    calls_before = len(pi.ha.calls)  # le repos appliqué au démarrage
    client.post("/api/simulate", json={"program_id": "demo"})
    assert not pi.relays.is_on("fantome") and len(pi.ha.calls) == calls_before


def test_program_routes_need_the_token(pi):
    from fastapi.testclient import TestClient

    with TestClient(pi.app()) as anonymous:
        assert anonymous.get("/api/programs").status_code == 401
        assert anonymous.put("/api/programs/demo", json=simple()).status_code == 401
        assert anonymous.post("/api/simulate", json={"program_id": "demo"}).status_code == 401
        assert anonymous.post("/api/programs/validate", json=simple()).status_code == 401
