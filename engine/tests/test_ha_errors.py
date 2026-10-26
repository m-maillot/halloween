import asyncio
import io
import json
import socket
import time
from pathlib import Path

import httpx
import pytest

from halloween.config import AppConfig
from halloween.drivers import (
    FakeButtonDriver,
    FakeRelayDriver,
    HAAuthError,
    HABadRequest,
    HAError,
    HANotFound,
    HAServerError,
    HATimeout,
    HAUnreachable,
)
from halloween.drivers.homeassistant import HttpHAClient
from halloween.log import setup_logging
from halloween.program import Program
from halloween.program.runs import RunManager
from halloween.testing.fake_ha import TOKEN, FakeHA

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def ha():
    server = FakeHA().start()
    yield server
    server.stop()


def free_port() -> int:
    """Un port sur lequel plus rien n'écoute (connexion refusée)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def call_light(client: HttpHAClient) -> None:
    await client.light_off("light.x")


# ------------------------------------------------------------------ erreurs distinctes


async def test_unreachable_host_says_connection_refused():
    client = HttpHAClient(f"http://127.0.0.1:{free_port()}", TOKEN, timeout_s=2)
    try:
        with pytest.raises(HAUnreachable, match="connexion refusée"):
            await call_light(client)
    finally:
        await client.close()


async def test_unknown_host_is_reported_as_such():
    class NoDns(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.ConnectError("[Errno -2] Name or service not known")

    client = HttpHAClient("http://homeassistant.invalid:8123", TOKEN, transport=NoDns())
    with pytest.raises(HAUnreachable, match="nom d'hôte introuvable"):
        await call_light(client)


async def test_timeout_mentions_the_configured_delay(ha):
    ha.delay_s = 1.0
    client = HttpHAClient(ha.url, TOKEN, timeout_s=0.2)
    try:
        started = time.monotonic()
        with pytest.raises(HATimeout, match=r"0\.2 s"):
            await call_light(client)
        assert time.monotonic() - started < 0.8  # n'a pas attendu la réponse de 1 s
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("status", "error", "fragment"),
    [
        (401, HAAuthError, "jeton refusé"),
        (403, HAAuthError, "jeton refusé"),
        (404, HANotFound, "introuvable"),
        (400, HABadRequest, "refusée"),
        (422, HABadRequest, "refusée"),
        (500, HAServerError, "erreur interne"),
        (503, HAServerError, "erreur interne"),
    ],
)
async def test_http_statuses_map_to_distinct_errors(ha, status, error, fragment):
    ha.overrides[("POST", "/api/services/light/turn_off")] = (status, {"message": "x"})
    client = HttpHAClient(ha.url, TOKEN)
    try:
        with pytest.raises(error, match=fragment) as exc:
            await call_light(client)
        assert type(exc.value) is error  # ni plus générale, ni confondue avec une autre
    finally:
        await client.close()


async def test_unexpected_status_is_a_generic_ha_error(ha):
    ha.overrides[("POST", "/api/services/light/turn_off")] = (418, {})
    client = HttpHAClient(ha.url, TOKEN)
    try:
        with pytest.raises(HAError, match="418") as exc:
            await call_light(client)
        assert type(exc.value) is HAError
    finally:
        await client.close()


async def test_wrong_token_is_refused_and_never_echoed(ha):
    client = HttpHAClient(ha.url, "mauvais-jeton-secret")
    try:
        with pytest.raises(HAAuthError) as exc:
            await client.check_connection()
        assert "mauvais-jeton-secret" not in str(exc.value)
    finally:
        await client.close()


async def test_all_specific_errors_are_ha_errors():
    for cls in (HAUnreachable, HATimeout, HAAuthError, HANotFound, HABadRequest, HAServerError):
        assert issubclass(cls, HAError)


# ------------------------------------------------------------------ coupe-circuit


async def test_after_a_network_failure_scenario_calls_fail_fast_then_recover(ha):
    now = [100.0]
    ha.delay_s = 0.4
    client = HttpHAClient(ha.url, TOKEN, timeout_s=0.1, cooldown_s=10, clock=lambda: now[0])
    try:
        with pytest.raises(HATimeout):
            await call_light(client)
        sent = len(ha.requests)
        started = time.monotonic()
        with pytest.raises(HAUnreachable, match="nouvel essai dans 10 s"):
            await call_light(client)
        assert time.monotonic() - started < 0.05 and len(ha.requests) == sent  # rien n'est envoyé
        now[0] += 11
        ha.delay_s = 0
        await call_light(client)  # le délai de pause est écoulé : on réessaie et ça passe
        await call_light(client)
    finally:
        await client.close()


async def test_explicit_calls_ignore_the_pause_and_reset_it(ha):
    now = [0.0]
    ha.delay_s = 0.3
    client = HttpHAClient(ha.url, TOKEN, timeout_s=0.1, cooldown_s=60, clock=lambda: now[0])
    try:
        with pytest.raises(HATimeout):
            await call_light(client)
        ha.delay_s = 0
        assert await client.check_connection() == "API running."  # test explicite : toujours tenté
        await call_light(client)  # et la réussite a levé la pause
    finally:
        await client.close()


async def test_http_errors_do_not_pause_the_client(ha):
    ha.overrides[("POST", "/api/services/light/turn_off")] = (500, {})
    client = HttpHAClient(ha.url, TOKEN, cooldown_s=60)
    try:
        for _ in range(3):
            with pytest.raises(HAServerError):
                await call_light(client)
        assert len(ha.posts()) == 3  # chaque appel est bien parti
    finally:
        await client.close()


# ------------------------------------------------------------------ dans un run réel


def config() -> AppConfig:
    return AppConfig.model_validate(
        json.loads((ROOT / "deploy" / "config.example.json").read_text(encoding="utf-8"))
    )


def program(*children: dict, id_="p", **kw) -> Program:
    root = {"id": "n", "type": "sequence", "children": list(children)}
    return Program.model_validate(
        {"id": id_, "name": id_, "scripts": [{"id": "s", "root": root}], "on_end": "keep", **kw}
    )


def light(id_, **kw):
    return {"id": id_, "type": "light", "target": "bandeau", "state": "on", **kw}


async def run_with(client: HttpHAClient, prog: Program):
    cfg = config()
    relays = FakeRelayDriver.from_config(cfg)
    manager = RunManager(
        cfg, relays, client, FakeButtonDriver(["bouton_principal"]), {prog.id: prog}
    )
    started = time.monotonic()
    run = await manager.start(prog)
    await run.done.wait()
    elapsed = time.monotonic() - started
    on = {
        r.id: relays.is_on(r.id) for r in cfg.relays
    }  # avant que l'arrêt ne remette tout au repos
    await manager.shutdown()
    return run, on, elapsed


async def test_run_continues_and_relays_stay_controlled_when_home_assistant_is_down():
    stream = io.StringIO()
    setup_logging("INFO", stream)
    client = HttpHAClient(f"http://127.0.0.1:{free_port()}", TOKEN, timeout_s=1)
    prog = program(
        light("a"),
        {"id": "r", "type": "relay", "target": "fantome", "state": "on"},
        {"id": "w", "type": "wait", "seconds": 0.05},
        {"id": "r2", "type": "relay", "target": "orage", "state": "on"},
    )
    try:
        run, on, _ = await run_with(client, prog)
    finally:
        await client.close()
        setup_logging()
    assert run.outcome == "completed"
    assert on["fantome"] and on["orage"]
    errors = [
        json.loads(line) for line in stream.getvalue().splitlines() if "action en échec" in line
    ]
    assert errors and errors[0]["error_type"] == "HAUnreachable" and errors[0]["node_id"] == "a"
    assert errors[0]["run_id"] == run.id  # l'erreur est rattachée au run et au bloc


async def test_on_error_abort_stops_the_run_with_the_ha_message():
    client = HttpHAClient(f"http://127.0.0.1:{free_port()}", TOKEN, timeout_s=1)
    prog = program(
        light("a", on_error="abort"),
        {"id": "r", "type": "relay", "target": "fantome", "state": "on"},
    )
    try:
        run, on, _ = await run_with(client, prog)
    finally:
        await client.close()
    assert run.outcome == "failed" and "injoignable" in run.error
    assert not on["fantome"]


async def test_slow_home_assistant_does_not_delay_every_block(ha):
    ha.delay_s = 0.5
    client = HttpHAClient(ha.url, TOKEN, timeout_s=0.1)
    prog = program(light("a"), light("b"), light("c"))
    try:
        run, _, elapsed = await run_with(client, prog)
    finally:
        await client.close()
    assert run.outcome == "completed"
    assert len(ha.posts()) == 1  # le premier a expiré, les deux suivants ont été court-circuités
    assert elapsed < 0.45  # sans coupe-circuit : 3 × 0,1 s d'attente plus le temps de réponse


async def test_fire_and_forget_does_not_wait_for_a_slow_home_assistant(ha):
    ha.delay_s = 1.0
    client = HttpHAClient(ha.url, TOKEN, timeout_s=3)
    prog = program(light("a", fire_and_forget=True), {"id": "w", "type": "wait", "seconds": 0.05})
    try:
        run, _, elapsed = await run_with(client, prog)
    finally:
        await client.close()
    assert run.outcome == "completed" and elapsed < 0.5
    await asyncio.sleep(0)
