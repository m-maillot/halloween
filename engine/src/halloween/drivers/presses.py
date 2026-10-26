"""Reconnaissance des appuis : court, long, double.

Machine à états indépendante du matériel (testable en temps virtuel). Elle reçoit les fronts
`press()` / `release()` (déjà débattus) dans la boucle asyncio et appelle `emit(kind)` :

- **long** : dès que le bouton est maintenu `long_press_s`, sans attendre le relâchement ;
- **double** : second appui reçu moins de `double_press_s` après le relâchement d'un appui court ;
- **short** : appui court non suivi d'un second appui dans `double_press_s`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from enum import Enum, auto

from halloween.drivers.base import ButtonEventKind


class _State(Enum):
    IDLE = auto()
    DOWN = auto()  # premier appui en cours, pas encore « long »
    HELD = auto()  # appui long déjà émis, on attend le relâchement
    WAIT_SECOND = auto()  # appui court relâché, on guette un second appui
    DOWN_SECOND = auto()  # second appui (double déjà émis), on attend le relâchement


class PressClassifier:
    def __init__(
        self,
        emit: Callable[[ButtonEventKind], None],
        long_press_s: float = 0.8,
        double_press_s: float = 0.4,
    ) -> None:
        self._emit = emit
        self._long_s = long_press_s
        self._double_s = double_press_s
        self._state = _State.IDLE
        self._timer: asyncio.TimerHandle | None = None

    def press(self) -> None:
        if self._state is _State.IDLE:
            self._state = _State.DOWN
            self._start_timer(self._long_s, self._on_long)
        elif self._state is _State.WAIT_SECOND:
            self._cancel_timer()
            self._state = _State.DOWN_SECOND
            self._emit("double")
        # appui déjà en cours : front en double, ignoré

    def release(self) -> None:
        if self._state is _State.DOWN:
            self._cancel_timer()
            self._state = _State.WAIT_SECOND
            self._start_timer(self._double_s, self._on_double_window_expired)
        elif self._state in (_State.HELD, _State.DOWN_SECOND):
            self._state = _State.IDLE
        # relâchement sans appui : ignoré

    def reset(self) -> None:
        """Abandonne toute reconnaissance en cours (arrêt du pilote)."""
        self._cancel_timer()
        self._state = _State.IDLE

    # ------------------------------------------------------------------ minuteurs

    def _start_timer(self, delay: float, callback: Callable[[], None]) -> None:
        self._cancel_timer()
        self._timer = asyncio.get_running_loop().call_later(delay, callback)

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _on_long(self) -> None:
        self._timer = None
        self._state = _State.HELD
        self._emit("long")

    def _on_double_window_expired(self) -> None:
        self._timer = None
        self._state = _State.IDLE
        self._emit("short")
