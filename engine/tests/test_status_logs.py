"""Journal en fichier avec rotation, derniers problèmes et `GET /status` complet (diagnostic)."""

from __future__ import annotations

import io
import json
import logging
import os
import signal
import socket
import threading
import time
import urllib.request

import pytest

import halloween.log as logmod
from api_helpers import AUTH, TOKEN, Pi
from halloween.cli import main
from halloween.log import ProblemLog, get_logger, setup_logging


@pytest.fixture(autouse=True)
def clean_logging():
    yield
    setup_logging()  # rend un handler propre aux autres tests


def read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ------------------------------------------------------------------ journal et rotation


def test_the_log_file_gets_info_even_when_the_stream_only_shows_errors(tmp_path):
    stream = io.StringIO()
    setup_logging("ERROR", stream, tmp_path / "logs" / "halloween.log")
    get_logger("t").info("détail utile")
    get_logger("t").error("grave")
    lines = read_lines(tmp_path / "logs" / "halloween.log")
    assert [entry["message"] for entry in lines] == ["détail utile", "grave"]
    assert [json.loads(line)["message"] for line in stream.getvalue().splitlines()] == ["grave"]


def test_the_log_rotates_and_keeps_a_bounded_number_of_archives(tmp_path, monkeypatch):
    monkeypatch.setattr(logmod, "LOG_MAX_BYTES", 600)
    monkeypatch.setattr(logmod, "LOG_BACKUPS", 3)
    path = tmp_path / "halloween.log"
    setup_logging("ERROR", io.StringIO(), path)
    for i in range(200):
        get_logger("t").info("ligne numéro %d", i, extra={"run_id": f"r{i}"})
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["halloween.log", "halloween.log.1", "halloween.log.2", "halloween.log.3"]
    assert all(p.stat().st_size <= 1200 for p in tmp_path.iterdir())
    newest = read_lines(path)
    assert newest[-1]["message"] == "ligne numéro 199" and newest[-1]["run_id"] == "r199"
    # Chaque archive reste du JSON lines valide (aucune ligne coupée en deux).
    for archive in tmp_path.glob("halloween.log.*"):
        assert read_lines(archive)


def test_setup_twice_does_not_duplicate_file_lines(tmp_path):
    path = tmp_path / "halloween.log"
    for _ in range(2):
        setup_logging("ERROR", io.StringIO(), path)
    get_logger("t").info("une fois")
    assert len(read_lines(path)) == 1


# ------------------------------------------------------------------ derniers problèmes


def test_problem_log_keeps_only_warnings_newest_first_and_bounded():
    problems = ProblemLog(capacity=3)
    logger = logging.getLogger("halloween.probe")
    logger.addHandler(problems)
    try:
        logger.setLevel(logging.INFO)
        logger.info("ignoré")
        for i in range(5):
            logger.warning("avertissement %d", i)
        logger.error("erreur", extra={"component_id": "fantome"})
    finally:
        logger.removeHandler(problems)
    recent = problems.recent()
    assert [p["message"] for p in recent] == ["erreur", "avertissement 4", "avertissement 3"]
    assert recent[0]["level"] == "ERROR" and recent[0]["component_id"] == "fantome"
    assert recent[0]["source"] == "probe"
    assert len(problems.recent(limit=1)) == 1


# ------------------------------------------------------------------ /status


@pytest.fixture
def client(tmp_path):
    pi = Pi(tmp_path)
    pi.program("scene", {"id": "w", "type": "wait", "seconds": 60})
    with pi.client(log_file=tmp_path / "logs" / "halloween.log") as client:
        yield client


def test_status_gives_a_complete_diagnostic(client):
    status = client.get("/api/status").json()
    assert status["programs"] == 1 and status["triggers"] == 0
    assert status["uptime_s"] >= 0 and status["started_at"] > 1_700_000_000
    assert status["lock"] == {"locked": False, "has_code": False, "retry_after_s": None}
    assert status["relays"]["fantome"] is False
    assert status["home_assistant"]["mode"] == "dry-run"
    assert status["rest_pending"] == [] and status["recent_problems"] == []
    assert status["startup_issues"] == [] and status["runs"] == []
    assert status["log_file"].endswith("halloween.log")


def test_status_lists_recent_problems_with_the_newest_first(client):
    client.put("/api/lock/code", json={"new_code": "4242"})
    client.post("/api/lock")
    for _ in range(2):
        client.post("/api/unlock", json={"code": "0000"})
    problems = client.get("/api/status").json()["recent_problems"]
    assert [p["message"] for p in problems] == ["code incorrect", "code incorrect"]
    assert problems[0]["level"] == "WARNING" and problems[0]["source"] == "lock"
    assert problems[0]["ts"] >= problems[1]["ts"]


def test_status_reports_what_is_waiting_for_home_assistant(client):
    from api_helpers import engine_of

    engine_of(client).rest_pending = ["bandeau"]
    assert client.get("/api/status").json()["rest_pending"] == ["bandeau"]


def test_status_requires_the_token(client):
    assert client.get("/api/status", headers={"Authorization": "Bearer faux"}).status_code == 401


def test_run_start_and_end_are_journalled_with_the_run_id(client, tmp_path):
    setup_logging("ERROR", io.StringIO(), tmp_path / "logs" / "halloween.log")
    run = client.post("/api/runs", json={"program_id": "scene"}).json()
    client.post(f"/api/runs/{run['run_id']}/stop")
    deadline = time.time() + 3
    while time.time() < deadline:
        lines = read_lines(tmp_path / "logs" / "halloween.log")
        if any(entry["message"] == "run_ended" for entry in lines):
            break
        time.sleep(0.02)
    mine = [e for e in lines if e.get("run_id") == run["run_id"]]
    assert [e["message"] for e in mine] == ["run démarré", "run terminé"]
    assert mine[1]["outcome"] == "stopped" and mine[0]["program"] == "scene"


def test_the_api_token_never_reaches_the_journal(client, tmp_path):
    setup_logging("ERROR", io.StringIO(), tmp_path / "logs" / "halloween.log")
    client.post("/api/runs", json={"program_id": "scene"})
    client.get("/api/status")
    client.get("/api/status", headers={"Authorization": "Bearer faux"})
    text = (tmp_path / "logs" / "halloween.log").read_text(encoding="utf-8")
    assert TOKEN not in text and AUTH["Authorization"] not in text


# ------------------------------------------------------------------ commande `api`


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _serve_then_stop(pi, extra_args, action):
    port = _free_port()
    seen: dict = {}

    def probe():
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"{base}/api/health", timeout=1).read()
                break
            except OSError:
                time.sleep(0.1)
        token = (pi.store.root / "api-token").read_text().strip()
        seen.update(action(base, {"Authorization": f"Bearer {token}"}))
        os.kill(os.getpid(), signal.SIGTERM)

    thread = threading.Thread(target=probe, daemon=True)
    thread.start()
    err = io.StringIO()
    out = io.StringIO()
    import contextlib

    with contextlib.redirect_stderr(err):
        code = main(
            [
                "--data-dir",
                str(pi.store.root),
                *extra_args,
                "api",
                "--port",
                str(port),
                "--host",
                "127.0.0.1",
            ],
            pi.backend(),
            out,
        )
    thread.join(timeout=5)
    return code, seen, err.getvalue()


def _get(url, headers):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=headers)).read())


def test_cli_api_writes_the_journal_under_the_data_dir_by_default(tmp_path):
    pi = Pi(tmp_path)
    pi.program("scene", {"id": "w", "type": "wait", "seconds": 60})

    def action(base, headers):
        request = urllib.request.Request(
            f"{base}/api/runs",
            data=json.dumps({"program_id": "scene"}).encode(),
            headers={**headers, "Content-Type": "application/json"},
        )
        urllib.request.urlopen(request).read()
        return {"status": _get(f"{base}/api/status", headers)}

    code, seen, _ = _serve_then_stop(pi, [], action)
    assert code == 130
    log_path = pi.store.root / "logs" / "halloween.log"
    assert seen["status"]["log_file"] == str(log_path)
    messages = [entry["message"] for entry in read_lines(log_path)]
    assert "moteur démarré" in messages and "run démarré" in messages and "run terminé" in messages


def test_cli_api_honours_log_dir(tmp_path):
    pi = Pi(tmp_path)
    target = tmp_path / "ailleurs"
    code, seen, _ = _serve_then_stop(
        pi, ["--log-dir", str(target)], lambda base, h: {"s": _get(f"{base}/api/status", h)}
    )
    assert code == 130 and (target / "halloween.log").is_file()
    assert seen["s"]["log_file"] == str(target / "halloween.log")


def test_cli_api_still_starts_when_the_journal_cannot_be_written(tmp_path):
    pi = Pi(tmp_path)
    blocker = tmp_path / "fichier"
    blocker.write_text("pas un dossier")
    code, seen, err = _serve_then_stop(
        pi,
        ["--log-dir", str(blocker / "logs")],
        lambda base, h: {"s": _get(f"{base}/api/status", h)},
    )
    assert code == 130
    assert "journal en fichier impossible" in err
    assert seen["s"]["log_file"] is None


def test_a_failing_home_assistant_action_shows_up_in_status(tmp_path):
    from halloween.drivers.base import HAUnreachable

    pi = Pi(tmp_path)
    pi.program(
        "lumiere",
        {"id": "l", "type": "light", "target": "bandeau", "state": "on", "on_error": "continue"},
    )
    with pi.client() as client:
        pi.ha.fail_with = HAUnreachable("Home Assistant injoignable : connexion refusée")
        client.post("/api/runs", json={"program_id": "lumiere"})
        deadline = time.time() + 3
        problems = []
        while time.time() < deadline and not problems:
            problems = client.get("/api/status").json()["recent_problems"]
            time.sleep(0.02)
    # L'échec de l'action, puis celui de la remise au repos qui suit (plus récent en premier).
    assert all(p["level"] == "ERROR" for p in problems)
    assert "action en échec" in [p["message"] for p in problems]
