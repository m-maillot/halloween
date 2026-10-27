from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from halloween.triggers.cron import CronError, CronExpression

PARIS = ZoneInfo("Europe/Paris")


def at(y, mo, d, h=0, mi=0, tz=PARIS, s=0) -> datetime:
    return datetime(y, mo, d, h, mi, s, tzinfo=tz)


def nxt(expression: str, moment: datetime) -> datetime:
    result = CronExpression(expression).next_after(moment)
    assert result is not None
    return result


@pytest.mark.parametrize(
    ("expression", "moment", "expected"),
    [
        ("0 18 31 10 *", at(2026, 10, 27, 12), at(2026, 10, 31, 18)),
        ("0 18 31 10 *", at(2026, 10, 31, 18), at(2027, 10, 31, 18)),  # strictement après
        ("0 18 31 10 *", at(2026, 10, 31, 17, 59, s=59), at(2026, 10, 31, 18)),
        ("* * * * *", at(2026, 10, 27, 12, 0, s=30), at(2026, 10, 27, 12, 1)),
        ("*/15 * * * *", at(2026, 10, 27, 12, 14), at(2026, 10, 27, 12, 15)),
        ("*/15 * * * *", at(2026, 10, 27, 12, 45), at(2026, 10, 27, 13, 0)),
        ("30 9-17/4 * * *", at(2026, 10, 27, 9, 30), at(2026, 10, 27, 13, 30)),
        ("0,30 8 * * *", at(2026, 10, 27, 8, 0), at(2026, 10, 27, 8, 30)),
        ("0 0 1 1 *", at(2026, 12, 31, 23, 59), at(2027, 1, 1)),  # changement d'année
        ("0 12 31 * *", at(2026, 11, 1), at(2026, 12, 31, 12)),  # mois de 30 jours sautés
        ("0 0 29 2 *", at(2026, 3, 1), at(2028, 2, 29)),  # année bissextile
        ("0 20 * * mon-fri", at(2026, 10, 30, 21), at(2026, 11, 2, 20)),  # vendredi → lundi
        ("0 20 * * sat,sun", at(2026, 10, 27), at(2026, 10, 31, 20)),
        ("0 8 * * 0", at(2026, 10, 27), at(2026, 11, 1, 8)),  # dimanche = 0
        ("0 8 * * 7", at(2026, 10, 27), at(2026, 11, 1, 8)),  # dimanche = 7
        ("0 0 * jan-mar *", at(2026, 4, 1), at(2027, 1, 1)),
        ("0 0 * OCT *", at(2026, 5, 5), at(2026, 10, 1)),  # noms insensibles à la casse
        ("@daily", at(2026, 10, 27, 5), at(2026, 10, 28)),
        ("@hourly", at(2026, 10, 27, 5, 10), at(2026, 10, 27, 6)),
        ("@weekly", at(2026, 10, 27), at(2026, 11, 1)),
    ],
)
def test_next_after(expression, moment, expected):
    assert nxt(expression, moment) == expected


def test_day_of_month_and_day_of_week_are_ored_when_both_are_restricted():
    # comme cron : le 15 du mois OU un vendredi
    assert nxt("0 9 15 * fri", at(2026, 10, 27)) == at(2026, 10, 30, 9)  # vendredi 30
    assert nxt("0 9 15 * fri", at(2026, 11, 2)) == at(2026, 11, 6, 9)  # vendredi avant le 15
    assert nxt("0 9 15 * fri", at(2026, 11, 14)) == at(2026, 11, 15, 9)  # le 15 (dimanche)


def test_only_one_of_them_restricted_both_must_match():
    assert nxt("0 9 * * fri", at(2026, 10, 27)) == at(2026, 10, 30, 9)
    assert nxt("0 9 15 * *", at(2026, 10, 27)) == at(2026, 11, 15, 9)


def test_timezone_is_the_wall_clock_of_the_moment_given():
    # 18:00 à Paris (UTC+1 fin octobre) = 17:00 UTC
    result = nxt("0 18 * * *", at(2026, 11, 2, 12, tz=UTC))
    assert result.astimezone(UTC) == at(2026, 11, 2, 18, tz=UTC)  # 18:00 UTC
    assert nxt("0 18 * * *", at(2026, 11, 2, 12)).astimezone(UTC) == at(2026, 11, 2, 17, tz=UTC)


def test_dst_spring_forward_skips_the_missing_hour_that_day():
    # 2026-03-29 : à 02:00 les pendules passent à 03:00, 02:30 n'existe pas
    assert nxt("30 2 * * *", at(2026, 3, 28, 12)) == at(2026, 3, 30, 2, 30)
    assert nxt("30 3 * * *", at(2026, 3, 28, 12)) == at(2026, 3, 29, 3, 30)  # valide : conservée


def test_dst_fall_back_fires_once_at_the_first_occurrence():
    # 2026-10-25 : à 03:00 les pendules reviennent à 02:00, 02:30 existe deux fois
    first = nxt("30 2 * * *", at(2026, 10, 24, 12))
    assert first == at(2026, 10, 25, 2, 30) and first.utcoffset().total_seconds() == 7200  # CEST
    second = nxt("30 2 * * *", first)
    assert second == at(2026, 10, 26, 2, 30)  # le lendemain, pas une seconde fois ce jour-là


def test_requires_a_timezone_aware_moment():
    with pytest.raises(ValueError, match="fuseau"):
        CronExpression("* * * * *").next_after(datetime(2026, 1, 1))


@pytest.mark.parametrize(
    ("expression", "fragment"),
    [
        ("", "5 champs"),
        ("* * * *", "5 champs"),
        ("* * * * * *", "5 champs"),
        ("60 * * * *", "hors de 0-59"),
        ("* 24 * * *", "hors de 0-23"),
        ("* * 0 * *", "hors de 1-31"),
        ("* * * 13 *", "hors de 1-12"),
        ("* * * * 8", "hors de 0-7"),
        ("5-1 * * * *", "à l'envers"),
        ("*/0 * * * *", "pas invalide"),
        ("*/x * * * *", "pas invalide"),
        ("a * * * *", "valeur invalide"),
        ("1,,2 * * * *", "élément vide"),
        ("* * * foo *", "valeur invalide"),
        ("0 0 31 2 *", "jamais"),
        ("0 0 30 2 *", "jamais"),
    ],
)
def test_invalid_expressions(expression, fragment):
    with pytest.raises(CronError, match=fragment):
        CronExpression(expression)


def test_error_is_a_value_error():
    assert issubclass(CronError, ValueError)
