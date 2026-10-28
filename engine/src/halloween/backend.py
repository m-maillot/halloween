"""Fabriques de pilotes : GPIO et Home Assistant réels par défaut, fictifs dans les tests."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from halloween.config.models import AppConfig
from halloween.drivers.base import ButtonDriver, HAClient, RelayDriver
from halloween.drivers.dryrun import DryRunHAClient
from halloween.drivers.homeassistant import TOKEN_ENV, HttpHAClient

# La chauffe d'un détecteur de mouvement court depuis la mise sous tension, pas depuis la dernière
# reconstruction des pilotes (un changement de configuration en provoque une) : on compte depuis
# le démarrage du processus.
PROCESS_STARTED = time.monotonic()


@dataclass
class Backend:
    """Fabriques de pilotes : GPIO réels par défaut, pilotes fictifs dans les tests."""

    relays: Callable[[AppConfig], RelayDriver]
    buttons: Callable[[AppConfig], ButtonDriver]
    # (config, écriture de messages, forcer le mode simulé)
    ha: Callable[[AppConfig, Callable[[str], None], bool], HAClient]


def gpio_backend() -> Backend:
    def relays(config: AppConfig) -> RelayDriver:
        from halloween.drivers.gpio import GpioRelayDriver

        return GpioRelayDriver(config.relays)

    def buttons(config: AppConfig) -> ButtonDriver:
        from halloween.drivers.gpio import GpioButtonDriver

        return GpioButtonDriver(config.buttons, warmup_origin=PROCESS_STARTED)

    def ha(config: AppConfig, write: Callable[[str], None], dry_run: bool) -> HAClient:
        settings = config.home_assistant
        if dry_run or settings is None:
            return DryRunHAClient(write)
        if not (os.environ.get(TOKEN_ENV) or settings.token):
            write("Home Assistant : aucun jeton configuré, appels simulés")
            return DryRunHAClient(write)
        write(f"Home Assistant : appels réels vers {settings.url}")
        return HttpHAClient.from_config(settings)

    return Backend(relays, buttons, ha)


def simulated_backend() -> Backend:
    """Pilotes fictifs : ni GPIO ni appel à Home Assistant. Pour essayer l'interface sans matériel
    et pour les tests de bout en bout ; l'état des relais est tenu en mémoire."""
    from halloween.drivers.fakes import FakeButtonDriver, FakeRelayDriver

    def relays(config: AppConfig) -> RelayDriver:
        return FakeRelayDriver.from_config(config)

    def buttons(config: AppConfig) -> ButtonDriver:
        return FakeButtonDriver(b.id for b in config.buttons)

    def ha(_config: AppConfig, write: Callable[[str], None], _dry_run: bool) -> HAClient:
        return DryRunHAClient(write)

    return Backend(relays, buttons, ha)
