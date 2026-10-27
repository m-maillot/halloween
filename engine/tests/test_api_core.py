import os
import signal
import socket
import stat
import threading
import time
import urllib.error
import urllib.request

import pytest
from fastapi.testclient import TestClient

from api_helpers import AUTH, TOKEN, Pi
from halloween.api.auth import MIN_TOKEN_LENGTH, load_or_create_token
from halloween.app import StartupError
from halloween.cli import main


@pytest.fixture
def pi(tmp_path) -> Pi:
    return Pi(tmp_path)


# ------------------------------------------------------------------ authentification


def test_health_needs_no_token_and_reveals_nothing_else(pi):
    with TestClient(pi.app()) as client:
        response = client.get("/api/health")
    assert response.status_code == 200 and response.json() == {"ok": True}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer mauvais"},
        {"Authorization": TOKEN},
        {"Authorization": "Basic abc"},
    ],
)
def test_api_refuses_requests_without_a_valid_token(pi, headers):
    with TestClient(pi.app()) as client:
        response = client.get("/api/status", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_token_in_the_query_string_is_not_accepted_for_http(pi):
    with TestClient(pi.app()) as client:
        assert client.get(f"/api/status?token={TOKEN}").status_code == 401


def test_valid_token_gives_access_and_scheme_is_case_insensitive(pi):
    with TestClient(pi.app()) as client:
        assert client.get("/api/status", headers=AUTH).status_code == 200
        assert (
            client.get("/api/status", headers={"Authorization": f"bearer {TOKEN}"}).status_code
            == 200
        )


def test_status_describes_the_engine(pi):
    pi.program("bon", {"id": "w", "type": "wait", "seconds": 1})
    with pi.client() as client:
        body = client.get("/api/status").json()
    assert body["relays"] == {
        "fantome": False,
        "squelette": False,
        "epouvantail": False,
        "orage": False,
    }
    assert body["runs"] == [] and body["startup_issues"] == []
    assert body["home_assistant"]["mode"] == "dry-run" and body["version"]


def test_unknown_api_route_is_a_json_404_even_with_a_ui(pi, tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html>app</html>")
    with pi.client(static_dir=ui) as client:
        response = client.get("/api/nope")
    assert response.status_code == 404 and "<html" not in response.text


# ------------------------------------------------------------------ jeton


def test_token_from_the_environment_wins(tmp_path):
    token, origin = load_or_create_token(tmp_path, {"HALLOWEEN_API_TOKEN": "x" * 20})
    assert token == "x" * 20 and "HALLOWEEN_API_TOKEN" in origin
    assert not (tmp_path / "api-token").exists()


def test_too_short_environment_token_is_refused(tmp_path):
    with pytest.raises(ValueError, match="trop court"):
        load_or_create_token(tmp_path, {"HALLOWEEN_API_TOKEN": "court"})


def test_token_file_is_created_once_with_private_permissions(tmp_path):
    first, origin = load_or_create_token(tmp_path, {})
    again, _ = load_or_create_token(tmp_path, {})
    assert first == again and len(first) >= MIN_TOKEN_LENGTH and "créé" in origin
    assert stat.S_IMODE((tmp_path / "api-token").stat().st_mode) == 0o600


def test_a_too_short_stored_token_is_replaced(tmp_path):
    (tmp_path / "api-token").write_text("abc\n")
    token, _ = load_or_create_token(tmp_path, {})
    assert len(token) >= MIN_TOKEN_LENGTH


# ------------------------------------------------------------------ interface statique


@pytest.fixture
def ui_dir(tmp_path):
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<html><body>Déco Halloween UI</body></html>", encoding="utf-8")
    (ui / "assets" / "app.js").write_text("console.log('app')")
    return ui


def test_ui_is_served_at_the_root_and_spa_routes_fall_back_to_index(pi, ui_dir):
    with TestClient(pi.app(static_dir=ui_dir)) as client:  # sans jeton : l'interface est publique
        for path in ("/", "/spectacle", "/scenarios/mon-scenario"):
            response = client.get(path)
            assert response.status_code == 200 and "Déco Halloween UI" in response.text
        assert client.get("/assets/app.js").text == "console.log('app')"


def test_placeholder_when_no_ui_is_installed(pi):
    with TestClient(pi.app()) as client:
        for path in ("/", "/spectacle"):
            response = client.get(path)
            assert response.status_code == 200 and "interface n'est pas installée" in response.text
        assert client.get("/api/inconnu").status_code == 404


# ------------------------------------------------------------------ démarrage


def test_invalid_configuration_prevents_the_application_from_starting(pi):
    pi.store.config_path.write_text("{", encoding="utf-8")
    app = pi.app()
    with pytest.raises(StartupError), TestClient(app):
        pass
    assert app.state.startup_error is not None and pi.relays is None


def test_engine_is_stopped_with_the_application(pi):
    pi.program(
        "bon", {"id": "r", "type": "relay", "target": "fantome", "state": "on"}, on_end="keep"
    )
    with pi.client() as client:
        assert client.get("/api/status").status_code == 200
        pi.relays._state["fantome"] = True
    assert not pi.relays.is_on("fantome")  # arrêt propre : relais éteints


# ------------------------------------------------------------------ commande `api`


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_cli_api_serves_over_a_real_socket_and_stops_on_sigterm(tmp_path):
    pi = Pi(tmp_path)
    port = _free_port()
    results: dict = {}

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
        request = urllib.request.Request(
            f"{base}/api/status", headers={"Authorization": f"Bearer {token}"}
        )
        results["status"] = urllib.request.urlopen(request, timeout=2).status
        try:
            urllib.request.urlopen(f"{base}/api/status", timeout=2)
        except urllib.error.HTTPError as exc:
            results["anonymous"] = exc.code
        results["spectacle"] = urllib.request.urlopen(f"{base}/spectacle", timeout=2).status
        os.kill(os.getpid(), signal.SIGTERM)

    thread = threading.Thread(target=probe, daemon=True)
    thread.start()
    import io

    out = io.StringIO()
    code = main(
        ["--data-dir", str(pi.store.root), "api", "--port", str(port), "--host", "127.0.0.1"],
        pi.backend(),
        out,
    )
    thread.join(timeout=5)
    assert code == 130
    assert results == {"status": 200, "anonymous": 401, "spectacle": 200}
    text = out.getvalue()
    assert "Moteur prêt" in text and "api-token" in text and "Service arrêté" in text
    assert TOKEN not in text and (pi.store.root / "api-token").read_text().strip() not in text


def test_cli_api_reports_a_startup_error(tmp_path, capsys):
    import io

    pi = Pi(tmp_path)
    pi.store.config_path.write_text("{", encoding="utf-8")
    code = main(
        [
            "--data-dir",
            str(pi.store.root),
            "api",
            "--port",
            str(_free_port()),
            "--host",
            "127.0.0.1",
        ],
        pi.backend(),
        io.StringIO(),
    )
    assert code == 2 and "invalide" in capsys.readouterr().err
