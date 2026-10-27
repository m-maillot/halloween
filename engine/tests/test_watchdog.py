"""Signal de vie vers systemd : prêt, battements, arrêt, et détection d'une boucle gelée."""

from __future__ import annotations

import asyncio
import io
import os
import signal
import socket
import threading
import time

import pytest

from api_helpers import Pi
from halloween.cli import main
from halloween.watchdog import Watchdog, notify, watchdog_interval


class FakeSystemd:
    """Le socket sur lequel systemd reçoit les messages `sd_notify`."""

    def __init__(self, path):
        self.path = str(path)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.bind(self.path)
        self.sock.setblocking(False)

    def env(self, watchdog_usec: int | None = None) -> dict[str, str]:
        env = {"NOTIFY_SOCKET": self.path}
        if watchdog_usec is not None:
            env["WATCHDOG_USEC"] = str(watchdog_usec)
        return env

    def drain(self) -> list[str]:
        messages = []
        while True:
            try:
                messages.append(self.sock.recv(1024).decode())
            except BlockingIOError:
                return messages

    def close(self):
        self.sock.close()


@pytest.fixture
def systemd(tmp_path):
    fake = FakeSystemd(tmp_path / "notify.sock")
    yield fake
    fake.close()


def test_notify_is_inactive_outside_systemd():
    assert notify("READY=1", {}) is False
    assert watchdog_interval({}) is None


def test_notify_reaches_the_socket(systemd):
    assert notify("READY=1", systemd.env()) is True
    assert systemd.drain() == ["READY=1"]


def test_notify_to_a_dead_socket_is_harmless(tmp_path):
    assert notify("READY=1", {"NOTIFY_SOCKET": str(tmp_path / "absent.sock")}) is False


def test_interval_is_half_the_systemd_timeout():
    assert watchdog_interval({"WATCHDOG_USEC": "20000000"}) == 10.0
    assert watchdog_interval({"WATCHDOG_USEC": "0"}) is None
    assert watchdog_interval({"WATCHDOG_USEC": "abc"}) is None
    # Une variable destinée à un autre processus est ignorée.
    assert watchdog_interval({"WATCHDOG_USEC": "1000000", "WATCHDOG_PID": "1"}) is None
    mine = {"WATCHDOG_USEC": "1000000", "WATCHDOG_PID": str(os.getpid())}
    assert watchdog_interval(mine) == 0.5


async def test_ready_then_heartbeats_then_stopping(systemd):
    watchdog = Watchdog(systemd.env(watchdog_usec=100_000))  # signal de vie toutes les 50 ms
    watchdog.ready("2 programmes")
    await asyncio.sleep(0.25)
    await watchdog.stop()
    messages = systemd.drain()
    assert messages[0] == "READY=1\nSTATUS=2 programmes"
    assert messages.count("WATCHDOG=1") >= 3
    assert messages[-1] == "STOPPING=1"
    await asyncio.sleep(0.15)
    assert systemd.drain() == []  # plus aucun signal de vie après l'arrêt


async def test_without_watchdog_only_ready_is_sent(systemd):
    watchdog = Watchdog(systemd.env())
    watchdog.ready()
    await asyncio.sleep(0.05)
    await watchdog.stop()
    assert systemd.drain() == ["READY=1", "STOPPING=1"]


async def test_a_frozen_event_loop_stops_the_heartbeat(systemd):
    """Gel simulé : systemd (WatchdogSec = 0,2 s ici) ne reçoit plus rien et tuerait le service."""
    watchdog = Watchdog(systemd.env(watchdog_usec=200_000))  # battement toutes les 100 ms
    watchdog.ready()
    await asyncio.sleep(0.35)
    assert systemd.drain().count("WATCHDOG=1") >= 2  # vivant : des signaux arrivent

    # Code bloquant dans la boucle : plus rien ne s'exécute, pas même le battement.
    time.sleep(0.6)  # noqa: ASYNC251
    # Rien n'a été envoyé pendant ces 0,6 s (> WatchdogSec) : systemd déclarerait le gel.
    assert "WATCHDOG=1" not in systemd.drain()

    # Témoin : une fois la boucle libérée, les battements reprennent (c'est donc bien le gel
    # de la boucle, et non un émetteur cassé, qui a provoqué le silence).
    await asyncio.sleep(0.25)
    assert systemd.drain().count("WATCHDOG=1") >= 1
    await watchdog.stop()


def test_cli_api_announces_ready_beats_and_stopping(tmp_path, systemd, monkeypatch):
    pi = Pi(tmp_path)
    for key, value in systemd.env(watchdog_usec=200_000).items():
        monkeypatch.setenv(key, value)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    seen: list[str] = []

    def systemd_side():
        deadline = time.time() + 10
        while time.time() < deadline and seen.count("WATCHDOG=1") < 3:
            seen.extend(systemd.drain())
            time.sleep(0.02)
        os.kill(os.getpid(), signal.SIGTERM)

    thread = threading.Thread(target=systemd_side, daemon=True)
    thread.start()
    code = main(
        ["--data-dir", str(pi.store.root), "api", "--port", str(port), "--host", "127.0.0.1"],
        pi.backend(),
        io.StringIO(),
    )
    thread.join(timeout=5)
    seen.extend(systemd.drain())
    assert code == 130
    assert seen[0].startswith("READY=1")
    assert seen.count("WATCHDOG=1") >= 3
    assert seen[-1] == "STOPPING=1"
