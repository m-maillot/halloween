"""Fuseau horaire du système (celui du Raspberry Pi), avec ses règles d'heure d'été."""

from __future__ import annotations

import os
from datetime import datetime, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from halloween.log import get_logger

log = get_logger("timezone")


def system_timezone(
    env: dict[str, str] | None = None,
    localtime: Path = Path("/etc/localtime"),
    timezone_file: Path = Path("/etc/timezone"),
) -> tzinfo:
    """Fuseau IANA du système : variable `TZ`, lien `/etc/localtime`, puis `/etc/timezone`.

    En dernier recours, le décalage actuel (sans passage heure d'été / hiver) avec un avertissement.
    """
    names: list[str] = []
    tz = (os.environ if env is None else env).get("TZ", "").lstrip(":")
    if tz:
        names.append(tz)
    try:
        resolved = str(localtime.resolve())
        if "zoneinfo/" in resolved:
            names.append(resolved.split("zoneinfo/", 1)[1])
    except OSError:
        pass
    try:
        names.append(timezone_file.read_text(encoding="utf-8").strip())
    except OSError:
        pass
    for name in names:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            continue
    fallback = datetime.now().astimezone().tzinfo
    log.warning("fuseau horaire du système introuvable : décalage fixe, pas d'heure d'été")
    assert fallback is not None
    return fallback
