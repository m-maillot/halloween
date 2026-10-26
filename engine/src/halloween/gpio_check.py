"""Vérification de la compatibilité GPIO sur le Raspberry Pi utilisé (`halloween-cli gpio-check`).

Sans option, la vérification ne commande rien : elle décrit l'environnement (modèle de Pi,
gpiozero, bibliothèque de broches) et crée les pilotes (ce qui met les sorties au repos).
Avec `--active`, elle fait basculer chaque relais (ils vont **cliquer** : débrancher les charges)
en relisant le niveau électrique de la broche, puis attend un appui sur chaque bouton.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import platform
from collections.abc import Callable as Callable_
from pathlib import Path
from typing import TextIO

from halloween.config.models import AppConfig
from halloween.drivers.base import ButtonDriver, ButtonEvent, RelayDriver

MODEL_FILE = Path("/proc/device-tree/model")
SETTLE_S = 0.3


def pi_model() -> str:
    """Modèle lu dans le device-tree (`Raspberry Pi 5 Model B Rev 1.0`), ou « inconnu »."""
    try:
        return MODEL_FILE.read_text(encoding="utf-8", errors="replace").strip("\x00\n ")
    except OSError:
        return "inconnu (ce n'est probablement pas un Raspberry Pi)"


def _version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "non installé"


class Report:
    def __init__(self, out: TextIO) -> None:
        self._out = out
        self.failures = 0

    def info(self, text: str) -> None:
        print(text, file=self._out)

    def ok(self, text: str) -> None:
        print(f"  OK      {text}", file=self._out)

    def warn(self, text: str) -> None:
        print(f"  ATTENTION {text}", file=self._out)

    def fail(self, text: str) -> None:
        self.failures += 1
        print(f"  ÉCHEC   {text}", file=self._out)


async def check_relays(
    config: AppConfig, driver: RelayDriver, report: Report, active: bool
) -> None:
    report.info("Relais")
    level = getattr(driver, "pin_level", None)
    for relay in config.relays:
        label = f"GPIO {relay.pin:<2} {relay.id}"
        resting = level is not None and level(relay.id)
        expected_rest = relay.active_low
        if level is None:
            report.warn(f"{label} : lecture du niveau électrique indisponible")
            continue
        if bool(resting) != expected_rest:
            report.fail(
                f"{label} : niveau {'haut' if resting else 'bas'} au repos, attendu "
                f"{'haut' if expected_rest else 'bas'} (active_low={relay.active_low})"
            )
            continue
        report.ok(f"{label} : au repos, niveau {'haut' if resting else 'bas'}")
        if not active:
            continue
        await driver.set(relay.id, True)
        await asyncio.sleep(SETTLE_S)
        active_level = level(relay.id)
        await driver.set(relay.id, False)
        await asyncio.sleep(SETTLE_S)
        if bool(active_level) == (not relay.active_low):
            shown = "haut" if active_level else "bas"
            report.ok(f"{label} : actif, niveau {shown} (a-t-il cliqué ?)")
        else:
            report.fail(
                f"{label} : le niveau n'a pas basculé comme attendu (active_low={relay.active_low})"
            )


async def check_buttons(
    config: AppConfig, driver: ButtonDriver, report: Report, press_timeout_s: float
) -> None:
    report.info("Boutons")
    received: asyncio.Queue[ButtonEvent] = asyncio.Queue()
    driver.subscribe(received.put_nowait)
    await driver.start()
    try:
        for button in config.buttons:
            report.info(
                f"  Appuyez sur « {button.name} » (GPIO {button.pin}), {press_timeout_s:g} s…"
            )
            try:
                async with asyncio.timeout(press_timeout_s):
                    while True:
                        event = await received.get()
                        if event.button_id == button.id:
                            break
            except TimeoutError:
                wired_to = "GND" if button.pull == "up" else "3,3 V"
                report.fail(
                    f"GPIO {button.pin:<2} {button.id} : aucun appui détecté "
                    f"(pull={button.pull} : vérifier le câblage vers {wired_to})"
                )
                continue
            report.ok(f"GPIO {button.pin:<2} {button.id} : appui {event.event} détecté")
    finally:
        await driver.close()


async def run_check(
    config: AppConfig,
    make_relays: Callable_[[AppConfig], RelayDriver],
    make_buttons: Callable_[[AppConfig], ButtonDriver],
    out: TextIO,
    active: bool = False,
    press_timeout_s: float = 10.0,
) -> int:
    report = Report(out)
    model = pi_model()
    report.info("Environnement")
    report.info(f"  Matériel : {model}")
    versions = f"gpiozero {_version('gpiozero')}, lgpio {_version('lgpio')}"
    report.info(f"  Python {platform.python_version()}, {versions}")

    relays = make_relays(config)
    try:
        factory = getattr(relays, "pin_factory_name", "inconnue")
        report.info(f"  Bibliothèque de broches : {factory}")
        if "Raspberry Pi 5" in model and factory != "LGPIOFactory":
            report.warn("Pi 5 : la bibliothèque `lgpio` est requise (uv sync --extra pi)")
        await check_relays(config, relays, report, active)
    finally:
        await relays.all_off()
        await relays.close()

    if active and config.buttons:
        await check_buttons(config, make_buttons(config), report, press_timeout_s)
    elif config.buttons:
        report.info("Boutons : non testés (ajouter --active pour attendre un appui)")

    report.info("")
    if report.failures:
        report.info(f"{report.failures} problème(s) détecté(s).")
        return 1
    report.info(
        "Aucun problème détecté."
        + ("" if active else " Relancer avec --active pour le test complet.")
    )
    return 0
