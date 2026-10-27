import asyncio
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from halloween.app import Engine, StartupError
from halloween.backend import Backend
from halloween.cli import main
from halloween.config import AppConfig
from halloween.drivers import (
    FakeButtonDriver,
    FakeHAClient,
    FakeRelayDriver,
    HAUnreachable,
    Recorder,
)
from halloween.program import Program
from halloween.program.virtual import run_virtual
from halloween.store import Store

ROOT = Path(__file__).resolve().parents[2]
PARIS = ZoneInfo("Europe/Paris")


class OrderedButtons(FakeButtonDriver):
    """Note à quel moment la surveillance des boutons démarre (par rapport au reste)."""

    def __init__(self, ids, journal):
        super().__init__(ids)
        self.journal = journal

    async def start(self):
        self.journal.append("boutons démarrés")


class Setup:
    """Un Pi simulé : pilotes fictifs, dossier de données conservé entre les « redémarrages »."""

    def __init__(self, tmp_path: Path, config_patch=None):
        raw = json.loads((ROOT / "deploy" / "config.example.json").read_text(encoding="utf-8"))
        raw.update(config_patch or {})
        self.store = Store(tmp_path / "data")
        self.store.initialize()
        self.store.save_config(AppConfig.model_validate(raw))
        self.journal: list[str] = []
        self.initial_on: set[str] = (
            set()
        )  # relais « collés » au démarrage (broche flottante, crash)
        self.relays: FakeRelayDriver | None = None
        self.ha: FakeHAClient | None = None
        self.buttons: OrderedButtons | None = None
        self.messages: list[str] = []

    def backend(self) -> Backend:
        def relays(config):
            self.relays = FakeRelayDriver.from_config(config)
            for relay_id in self.initial_on:
                self.relays._state[relay_id] = True
            return self.relays

        def buttons(config):
            self.buttons = OrderedButtons((b.id for b in config.buttons), self.journal)
            return self.buttons

        def ha(_config, _write, _dry):
            recorder = Recorder()
            self.ha = FakeHAClient(recorder)
            original = self.ha.call_service

            async def journaled(domain, service, data):
                self.journal.append(f"HA {domain}/{service}")
                await original(domain, service, data)

            self.ha.call_service = journaled
            return self.ha

        return Backend(relays, buttons, ha)

    def engine(self, clock=None) -> Engine:
        return Engine(self.store, self.backend(), self.messages.append, clock=clock)

    def program(self, id_, *children, **kw) -> Program:
        root = {"id": "n", "type": "sequence", "children": list(children)}
        prog = Program.model_validate(
            {"id": id_, "name": id_, "scripts": [{"id": "s", "root": root}], **kw}
        )
        self.store.save_program(prog)
        return prog

    def triggers(self, *items: dict) -> None:
        self.store.save_triggers(list(items))


def relay(id_, target, state="on"):
    return {"id": id_, "type": "relay", "target": target, "state": state}


def wait(id_, seconds):
    return {"id": id_, "type": "wait", "seconds": seconds}


def button_trigger(id_, event, **kw):
    return {"id": id_, "source": "button", "button": "bouton_principal", "event": event, **kw}


# ------------------------------------------------------------------ démarrage


def test_start_puts_everything_at_rest_before_anything_can_trigger(tmp_path):
    setup = Setup(tmp_path)
    setup.initial_on = {"fantome", "orage"}  # collés au moment du redémarrage

    async def main():
        engine = setup.engine()
        report = await engine.start()
        assert not any(
            setup.relays.is_on(r) for r in ("fantome", "squelette", "epouvantail", "orage")
        )
        assert report.issues == [] and report.rest_pending == []
        await engine.stop()

    run_virtual(main)
    # le repos (bandeau, guirlande) est appliqué AVANT l'activation des boutons
    first_buttons = setup.journal.index("boutons démarrés")
    assert setup.journal[:first_buttons] == ["HA light/turn_on", "HA light/turn_on"]


def test_invalid_config_refuses_to_start(tmp_path):
    setup = Setup(tmp_path)
    setup.store.config_path.write_text("{pas du json", encoding="utf-8")

    async def main():
        with pytest.raises(StartupError, match="invalide"):
            await setup.engine().start()

    run_virtual(main)
    assert setup.relays is None  # aucun pilote créé


def test_duplicate_pins_refuse_to_start(tmp_path):
    setup = Setup(tmp_path)
    raw = json.loads(setup.store.config_path.read_text(encoding="utf-8"))
    raw["buttons"][0]["pin"] = 18
    setup.store.config_path.write_text(json.dumps(raw), encoding="utf-8")

    async def main():
        with pytest.raises(StartupError, match="GPIO 18"):
            await setup.engine().start()

    run_virtual(main)


def test_missing_config_refuses_to_start(tmp_path):
    setup = Setup(tmp_path)
    setup.store.config_path.unlink()

    async def main():
        with pytest.raises(StartupError, match="aucune configuration"):
            await setup.engine().start()

    run_virtual(main)


def test_invalid_programs_and_triggers_are_set_aside_the_rest_works(tmp_path):
    setup = Setup(tmp_path)
    setup.program("bon", relay("a", "fantome"), wait("w", 5))
    setup.program("mauvais", relay("a", "composant-inconnu"))
    (setup.store.programs_dir / "casse.json").write_text("{", encoding="utf-8")
    setup.triggers(
        button_trigger("ok", "short", program="bon"),
        button_trigger("vers-mauvais", "double", program="mauvais"),
        button_trigger("bouton-inconnu", "long", program="bon", button="nope"),
        {"id": "illisible", "source": "wifi"},
    )

    async def main():
        engine = setup.engine()
        report = await engine.start()
        assert report.programs == 1 and set(engine.programs) == {"bon"}
        assert report.triggers == 1 and [t.id for t in engine.triggers.triggers] == ["ok"]
        messages = " | ".join(i.message for i in report.issues)
        assert "mauvais" in messages and "composant-inconnu" in messages
        assert "casse.json" in messages and "bouton inconnu" in messages and "n°4" in messages
        await engine.stop()

    run_virtual(main)


def test_failure_while_starting_releases_what_was_acquired(tmp_path):
    setup = Setup(tmp_path)
    closed = []

    async def main():
        backend = setup.backend()
        original_buttons = backend.buttons

        def buttons(config):
            driver = original_buttons(config)

            async def broken_start():
                raise OSError("broche déjà prise")

            async def close():
                closed.append("boutons")

            driver.start = broken_start
            driver.close = close
            return driver

        backend.buttons = buttons
        engine = Engine(setup.store, backend, setup.messages.append)
        with pytest.raises(OSError, match="déjà prise"):
            await engine.start()
        assert closed == ["boutons"] and not setup.relays.is_on("fantome")

    run_virtual(main)


# ------------------------------------------------------------------ fonctionnement


def test_triggers_work_after_start_and_stop_after_stop(tmp_path):
    setup = Setup(tmp_path)
    setup.program("bon", relay("a", "fantome"), wait("w", 50))
    setup.triggers(
        button_trigger("go", "short", program="bon"), button_trigger("halt", "long", action="stop")
    )

    async def main():
        engine = setup.engine()
        await engine.start()
        await setup.buttons.press("bouton_principal", "short")
        await asyncio.sleep(0.01)
        assert setup.relays.is_on("fantome")
        await setup.buttons.press("bouton_principal", "long")
        await asyncio.sleep(0.01)
        assert not setup.relays.is_on("fantome") and engine.manager.active == []
        await engine.stop()
        await setup.buttons.press("bouton_principal", "short")
        await asyncio.sleep(0.01)
        assert not setup.relays.is_on("fantome")  # plus aucune réaction

    run_virtual(main)


def test_scheduled_trigger_works_after_start(tmp_path):
    setup = Setup(tmp_path)
    setup.program("ambiance", relay("a", "orage"), wait("w", 5))
    setup.triggers(
        {"id": "soir", "source": "schedule", "cron": "0 18 31 10 *", "program": "ambiance"}
    )

    async def main():
        loop = asyncio.get_running_loop()
        start = datetime(2026, 10, 31, 17, 59, 0, tzinfo=PARIS)

        def clock():
            return (start.astimezone(UTC) + timedelta(seconds=loop.time())).astimezone(PARIS)

        engine = setup.engine(clock=clock)
        await engine.start()
        await asyncio.sleep(62)  # 18:00:02 : le programme (5 s) est en cours
        assert setup.relays.is_on("orage")
        await engine.stop()

    run_virtual(main)


def test_stop_leaves_everything_off_and_releases_the_drivers(tmp_path):
    setup = Setup(tmp_path)
    setup.program("bon", relay("a", "fantome"), wait("w", 50), on_end="keep")

    async def main():
        engine = setup.engine()
        await engine.start()
        await engine.manager.start(engine.programs["bon"])
        await asyncio.sleep(1)
        assert setup.relays.is_on("fantome")
        await engine.stop()
        assert not setup.relays.is_on("fantome")

    run_virtual(main)


# ------------------------------------------------------------------ redémarrage du Pi


def test_pi_restart_after_a_crash_everything_is_at_rest_and_triggers_work(tmp_path):
    """Critère de l'issue : après un plantage, tout est au repos et les déclencheurs marchent."""
    setup = Setup(tmp_path)
    setup.program("bon", relay("a", "squelette"), wait("w", 50))
    setup.triggers(button_trigger("go", "short", program="bon"))

    async def before_crash():
        engine = setup.engine()
        await engine.start()
        await setup.buttons.press("bouton_principal", "short")
        await asyncio.sleep(1)
        assert setup.relays.is_on("squelette")  # le scénario est en cours...
        # ... et le Pi plante : aucun arrêt propre, rien n'est éteint

    run_virtual(before_crash)

    setup.journal.clear()
    setup.initial_on = {"squelette", "fantome"}  # les relais sont restés collés (ou flottent)

    async def after_reboot():
        engine = setup.engine()
        report = await engine.start()
        assert report.programs == 1 and report.triggers == 1
        assert not setup.relays.is_on("squelette") and not setup.relays.is_on("fantome")
        assert engine.manager.active == []  # aucun scénario fantôme
        await setup.buttons.press("bouton_principal", "short")  # les déclencheurs fonctionnent
        await asyncio.sleep(0.01)
        assert setup.relays.is_on("squelette")
        await engine.stop()

    run_virtual(after_reboot)


# ------------------------------------------------------------------ Home Assistant pas encore prêt


def test_rest_state_is_retried_when_home_assistant_is_not_ready_at_boot(tmp_path):
    setup = Setup(tmp_path)

    async def main():
        engine = setup.engine()
        # Home Assistant démarre après le Pi : les premiers appels échouent
        original = setup.backend

        def backend():
            b = original()
            ha_factory = b.ha

            def ha(config, write, dry):
                client = ha_factory(config, write, dry)
                client.fail_with = HAUnreachable("pas prêt")
                setup.late_ha = client
                return client

            b.ha = ha
            return b

        engine = Engine(setup.store, backend(), setup.messages.append)
        report = await engine.start()
        assert sorted(report.rest_pending) == ["bandeau", "guirlande"]
        assert setup.ha.calls == []
        await asyncio.sleep(20)  # Home Assistant est toujours absent
        assert setup.ha.calls == []
        setup.ha.fail_with = None  # il vient de démarrer
        await asyncio.sleep(40)
        assert len(setup.ha.calls) == 2  # repos appliqué par la tâche de reprise
        await engine.stop()

    run_virtual(main)


def test_retry_never_overrides_a_light_taken_by_a_program(tmp_path):
    setup = Setup(tmp_path)
    setup.program(
        "show",
        {"id": "l", "type": "light", "target": "bandeau", "state": "on", "rgb_color": [255, 0, 0]},
        wait("w", 500),
        on_end="keep",
    )

    async def main():
        original = setup.backend()
        ha_factory = original.ha

        def ha(config, write, dry):
            client = ha_factory(config, write, dry)
            client.fail_with = HAUnreachable("pas prêt")
            return client

        original.ha = ha
        engine = Engine(setup.store, original, setup.messages.append)
        await engine.start()
        run = await engine.manager.start(engine.programs["show"])
        await asyncio.sleep(1)
        setup.ha.fail_with = None
        await asyncio.sleep(60)
        entities = [c[2]["entity_id"] for c in setup.ha.calls]
        # la guirlande est remise au repos, mais pas le bandeau, repris par le programme
        assert "light.twinkly_halloween" in entities
        assert "light.bandeau_hue" not in entities
        assert run.state == "running"
        await engine.stop()

    run_virtual(main)


def test_retry_gives_up_after_the_window(tmp_path):
    setup = Setup(tmp_path)

    async def main():
        original = setup.backend()
        ha_factory = original.ha

        def ha(config, write, dry):
            client = ha_factory(config, write, dry)
            client.fail_with = HAUnreachable("toujours absent")
            return client

        original.ha = ha
        engine = Engine(setup.store, original, setup.messages.append)
        await engine.start()
        await asyncio.sleep(700)
        assert engine._retry.done() and setup.ha.calls == []
        await engine.stop()

    run_virtual(main)


# ------------------------------------------------------------------ commande serve


def test_cli_serve_reports_and_stops_cleanly_on_sigterm(tmp_path):
    import os
    import signal
    import threading

    setup = Setup(tmp_path)
    setup.program("bon", relay("a", "fantome"), wait("w", 5))
    setup.triggers(
        button_trigger("go", "short", program="bon"), button_trigger("bad", "long", program="nope")
    )
    out = io.StringIO()
    timer = threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM))
    timer.start()
    try:
        code = main(["--data-dir", str(setup.store.root), "serve"], setup.backend(), out)
    finally:
        timer.cancel()
    text = out.getvalue()
    assert code == 130
    assert "Moteur prêt : 1 programme(s), 1 déclencheur(s)" in text
    assert "ÉCARTÉ" in text and "nope" in text
    assert "Moteur arrêté, relais éteints." in text
    assert not setup.relays.is_on("fantome")


def test_cli_serve_refuses_an_invalid_configuration(tmp_path, capsys):
    setup = Setup(tmp_path)
    setup.store.config_path.write_text("{", encoding="utf-8")
    code = main(["--data-dir", str(setup.store.root), "serve"], setup.backend(), io.StringIO())
    assert code == 2 and "invalide" in capsys.readouterr().err
