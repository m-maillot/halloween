import asyncio
import io
import json
from pathlib import Path

import pytest

from halloween.cli import Backend, main
from halloween.config import AppConfig
from halloween.drivers import FakeButtonDriver, FakeRelayDriver, Recorder
from halloween.drivers.dryrun import DryRunHAClient
from halloween.program import Program
from halloween.store import Store

ROOT = Path(__file__).resolve().parents[2]


class ScriptedButtons(FakeButtonDriver):
    """Simule un appui peu après le démarrage de la surveillance."""

    async def start(self):
        async def later():
            await asyncio.sleep(0.02)
            await self.press("bouton_principal", "long")

        self._task = asyncio.ensure_future(later())


class Env:
    def __init__(self, tmp_path: Path):
        self.data = tmp_path / "data"
        self.rec = Recorder()
        self.relays: FakeRelayDriver | None = None
        self.closed = False
        store = Store(self.data)
        store.initialize()
        raw = json.loads((ROOT / "deploy" / "config.example.json").read_text(encoding="utf-8"))
        raw["relays"].append(
            {"id": "robot", "name": "Robot", "pin": 5, "mode": "push", "pulse_ms": 100}
        )
        self.config = AppConfig.model_validate(raw)
        store.save_config(self.config)
        self.store = store

        def relays(config):
            self.relays = FakeRelayDriver.from_config(config, self.rec)
            return self.relays

        self.backend = Backend(
            relays,
            lambda config: ScriptedButtons(b.id for b in config.buttons),
            lambda _config, write, _dry: DryRunHAClient(write),
        )

    def program(self, id_: str, *children: dict, **kw) -> None:
        root = {"id": "n", "type": "sequence", "children": list(children)}
        self.store.save_program(
            Program.model_validate(
                {"id": id_, "name": id_, "scripts": [{"id": "s", "root": root}], **kw}
            )
        )

    def cli(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        code = main(["--data-dir", str(self.data), *argv], self.backend, out)
        return code, out.getvalue()


@pytest.fixture
def env(tmp_path) -> Env:
    return Env(tmp_path)


def relay(id_, target, state="on"):
    return {"id": id_, "type": "relay", "target": target, "state": state}


def wait(id_, seconds):
    return {"id": id_, "type": "wait", "seconds": seconds}


# ------------------------------------------------------------------ relais


def test_relay_list(env):
    code, out = env.cli("relay", "list")
    assert code == 0
    assert "fantome" in out and "GPIO 18" in out and "latched" in out and "actif haut" in out
    assert "robot" in out and "push" in out


def test_relay_on_for_a_duration_turns_off_afterwards(env):
    code, out = env.cli("relay", "fantome", "on", "--for", "0.05")
    assert code == 0 and "allumé" in out and "éteint" in out
    assert [(c, a) for _, c, a in env.rec.timeline()] == [("fantome", "on"), ("fantome", "off")]
    assert not env.relays.is_on("fantome")


def test_relay_off(env):
    code, out = env.cli("relay", "orage", "off")
    assert code == 0 and "éteint" in out
    assert env.rec.timeline() == [] or env.rec.timeline()[-1][2] == "off"


def test_relay_trigger_pulses_for_pulse_ms(env):
    code, out = env.cli("relay", "robot", "trigger")
    assert code == 0 and "impulsion de 0,1" in out.replace(".", ",")
    assert [(c, a) for _, c, a in env.rec.timeline()] == [("robot", "on"), ("robot", "off")]


def test_unknown_relay_lists_the_known_ones(env, capsys):
    code, _ = env.cli("relay", "nope", "on")
    assert code == 2
    err = capsys.readouterr().err
    assert "relais inconnu" in err and "fantome" in err


def test_relay_without_action(env, capsys):
    code, _ = env.cli("relay", "fantome")
    assert code == 2 and "on, off ou trigger" in capsys.readouterr().err


def test_missing_config_is_a_usage_error(tmp_path, capsys):
    out = io.StringIO()
    code = main(
        ["--data-dir", str(tmp_path / "vide"), "relay", "list"], Backend(None, None, None), out
    )
    assert code == 2 and "aucune configuration" in capsys.readouterr().err


def test_hardware_failure_gives_exit_code_3(env, capsys):
    def broken(_config):
        raise OSError("pas de GPIO ici")

    env.backend.relays = broken
    code, _ = env.cli("relay", "fantome", "on", "--for", "0.01")
    assert code == 3 and "matériel inutilisable" in capsys.readouterr().err


# ------------------------------------------------------------------ boutons


def test_button_watch_prints_events(env):
    code, out = env.cli("button", "watch", "--for", "0.2")
    assert code == 0
    assert "bouton_principal" in out and "long" in out and "Ctrl+C" in out


# ------------------------------------------------------------------ run et simulate


def test_simulate_prints_the_timeline(env):
    env.program("demo", relay("a", "fantome"), wait("w", 3), relay("b", "fantome", "off"))
    code, out = env.cli("simulate", "demo")
    assert code == 0
    assert "fantome" in out and "3.00 s" in out and "completed" in out
    assert env.relays is None  # rien n'a été actionné


def test_run_executes_the_program_and_returns_to_rest(env):
    env.program("demo", relay("a", "fantome"), wait("w", 0.05), relay("b", "orage"))
    code, out = env.cli("run", "demo")
    assert code == 0 and "completed" in out
    # le repos (bandeau, guirlande) est appliqué au démarrage et à la fin, via le client simulé
    assert "[Home Assistant simulé] light/turn_on" in out and "light.bandeau_hue" in out
    assert not env.relays.is_on("fantome") and not env.relays.is_on("orage")
    assert [c for _, c, a in env.rec.timeline() if a == "on"] == ["fantome", "orage"]


def test_run_unknown_program(env, capsys):
    env.program("demo", wait("w", 1))
    code, _ = env.cli("run", "nope")
    assert code == 2 and "programme inconnu" in capsys.readouterr().err


def test_run_refuses_an_invalid_program_with_the_faulty_block(env, capsys):
    env.program("bad", relay("a", "inconnu"))
    code, _ = env.cli("run", "bad")
    err = capsys.readouterr().err
    assert code == 2 and "[a]" in err and "inconnu" in err
    assert env.relays is None  # aucun matériel touché


def test_run_reports_failed_outcome_with_exit_code_1(env):
    env.program(
        "boom",
        {"id": "x", "type": "light", "target": "bandeau", "state": "on", "on_error": "abort"},
    )

    class Broken(DryRunHAClient):
        async def call_service(self, domain, service, data):
            if (
                data.get("entity_id") == "light.bandeau_hue"
                and service == "turn_on"
                and data.get("rgb_color") is None
            ):
                raise RuntimeError("HA HS")
            await super().call_service(domain, service, data)

    env.backend.ha = lambda _config, write, _dry: Broken(write)
    code, out = env.cli("run", "boom")
    assert code == 1 and "failed" in out


def test_interruption_stops_the_run_and_turns_everything_off(env):
    env.program("long", relay("a", "fantome"), wait("w", 60))
    import os
    import signal
    import threading

    timer = threading.Timer(0.3, lambda: os.kill(os.getpid(), signal.SIGINT))
    timer.start()
    try:
        code, out = env.cli("run", "long")
    finally:
        timer.cancel()
    assert code == 130
    assert not env.relays.is_on("fantome")


# ------------------------------------------------------------------ unlock --reset


def test_unlock_without_reset_is_a_usage_error(env, capsys):
    assert env.cli("unlock")[0] == 2
    assert "--reset" in capsys.readouterr().err


def test_unlock_reset_removes_code_and_unlocks(env):
    from halloween.lock import LockState

    lock = LockState.in_dir(env.data)
    lock.set_code("1234")
    lock.lock()
    code, out = env.cli("unlock", "--reset")
    assert code == 0 and "déverrouillé" in out
    assert not lock.locked and not lock.has_code and not (env.data / "lock.json").exists()


def test_unlock_reset_without_code_is_harmless(env):
    code, out = env.cli("unlock", "--reset")
    assert code == 0 and "Aucun code" in out


def test_unlock_reset_recovers_an_unreadable_lock_file(env):
    from halloween.lock import LockState

    (env.data / "lock.json").write_text("abîmé")
    assert LockState.in_dir(env.data).locked  # échec fermé
    assert env.cli("unlock", "--reset")[0] == 0
    assert not LockState.in_dir(env.data).locked
