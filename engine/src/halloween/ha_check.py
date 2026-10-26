"""Validation sur l'installation réelle (`halloween-cli ha-check`).

Sans `--active`, la commande ne fait que **lire** : connexion, entités, capacités déclarées par
Home Assistant comparées à la configuration. Avec `--active`, elle commande chaque lumière /
interrupteur configuré (couleur, luminosité, transition), mesure la latence des appels, puis
remet l'état d'avant.
"""

from __future__ import annotations

import asyncio
import difflib
import statistics
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TextIO

from halloween.config.models import AppConfig, Light
from halloween.drivers.base import (
    HAAuthError,
    HAError,
    HANotFound,
    HATimeout,
    HAUnreachable,
)
from halloween.drivers.homeassistant import EntityInfo, HttpHAClient

COLOR_MODES = {"hs", "xy", "rgb", "rgbw", "rgbww"}
TRANSITION_FEATURE = 32  # LightEntityFeature.TRANSITION de Home Assistant


@dataclass(frozen=True)
class Capabilities:
    color: bool
    brightness: bool
    transition: bool


def infer_capabilities(attributes: Mapping[str, Any]) -> Capabilities:
    """Capacités d'une lumière d'après ses attributs Home Assistant.

    - couleur : un mode colorimétrique (`hs`, `xy`, `rgb`, `rgbw`, `rgbww`) est supporté ;
    - luminosité : tout mode autre que `onoff` ;
    - transition : bit `TRANSITION` (32) de `supported_features`.
    """
    modes = {str(m) for m in attributes.get("supported_color_modes") or []}
    features = int(attributes.get("supported_features") or 0)
    return Capabilities(
        color=bool(modes & COLOR_MODES),
        brightness=bool(modes - {"onoff"}),
        transition=bool(features & TRANSITION_FEATURE),
    )


def hint_for(error: HAError) -> str:
    if isinstance(error, HAAuthError):
        return (
            "Créer un jeton longue durée (Home Assistant > votre profil > Sécurité) puis le placer "
            "dans config.json ou dans HALLOWEEN_HA_TOKEN."
        )
    if isinstance(error, HAUnreachable):
        return (
            "Vérifier l'URL (http://hôte:8123), le réseau du Pi et que Home Assistant est démarré."
        )
    if isinstance(error, HATimeout):
        return "Home Assistant est lent ou bloqué ; augmenter timeout_s si besoin."
    if isinstance(error, HANotFound):
        return "L'URL ne pointe probablement pas sur l'API de Home Assistant (préfixe ?)."
    return ""


class Report:
    def __init__(self, out: TextIO) -> None:
        self._out = out
        self.failures = 0
        self.warnings = 0

    def info(self, text: str = "") -> None:
        print(text, file=self._out)

    def ok(self, text: str) -> None:
        print(f"  OK        {text}", file=self._out)

    def warn(self, text: str) -> None:
        self.warnings += 1
        print(f"  ATTENTION {text}", file=self._out)

    def fail(self, text: str) -> None:
        self.failures += 1
        print(f"  ÉCHEC     {text}", file=self._out)


def _yes_no(value: bool) -> str:
    return "oui" if value else "non"


def compare_capabilities(light: Light, found: Capabilities, report: Report) -> None:
    for label, configured, detected in (
        ("couleur", light.supports_color, found.color),
        ("luminosité", light.supports_brightness, found.brightness),
        ("transition", light.supports_transition, found.transition),
    ):
        line = (
            f"{light.id} : {label} "
            f"(config : {_yes_no(configured)}, Home Assistant : {_yes_no(detected)})"
        )
        if configured and not detected:
            report.fail(line + " - la config demande une capacité que la lumière n'a pas")
        elif detected and not configured:
            report.warn(line + " - disponible mais non utilisée (mettre true pour l'utiliser)")
        else:
            report.ok(line)


async def _timed(latencies: list[float], call: Any) -> None:
    started = time.perf_counter()
    await call
    latencies.append((time.perf_counter() - started) * 1000)


async def active_light_test(
    light: Light, client: HttpHAClient, before: EntityInfo, report: Report, pause_s: float
) -> list[float]:
    """Allume la lumière avec chaque paramètre supporté, puis restaure son état précédent."""
    latencies: list[float] = []
    steps: list[tuple[str, dict[str, Any]]] = [("allumée", {})]
    if light.supports_brightness:
        steps.append(("luminosité 50 %", {"brightness": 128}))
    if light.supports_color:
        steps.append(("rouge", {"rgb_color": (255, 0, 0)}))
        steps.append(("vert", {"rgb_color": (0, 255, 0)}))
    if light.supports_transition:
        steps.append(
            (
                "transition 2 s",
                {"transition": 2, "rgb_color": (0, 0, 255)}
                if light.supports_color
                else {"transition": 2},
            )
        )
    try:
        for label, params in steps:
            try:
                await _timed(latencies, client.light_on(light.entity_id, **params))
                report.ok(f"{light.id} : {label}")
            except HAError as exc:
                report.fail(f"{light.id} : {label} refusé - {exc}")
            await asyncio.sleep(pause_s)
    finally:
        try:
            if before.state == "on":
                color = before.attributes.get("rgb_color")
                await client.light_on(
                    light.entity_id,
                    rgb_color=tuple(color) if color else None,
                    brightness=before.attributes.get("brightness"),
                )
            else:
                await client.light_off(light.entity_id)
        except HAError as exc:
            report.warn(f"{light.id} : état initial non restauré - {exc}")
    return latencies


async def run_ha_check(
    config: AppConfig,
    client: HttpHAClient,
    out: TextIO,
    active: bool = False,
    pause_s: float = 1.0,
) -> int:
    report = Report(out)
    report.info(f"Home Assistant : {config.home_assistant.url if config.home_assistant else '?'}")
    started = time.perf_counter()
    try:
        message = await client.check_connection()
        entities = {e.entity_id: e for e in await client.list_entities()}
    except HAError as exc:
        report.fail(str(exc))
        if hint := hint_for(exc):
            report.info(f"            {hint}")
        return 1
    report.ok(f"connexion ({(time.perf_counter() - started) * 1000:.0f} ms) : {message}")

    configured = {c.entity_id: c.id for c in (*config.lights, *config.switches)}
    report.info("Entités lumière / interrupteur disponibles :")
    for entity in entities.values():
        if entity.domain in ("light", "switch"):
            used = (
                f"  [config : {configured[entity.entity_id]}]"
                if entity.entity_id in configured
                else ""
            )
            report.info(f"    {entity.entity_id:<40} {entity.name} ({entity.state}){used}")

    report.info("Composants configurés")
    present: list[tuple[Light, EntityInfo]] = []
    for component in (*config.lights, *config.switches):
        entity = entities.get(component.entity_id)
        if entity is None:
            close = difflib.get_close_matches(component.entity_id, list(entities), n=3)
            report.fail(
                f"{component.id} : entité `{component.entity_id}` introuvable"
                + (f" (proches : {', '.join(close)})" if close else "")
            )
            continue
        report.ok(f"{component.id} : `{component.entity_id}` existe ({entity.state})")
        if isinstance(component, Light):
            compare_capabilities(component, infer_capabilities(entity.attributes), report)
            present.append((component, entity))

    if active:
        report.info("Test actif (les lumières vont changer ; leur état est restauré ensuite)")
        all_latencies: list[float] = []
        for light, before in present:
            all_latencies += await active_light_test(light, client, before, report, pause_s)
        for switch in config.switches:
            entity = entities.get(switch.entity_id)
            if entity is None:
                continue
            try:
                await _timed(all_latencies, client.switch_on(switch.entity_id))
                await asyncio.sleep(pause_s)
                await (client.switch_on if entity.state == "on" else client.switch_off)(
                    switch.entity_id
                )
                report.ok(f"{switch.id} : basculé puis restauré")
            except HAError as exc:
                report.fail(f"{switch.id} : {exc}")
        if all_latencies:
            report.info(
                f"Latence des appels : moyenne {statistics.mean(all_latencies):.0f} ms, "
                f"max {max(all_latencies):.0f} ms sur {len(all_latencies)} appels "
                "(temps de réponse de l'API, pas de réaction visible de l'éclairage)"
            )
    else:
        report.info("Test actif non lancé (ajouter --active pour piloter les lumières).")

    report.info()
    if report.failures:
        report.info(f"{report.failures} problème(s), {report.warnings} avertissement(s).")
        return 1
    report.info(f"Aucun problème bloquant, {report.warnings} avertissement(s).")
    return 0
