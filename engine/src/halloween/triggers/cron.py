"""Expressions cron à 5 champs (minute heure jour-du-mois mois jour-de-semaine).

Syntaxe : `*`, valeurs, listes (`1,15`), intervalles (`9-17`), pas (`*/5`, `9-17/2`), noms de mois
(`jan`…`dec`) et de jours (`sun`…`sat`), alias `@hourly`, `@daily`, `@weekly`, `@monthly`,
`@yearly`. Dimanche = 0 ou 7. Comme cron : si le jour-du-mois **et** le jour-de-semaine sont
restreints, l'un **ou** l'autre suffit.

Fuseaux horaires : l'expression s'évalue à l'heure murale du fuseau. Une heure qui n'existe pas
(passage à l'heure d'été) est sautée ce jour-là ; une heure qui se répète (passage à l'heure
d'hiver) ne déclenche qu'une fois, la première.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

ALIASES = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}
MONTHS = {n: i for i, n in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
DAYS = {n: i for i, n in enumerate("sun mon tue wed thu fri sat".split())}

# Recherche : au-delà de 8 ans (un 29 février tous les 4 ans, y compris le siècle non bissextile).
SEARCH_DAYS = 366 * 8


class CronError(ValueError):
    """Expression cron invalide."""


def _parse_field(
    text: str, low: int, high: int, names: dict[str, int], label: str
) -> frozenset[int]:
    values: set[int] = set()
    for part in text.split(","):
        if not part:
            raise CronError(f"{label} : élément vide dans « {text} »")
        base, _, step_text = part.partition("/")
        step = 1
        if step_text:
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(f"{label} : pas invalide « {step_text} »")
            step = int(step_text)

        def number(token: str) -> int:
            token = token.lower()
            if token in names:
                return names[token]
            if token.isdigit():
                return int(token)
            raise CronError(f"{label} : valeur invalide « {token} »")

        if base == "*":
            start, end = low, high
        elif "-" in base:
            first, _, last = base.partition("-")
            start, end = number(first), number(last)
        else:
            start = number(base)
            end = high if step_text else start
        if not low <= start <= high:
            raise CronError(f"{label} : {start} hors de {low}-{high}")
        if not low <= end <= high:
            raise CronError(f"{label} : {end} hors de {low}-{high}")
        if start > end:
            raise CronError(f"{label} : intervalle à l'envers « {base} »")
        values.update(range(start, end + 1, step))
    if label == "jour de semaine" and 7 in values:  # 7 = dimanche, comme 0
        values.discard(7)
        values.add(0)
    return frozenset(values)


class CronExpression:
    def __init__(self, expression: str) -> None:
        self.expression = expression.strip()
        text = ALIASES.get(self.expression, self.expression)
        fields = text.split()
        if len(fields) != 5:
            raise CronError(
                f"5 champs attendus (minute heure jour mois jour-de-semaine), {len(fields)} trouvés"
            )
        minute, hour, dom, month, dow = fields
        self.minutes = sorted(_parse_field(minute, 0, 59, {}, "minute"))
        self.hours = sorted(_parse_field(hour, 0, 23, {}, "heure"))
        self.days_of_month = _parse_field(dom, 1, 31, {}, "jour du mois")
        self.months = _parse_field(month, 1, 12, MONTHS, "mois")
        self.days_of_week = _parse_field(dow, 0, 7, DAYS, "jour de semaine")
        self._dom_restricted = not dom.startswith("*")
        self._dow_restricted = not dow.startswith("*")
        # Une expression qui ne se produit jamais (ex. 31 février) est une erreur de saisie.
        if self.next_after(datetime(2026, 1, 1, tzinfo=UTC)) is None:
            raise CronError("cette expression ne se produit jamais")

    def _day_matches(self, day: date) -> bool:
        if day.month not in self.months:
            return False
        in_month = day.day in self.days_of_month
        in_week = (day.weekday() + 1) % 7 in self.days_of_week
        if self._dom_restricted and self._dow_restricted:
            return in_month or in_week
        return in_month and in_week

    def next_after(self, moment: datetime) -> datetime | None:
        """Prochaine échéance **strictement après** `moment` (datetime avec fuseau), ou `None`."""
        if moment.tzinfo is None:
            raise ValueError("un datetime avec fuseau horaire est requis")
        tz = moment.tzinfo
        local = moment.astimezone(tz).replace(second=0, microsecond=0, tzinfo=None) + timedelta(
            minutes=1
        )
        day = local.date()
        for offset in range(SEARCH_DAYS):
            current = day + timedelta(days=offset)
            if not self._day_matches(current):
                continue
            for hour in self.hours:
                for minute in self.minutes:
                    candidate = datetime(current.year, current.month, current.day, hour, minute)
                    if candidate < local:
                        continue
                    aware = candidate.replace(tzinfo=tz)
                    # heure inexistante (heure d'été) : l'aller-retour ne la restitue pas
                    if aware.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != candidate:
                        continue
                    if aware > moment:
                        return aware
        return None
