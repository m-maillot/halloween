"""Ligne de commande `halloween-cli` : essais du matériel et exécution d'un programme.

    halloween-cli relay list
    halloween-cli relay fantome on [--for 5]      # allumé jusqu'à Ctrl+C ou 5 s
    halloween-cli relay fantome off
    halloween-cli relay fantome trigger           # impulsion
    halloween-cli button watch                    # affiche les appuis
    halloween-cli gpio-check [--active]           # compatibilité GPIO du Pi utilisé
    halloween-cli serve                           # moteur en continu : reprise, boutons, planning
    halloween-cli api [--port 8080]               # moteur + API HTTP + interface (service complet)
    halloween-cli ha-check [--active]             # Home Assistant : connexion, entités, capacités
    halloween-cli simulate scenario-principal     # timeline sans rien actionner
    halloween-cli run scenario-principal          # exécution réelle [--ha-dry-run]

Le dossier de données (config.json, programs/) vient de `--data-dir`, de `HALLOWEEN_DATA_DIR` ou
de `/var/lib/halloween`. Codes de sortie : 0 succès, 1 run en échec, 2 erreur d'usage ou de
configuration, 3 matériel inutilisable, 130 interruption (Ctrl+C).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TextIO

from pydantic import ValidationError

from halloween.backend import Backend, gpio_backend
from halloween.config.models import AppConfig
from halloween.config.validation import validate_config
from halloween.drivers.base import ButtonDriver, ButtonEvent, RelayDriver
from halloween.drivers.homeassistant import TOKEN_ENV, HttpHAClient
from halloween.issues import errors, warnings
from halloween.log import setup_logging
from halloween.program.models import Program
from halloween.program.runs import RunManager
from halloween.program.simulation import simulate
from halloween.program.validation import validate_program
from halloween.store import Store

DEFAULT_DATA_DIR = "/var/lib/halloween"

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_HARDWARE, EXIT_INTERRUPTED = 0, 1, 2, 3, 130


class CliError(Exception):
    def __init__(self, message: str, code: int = EXIT_USAGE) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- analyse des arguments


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="halloween-cli", description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("HALLOWEEN_DATA_DIR", DEFAULT_DATA_DIR),
        help="dossier de données (config.json, programs/) [%(default)s]",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="journal JSON détaillé")
    sub = parser.add_subparsers(dest="command", required=True)

    relay = sub.add_parser("relay", help="piloter un relais")
    relay.add_argument("target", help="`list` ou l'id d'un relais")
    relay.add_argument("action", nargs="?", choices=["on", "off", "trigger"])
    relay.add_argument("--for", dest="seconds", type=float, help="durée en secondes (on)")

    button = sub.add_parser("button", help="surveiller les boutons")
    button.add_argument("action", choices=["watch"])
    button.add_argument("--for", dest="seconds", type=float, help="s'arrêter après N secondes")

    check = sub.add_parser("gpio-check", help="vérifier la compatibilité GPIO du Raspberry Pi")
    check.add_argument(
        "--active",
        action="store_true",
        help="fait basculer chaque relais (ils vont cliquer : débrancher les charges) "
        "et attend un appui sur chaque bouton",
    )
    check.add_argument("--press-timeout", type=float, default=10.0, help="attente d'un appui (s)")

    serve = sub.add_parser("serve", help="lancer le moteur (boutons, planning) en continu")
    serve.add_argument("--ha-dry-run", action="store_true", help="n'envoie rien à Home Assistant")

    api = sub.add_parser("api", help="moteur + API HTTP + interface (le service complet)")
    api.add_argument("--host", default="0.0.0.0", help="adresse d'écoute [%(default)s]")
    api.add_argument("--port", type=int, default=8080, help="port [%(default)s]")
    api.add_argument(
        "--ui-dir",
        default=os.environ.get("HALLOWEEN_UI_DIR"),
        help="dossier du build de l'interface (HALLOWEEN_UI_DIR)",
    )
    api.add_argument("--ha-dry-run", action="store_true", help="n'envoie rien à Home Assistant")

    ha_check = sub.add_parser(
        "ha-check", help="vérifier Home Assistant et les capacités des lumières"
    )
    ha_check.add_argument(
        "--active",
        action="store_true",
        help="pilote les lumières (couleur, luminosité, transition), mesure la latence, "
        "puis restaure leur état",
    )
    ha_check.add_argument("--pause", type=float, default=1.0, help="pause entre deux essais (s)")

    for name, text in (("run", "exécuter un programme"), ("simulate", "simuler un programme")):
        p = sub.add_parser(name, help=text)
        p.add_argument("program_id")
        if name == "run":
            p.add_argument(
                "--ha-dry-run",
                action="store_true",
                help="n'envoie rien à Home Assistant (affiche seulement les appels)",
            )
    return parser


# --------------------------------------------------------------------------- commandes


def _load(args: argparse.Namespace) -> tuple[Store, AppConfig]:
    store = Store(Path(args.data_dir))
    try:
        config = store.load_config()
    except ValidationError as exc:
        raise CliError(f"config.json invalide :\n{exc}") from exc
    if not store.config_path.exists():
        raise CliError(f"aucune configuration : {store.config_path} n'existe pas")
    problems = errors(validate_config(config))
    if problems:
        raise CliError(
            "configuration invalide :\n" + "\n".join(f"  - {p.message}" for p in problems)
        )
    return store, config


def _make(factory: Callable[..., Any], *args: Any) -> Any:
    try:
        return factory(*args)
    except Exception as exc:
        raise CliError(
            f"matériel inutilisable : {type(exc).__name__}: {exc}", EXIT_HARDWARE
        ) from exc


async def _sleep(seconds: float | None) -> None:
    """Attend `seconds` (ou indéfiniment, jusqu'à l'interruption)."""
    if seconds is None:
        await asyncio.Event().wait()
    else:
        await asyncio.sleep(seconds)


async def cmd_relay(args: argparse.Namespace, backend: Backend, out: TextIO) -> int:
    _, config = _load(args)
    if args.target == "list":
        for relay in config.relays:
            level = "actif bas" if relay.active_low else "actif haut"
            print(
                f"{relay.id:<16} GPIO {relay.pin:<3} {relay.mode.value:<8} {level}  {relay.name}",
                file=out,
            )
        return EXIT_OK
    relay = next((r for r in config.relays if r.id == args.target), None)
    if relay is None or args.action is None:
        known = ", ".join(r.id for r in config.relays)
        if relay is None:
            raise CliError(f"relais inconnu : {args.target} (relais : {known})")
        raise CliError("indiquer on, off ou trigger")

    driver: RelayDriver = _make(backend.relays, config)
    try:
        if args.action == "off":
            await driver.set(relay.id, False)
            print(f"{relay.id} : éteint (GPIO {relay.pin})", file=out)
        elif args.action == "trigger":
            pulse = (relay.pulse_ms or 500) / 1000
            await driver.set(relay.id, True)
            print(f"{relay.id} : impulsion de {pulse:g} s (GPIO {relay.pin})", file=out)
            await asyncio.sleep(pulse)
            await driver.set(relay.id, False)
        else:
            await driver.set(relay.id, True)
            until = (
                "Ctrl+C pour éteindre" if args.seconds is None else f"pendant {args.seconds:g} s"
            )
            print(f"{relay.id} : allumé (GPIO {relay.pin}), {until}", file=out)
            out.flush()
            try:
                await _sleep(args.seconds)
            finally:
                await driver.set(relay.id, False)
                print(f"{relay.id} : éteint", file=out)
    finally:
        await driver.all_off()
        await driver.close()
    return EXIT_OK


async def cmd_gpio_check(args: argparse.Namespace, backend: Backend, out: TextIO) -> int:
    from halloween.gpio_check import run_check

    _, config = _load(args)
    return await run_check(
        config,
        lambda c: _make(backend.relays, c),
        lambda c: _make(backend.buttons, c),
        out,
        active=args.active,
        press_timeout_s=args.press_timeout,
    )


async def cmd_ha_check(args: argparse.Namespace, backend: Backend, out: TextIO) -> int:
    from halloween.ha_check import run_ha_check

    _, config = _load(args)
    if config.home_assistant is None:
        raise CliError('aucune section "home_assistant" dans config.json')
    if not (os.environ.get(TOKEN_ENV) or config.home_assistant.token):
        raise CliError(f"aucun jeton : le renseigner dans config.json ou dans {TOKEN_ENV}")
    client = HttpHAClient.from_config(config.home_assistant)
    try:
        return await run_ha_check(config, client, out, args.active, args.pause)
    finally:
        await client.close()


async def cmd_serve(args: argparse.Namespace, backend: Backend, out: TextIO) -> int:
    """Lance le moteur en continu (reprise, boutons, planning) jusqu'à Ctrl+C / SIGTERM."""
    from halloween.app import Engine, StartupError

    engine = Engine(
        Store(Path(args.data_dir)), backend, lambda line: print(line, file=out), args.ha_dry_run
    )
    try:
        report = await engine.start()
    except StartupError as exc:
        await engine.stop()
        raise CliError(str(exc)) from exc
    try:
        for issue in report.issues:
            tag = "attention" if issue.severity == "warning" else "ÉCARTÉ"
            print(f"  {tag} : {issue.message}", file=out)
        pending = (
            f" ; remise au repos de {', '.join(report.rest_pending)} retentée en arrière-plan"
            if report.rest_pending
            else ""
        )
        counts = f"{report.programs} programme(s), {report.triggers} déclencheur(s)"
        print(f"Moteur prêt : {counts}{pending}.", file=out)
        print("Ctrl+C ou SIGTERM pour arrêter.", file=out)
        out.flush()
        await _sleep(None)
    finally:
        await engine.stop()
        print("Moteur arrêté, relais éteints.", file=out)
    return EXIT_OK


async def cmd_api(args: argparse.Namespace, backend: Backend, out: TextIO) -> int:
    """Le service complet : moteur, API sous /api et interface, jusqu'à Ctrl+C / SIGTERM."""
    from halloween.api import create_app
    from halloween.api.auth import load_or_create_token
    from halloween.api.server import run_server
    from halloween.app import StartupReport

    store = Store(Path(args.data_dir))
    store.initialize()
    try:
        token, origin = load_or_create_token(store.root)
    except ValueError as exc:
        raise CliError(str(exc)) from exc

    def say(line: str) -> None:
        print(line, file=out)
        out.flush()

    def ready(report: StartupReport) -> None:
        for issue in report.issues:
            say(f"  {'attention' if issue.severity == 'warning' else 'ÉCARTÉ'} : {issue.message}")
        say(f"Moteur prêt : {report.programs} programme(s), {report.triggers} déclencheur(s).")
        say(f"API : http://{args.host}:{args.port}/api  (jeton : {origin})")
        say("Ctrl+C ou SIGTERM pour arrêter.")

    ui_dir = Path(args.ui_dir) if args.ui_dir else None
    app = create_app(
        store,
        backend,
        token=token,
        static_dir=ui_dir,
        ha_dry_run=args.ha_dry_run,
        write=say,
        on_ready=ready,
    )
    try:
        await run_server(app, args.host, args.port)
    finally:
        say("Service arrêté, relais éteints.")
    failure = getattr(app.state, "startup_error", None)
    if failure is not None:
        raise CliError(str(failure))
    return EXIT_OK


async def cmd_button_watch(args: argparse.Namespace, backend: Backend, out: TextIO) -> int:
    _, config = _load(args)
    if not config.buttons:
        raise CliError("aucun bouton configuré")
    driver: ButtonDriver = _make(backend.buttons, config)
    started = time.monotonic()

    def show(event: ButtonEvent) -> None:
        print(f"{time.monotonic() - started:7.2f} s  {event.button_id}  {event.event}", file=out)
        out.flush()

    driver.subscribe(show)
    await driver.start()
    ids = ", ".join(f"{b.id} (GPIO {b.pin})" for b in config.buttons)
    print(f"En attente d'appuis sur : {ids}. Ctrl+C pour quitter.", file=out)
    out.flush()
    try:
        await _sleep(args.seconds)
    finally:
        await driver.close()
    return EXIT_OK


def _find_program(
    store: Store, program_id: str, config: AppConfig
) -> tuple[Program, dict[str, Program]]:
    loaded = store.load_programs()
    program = loaded.programs.get(program_id)
    if program is None:
        known = ", ".join(sorted(loaded.programs)) or "aucun"
        broken = "".join(f"\n  ! {i.message}" for i in loaded.issues)
        raise CliError(f"programme inconnu : {program_id} (programmes : {known}){broken}")
    problems = errors(validate_program(program, config, loaded.programs))
    if problems:
        lines = "\n".join(f"  - [{p.node_id or '-'}] {p.message}" for p in problems)
        raise CliError(f"programme invalide :\n{lines}")
    return program, loaded.programs


async def cmd_simulate(args: argparse.Namespace, backend: Backend, out: TextIO) -> int:
    store, config = _load(args)
    program, programs = _find_program(store, args.program_id, config)
    # `simulate` crée sa propre boucle à temps virtuel : hors de la boucle courante.
    result = await asyncio.to_thread(simulate, program, config, programs)
    for entry in result.timeline:
        print(f"{entry.t:8.2f} s  {entry.component:<16} {entry.action}", file=out)
    print(f"-- {result.status}, {result.duration_s:g} s simulées", file=out)
    if result.error:
        print(f"   {result.error}", file=out)
    return EXIT_OK if result.status == "completed" else EXIT_FAILED


async def cmd_run(args: argparse.Namespace, backend: Backend, out: TextIO) -> int:
    store, config = _load(args)
    program, programs = _find_program(store, args.program_id, config)
    for warning in warnings(validate_program(program, config, programs)):
        print(f"  attention [{warning.node_id or '-'}] {warning.message}", file=out)

    relays: RelayDriver = _make(backend.relays, config)
    buttons: ButtonDriver = _make(backend.buttons, config)
    ha = backend.ha(config, lambda line: print(line, file=out), args.ha_dry_run)
    manager = RunManager(config, relays, ha, buttons, programs)
    try:
        await buttons.start()
        await manager.reset_all()
        run = await manager.start(program)
        print(f"{program.id} : démarré (Ctrl+C pour arrêter)", file=out)
        out.flush()
        await run.done.wait()
        duration = (run.ended_at or 0) - (run.started_at or 0)
        print(f"{program.id} : {run.outcome} en {duration:.1f} s", file=out)
        if run.error:
            print(f"  {run.error}", file=out)
        return EXIT_OK if run.outcome == "completed" else EXIT_FAILED
    finally:
        await manager.shutdown()
        await buttons.close()
        await relays.close()
        await ha.close()


COMMANDS: dict[str, Callable[[argparse.Namespace, Backend, TextIO], Awaitable[int]]] = {
    "button": cmd_button_watch,
    "gpio-check": cmd_gpio_check,
    "ha-check": cmd_ha_check,
    "relay": cmd_relay,
    "run": cmd_run,
    "serve": cmd_serve,
    "api": cmd_api,
    "simulate": cmd_simulate,
}


# --------------------------------------------------------------------------- point d'entrée


async def _supervised(coro: Awaitable[int]) -> int:
    """Exécute la commande ; SIGINT / SIGTERM l'annulent (les `finally` éteignent tout)."""
    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(coro)
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, ValueError):
            loop.add_signal_handler(sig, task.cancel)
    try:
        return await task
    except asyncio.CancelledError:
        return EXIT_INTERRUPTED


def main(
    argv: list[str] | None = None, backend: Backend | None = None, out: TextIO | None = None
) -> int:
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    setup_logging("INFO" if args.verbose else "ERROR", sys.stderr)
    backend = backend or gpio_backend()
    try:
        return asyncio.run(_supervised(COMMANDS[args.command](args, backend, out)))
    except CliError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return exc.code


def console() -> None:
    sys.exit(main())


if __name__ == "__main__":
    console()
