import asyncio

import pytest

from halloween.drivers.presses import PressClassifier
from halloween.program.virtual import run_virtual

LONG = 0.8
DOUBLE = 0.4


def classify(script: list[tuple[float, str]], until: float = 10.0) -> list[tuple[float, str]]:
    """Joue `[(t, "press"|"release")]` et retourne les événements `[(t, kind)]` émis."""
    emitted: list[tuple[float, str]] = []

    async def main():
        loop = asyncio.get_running_loop()
        clf = PressClassifier(
            lambda kind: emitted.append((round(loop.time(), 3), kind)), LONG, DOUBLE
        )
        for t, action in script:
            await asyncio.sleep(max(0.0, t - loop.time()))
            getattr(clf, action)()
        await asyncio.sleep(until - loop.time())
        clf.reset()

    run_virtual(main)
    return emitted


def test_short_press_is_confirmed_after_the_double_press_window():
    assert classify([(0, "press"), (0.1, "release")]) == [(0.5, "short")]


def test_long_press_fires_while_still_held_and_release_adds_nothing():
    assert classify([(0, "press"), (2.0, "release")]) == [(0.8, "long")]


def test_press_just_under_the_long_threshold_is_short():
    assert classify([(0, "press"), (0.79, "release")]) == [(1.19, "short")]


def test_double_press_fires_on_the_second_press_and_no_short():
    assert classify([(0, "press"), (0.1, "release"), (0.3, "press"), (0.4, "release")]) == [
        (0.3, "double")
    ]


def test_second_press_after_the_window_is_a_new_short_press():
    events = classify([(0, "press"), (0.1, "release"), (0.6, "press"), (0.7, "release")])
    assert events == [(0.5, "short"), (1.1, "short")]


def test_second_press_held_long_after_a_double_does_not_emit_long():
    events = classify([(0, "press"), (0.1, "release"), (0.3, "press"), (3.0, "release")])
    assert events == [(0.3, "double")]


def test_triple_click_is_a_double_then_a_short():
    script = [
        (0, "press"),
        (0.1, "release"),
        (0.2, "press"),
        (0.3, "release"),
        (0.4, "press"),
        (0.5, "release"),
    ]
    assert classify(script) == [(0.2, "double"), (0.9, "short")]


def test_a_new_sequence_works_after_a_long_press():
    script = [(0, "press"), (1.5, "release"), (2.0, "press"), (2.1, "release")]
    assert classify(script) == [(0.8, "long"), (2.5, "short")]


@pytest.mark.parametrize(
    "script",
    [
        [(0, "release")],  # relâchement sans appui
        [(0, "release"), (1, "release")],
    ],
)
def test_release_without_press_is_ignored(script):
    assert classify(script) == []


def test_duplicate_edges_are_ignored():
    script = [(0, "press"), (0.05, "press"), (0.1, "release"), (0.12, "release")]
    assert classify(script) == [(0.5, "short")]


def test_reset_cancels_pending_events():
    emitted = []

    async def main():
        clf = PressClassifier(emitted.append, LONG, DOUBLE)
        clf.press()
        clf.reset()
        await asyncio.sleep(5)

    run_virtual(main)
    assert emitted == []
