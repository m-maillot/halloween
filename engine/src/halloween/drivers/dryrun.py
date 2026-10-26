"""Client Home Assistant « à blanc » : affiche les appels sans rien envoyer.

Sert à la ligne de commande tant que le client réel n'est pas configuré, et aux essais sur le Pi
sans réseau.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from halloween.drivers.base import HAClient


class DryRunHAClient(HAClient):
    def __init__(self, write: Callable[[str], None] = print) -> None:
        self._write = write

    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> None:
        self._write(
            f"[Home Assistant simulé] {domain}/{service} {json.dumps(data, ensure_ascii=False)}"
        )
