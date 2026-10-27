"""Dialogue avec `systemd` : service prêt, signal de vie périodique, arrêt (spec 1 §6.3).

Le signal de vie est envoyé **par la boucle d'événements elle-même** : si la boucle gèle (code
bloquant, interblocage), il s'arrête, `systemd` constate le silence au bout de `WatchdogSec`, tue
le processus puis le relance, ce qui éteint les relais au démarrage. Aucune dépendance : le
protocole `sd_notify` est un datagramme sur le socket Unix `$NOTIFY_SOCKET`.

Hors `systemd` (pas de `NOTIFY_SOCKET`), tout est inactif.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
from collections.abc import Mapping

from halloween.log import get_logger

log = get_logger("watchdog")

# Signal de vie à la moitié du délai de `systemd` (recommandation de sd_watchdog_enabled).
HEARTBEAT_RATIO = 0.5


def notify(message: str, env: Mapping[str, str] | None = None) -> bool:
    """Envoie un message `sd_notify` ; `False` si `systemd` n'écoute pas ou en cas d'erreur."""
    path = (os.environ if env is None else env).get("NOTIFY_SOCKET")
    if not path:
        return False
    if path.startswith("@"):  # socket abstrait
        path = "\0" + path[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC) as sock:
            sock.setblocking(False)
            sock.sendto(message.encode(), path)
    except OSError as exc:
        log.warning("sd_notify impossible : %s", exc)
        return False
    return True


def watchdog_interval(env: Mapping[str, str] | None = None) -> float | None:
    """Période du signal de vie en secondes, ou `None` si `systemd` ne surveille pas ce service."""
    env = os.environ if env is None else env
    try:
        usec = int(env.get("WATCHDOG_USEC", ""))
    except ValueError:
        return None
    pid = env.get("WATCHDOG_PID")
    if usec <= 0 or (pid and pid != str(os.getpid())):
        return None
    return usec / 1_000_000 * HEARTBEAT_RATIO


class Watchdog:
    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env = env
        self._task: asyncio.Task[None] | None = None
        self.interval = watchdog_interval(env)
        self.beats = 0

    def ready(self, status: str = "") -> None:
        """Annonce le service prêt et démarre le signal de vie (à appeler dans la boucle)."""
        notify("READY=1" + (f"\nSTATUS={status}" if status else ""), self._env)
        if self.interval is not None and self._task is None:
            self._task = asyncio.ensure_future(self._beat())
            log.info("signal de vie systemd toutes les %.1f s", self.interval)

    async def _beat(self) -> None:
        while True:
            if notify("WATCHDOG=1", self._env):
                self.beats += 1
            await asyncio.sleep(self.interval or 1.0)

    async def stop(self) -> None:
        """Annonce l'arrêt (systemd n'attend alors plus de signal de vie)."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        notify("STOPPING=1", self._env)
