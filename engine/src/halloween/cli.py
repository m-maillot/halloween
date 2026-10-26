"""Ligne de commande `halloween-cli` : essais du matériel et exécution d'un programme.

    halloween-cli relay list
    halloween-cli relay fantome on [--for 5]      # allumé jusqu'à Ctrl+C ou 5 s
    halloween-cli relay fantome off
    halloween-cli relay fantome trigger           # impulsion
    halloween-cli button watch                    # affiche les appuis
    halloween-cli simulate scenario-principal     # timeline sans rien actionner
    halloween-cli run scenario-principal          # exécution réelle (Home Assistant simulé)

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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from pydantic import ValidationError

from halloween.config.models import AppConfig
from halloween.config.validation import validate_config
from halloween.drivers.base import ButtonDriver, ButtonEvent, HAClient, RelayDriver
from halloween.drivers.dryrun import DryRunHAClient
from halloween.issues import errors, warnings
from halloween.log import setup_logging
from halloween.program.models import Program
from halloween.program.runs import RunManager
from halloween.program.simulation import simulate
from halloween.program.validation import validate_program
from halloween.store import Store

DEFAULT_DATA_DIR = "/var/lib/halloween"

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_HARDWARE, EXIT_INTERRUPTED = 0, 1, 2, 3, 130


@dataclass
class Backend:
    """Fabriques de pilotes : GPIO réels par défaut, pilotes fictifs dans les tests."""

    relays: Callable[[AppConfig], RelayDriver]
    buttons: Callable[[AppConfig], ButtonDriver]
    ha: Callable[[AppConfig, Callable[[str], None]], HAClient]


def gpio_backend() -> Backend:
    def relays(config: AppConfig) -> RelayDriver:
        from halloween.drivers.gpio import GpioRelayDriver

        return GpioRelayDriver(config.relays)

    def buttons(config: AppConfig) -> ButtonDriver:
        from halloween.drivers.gpio import GpioButtonDriver

        return GpioButtonDriver(config.buttons)

    return Backend(relays, buttons, lambda _config, write: DryRunHAClient(write))


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

    for name, text in (("run", "exécuter un programme"), ("simulate", "simuler un programme")):
        p = sub.add_parser(name, help=text)
        p.add_argument("program_id")
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
    ha = backend.ha(config, lambda line: print(line, file=out))
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
    "relay": cmd_relay,
    "run": cmd_run,
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
