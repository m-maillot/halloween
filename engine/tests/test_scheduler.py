import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from halloween.config import AppConfig
from halloween.drivers import FakeButtonDriver, FakeHAClient, FakeRelayDriver
from halloween.program import Program
from halloween.program.runs import RunManager
from halloween.program.virtual import run_virtual
from halloween.triggers import TriggerEngine, parse_triggers
from halloween.triggers.models import ScheduleTrigger
from halloween.triggers.timezone import system_timezone

ROOT = Path(__file__).resolve().parents[2]
PARIS = ZoneInfo("Europe/Paris")


def program(id_: str, seconds: float = 1.0) -> Program:
    root = {"id": "n", "type": "wait", "seconds": seconds}
    return Program.model_validate({"id": id_, "name": id_, "scripts": [{"id": "s", "root": root}]})


def schedule(id_="t", cron="0 18 31 10 *", program_id="ambiance", **kw) -> ScheduleTrigger:
    return ScheduleTrigger.model_validate(
        {"id": id_, "source": "schedule", "cron": cron, "program": program_id, **kw}
    )


class World:
    """Moteur de déclencheurs sur horloge murale virtuelle (départ + temps de la boucle)."""

    def __init__(self, start: datetime, triggers=()):
        loop = asyncio.get_running_loop()
        self.loop = loop
        self.start = start
        self.jump = timedelta(0)  # décalage de l'horloge (saut après resynchronisation réseau)
        config = AppConfig.model_validate(
            json.loads((ROOT / "deploy" / "config.example.json").read_text(encoding="utf-8"))
        )
        self.programs = {"ambiance": program("ambiance"), "autre": program("autre")}
        self.manager = RunManager(
            config,
            FakeRelayDriver.from_config(config),
            FakeHAClient(),
            FakeButtonDriver([]),
            self.programs,
        )
        self.starts: list[tuple[str, datetime]] = []
        original = self.manager.start

        async def recording_start(prog, policy="ignore"):
            self.starts.append((prog.id, self.now()))
            return await original(prog, policy)

        self.manager.start = recording_start
        self.engine = TriggerEngine(
            self.manager,
            FakeButtonDriver([]),
            self.programs,
            triggers,
            clock=self.now,
            default_timezone=PARIS,
        )

    def now(self) -> datetime:
        # arithmétique sur l'instant (UTC) : sur l'heure murale, l'heure d'été serait ignorée
        instant = self.start.astimezone(UTC) + timedelta(seconds=self.loop.time()) + self.jump
        return instant.astimezone(PARIS)

    def started(self, program_id="ambiance") -> list[datetime]:
        return [when for pid, when in self.starts if pid == program_id]


def scenario(start: datetime, triggers=()):
    def decorator(test):
        def wrapper():
            async def main():
                world = World(start, triggers)
                await world.engine.start()
                try:
                    await test(world)
                finally:
                    await world.engine.stop()
                    await world.manager.shutdown()

            run_virtual(main)

        wrapper.__name__ = test.__name__
        return wrapper

    return decorator


def at(y, mo, d, h=0, mi=0, s=0, tz=PARIS) -> datetime:
    return datetime(y, mo, d, h, mi, s, tzinfo=tz)


# ------------------------------------------------------------------ échéances


@scenario(at(2026, 10, 31, 17, 59, 30), [schedule()])
async def test_trigger_fires_at_the_scheduled_time(world):
    await asyncio.sleep(120)
    (fired,) = world.started()
    assert at(2026, 10, 31, 18, 0, 0) <= fired < at(2026, 10, 31, 18, 0, 1)


@scenario(at(2026, 10, 31, 17, 0), [schedule(cron="0 18 31 10 *")])
async def test_does_not_fire_before_the_time(world):
    await asyncio.sleep(3000)  # jusqu'à 17:50
    assert world.started() == []


@scenario(at(2026, 10, 27, 12, 0, 30), [schedule(cron="* * * * *")])
async def test_every_minute_fires_every_minute(world):
    await asyncio.sleep(5 * 60)
    stamps = world.started()
    assert len(stamps) == 5
    assert all(b - a == timedelta(minutes=1) for a, b in zip(stamps, stamps[1:], strict=False))


@scenario(
    at(2026, 10, 31, 17, 59, 30),
    [schedule("a", program_id="ambiance"), schedule("b", program_id="autre")],
)
async def test_two_triggers_due_together_both_fire(world):
    await asyncio.sleep(60)
    assert len(world.started("ambiance")) == 1 and len(world.started("autre")) == 1


@scenario(at(2026, 10, 31, 17, 59, 30), [schedule(enabled=False)])
async def test_disabled_trigger_never_fires(world):
    await asyncio.sleep(120)
    assert world.started() == []


@scenario(at(2026, 10, 31, 16, 59, 30), [schedule(cron="0 18 * * *", timezone="UTC")])
async def test_trigger_timezone_overrides_the_default(world):
    # 18:00 UTC = 19:00 à Paris ; départ à 16:59:30 heure de Paris (15:59:30 UTC)
    await asyncio.sleep(3 * 3600)
    (fired,) = world.started()
    assert fired.astimezone(ZoneInfo("UTC")) >= at(2026, 10, 31, 18, 0, 0, tz=ZoneInfo("UTC"))
    assert fired.astimezone(ZoneInfo("UTC")) < at(2026, 10, 31, 18, 0, 1, tz=ZoneInfo("UTC"))


@scenario(at(2026, 10, 31, 17, 59, 30), [schedule(policy="restart")])
async def test_policy_is_applied_when_the_program_is_still_running(world):
    world.programs["ambiance"] = program("ambiance", seconds=3600)
    await asyncio.sleep(60)  # première exécution, longue
    first = world.manager.active[0]
    world.engine.set_triggers([schedule(cron="* * * * *", policy="restart")])
    await asyncio.sleep(70)
    assert first.outcome == "stopped" and len(world.manager.active) == 1


# ------------------------------------------------------------------ rechargement à chaud


@scenario(at(2026, 10, 31, 17, 0), [])
async def test_triggers_added_while_running_are_taken_into_account_immediately(world):
    await asyncio.sleep(1000)
    world.engine.set_triggers([schedule(cron="*/10 * * * *")])
    await asyncio.sleep(25 * 60)
    assert len(world.started()) >= 2


@scenario(at(2026, 10, 31, 17, 59, 30), [schedule()])
async def test_trigger_removed_before_its_time_does_not_fire(world):
    await asyncio.sleep(10)
    world.engine.set_triggers([])
    await asyncio.sleep(120)
    assert world.started() == []


@scenario(at(2026, 10, 31, 17, 0), [schedule(cron="0 18 * * *")])
async def test_changing_the_schedule_replaces_the_old_one(world):
    await asyncio.sleep(60)
    world.engine.set_triggers([schedule(cron="0 19 * * *")])
    await asyncio.sleep(2 * 3600 + 60)  # on passe 18:00 puis 19:00
    (fired,) = world.started()
    assert fired.hour == 19


# ------------------------------------------------------------------ horloge


@scenario(at(2026, 10, 31, 17, 59, 0), [schedule(cron="0 18 * * *")])
async def test_a_due_time_missed_by_a_clock_jump_is_skipped_not_launched_late(world):
    await asyncio.sleep(10)
    world.jump = timedelta(hours=2)  # resynchronisation : on saute à 19:59, 18:00 est loin derrière
    await asyncio.sleep(120)
    assert world.started() == []


@scenario(at(2026, 10, 31, 17, 58, 0), [schedule(cron="0 18 * * *")])
async def test_a_slightly_late_wake_up_still_fires(world):
    await asyncio.sleep(10)
    world.jump = timedelta(
        minutes=2, seconds=-40
    )  # l'heure saute à 18:00:20 : en retard de 20 s seulement
    await asyncio.sleep(60)
    assert len(world.started()) == 1


@scenario(at(2026, 10, 31, 17, 59, 50), [schedule(cron="0 18 * * *")])
async def test_clock_set_back_does_not_fire_twice(world):
    await asyncio.sleep(30)  # 18:00:20 : déjà déclenché
    assert len(world.started()) == 1
    world.jump = timedelta(seconds=-60)  # l'horloge recule de 60 s : on repasse avant 18:00
    await asyncio.sleep(20)
    world.jump = timedelta(seconds=-60)
    await asyncio.sleep(120)
    assert len(world.started()) == 2  # 18:00 est repassé : c'est une nouvelle occurrence réelle


@scenario(at(2026, 3, 29, 1, 59, 30), [schedule(cron="30 2 * * *")])
async def test_dst_spring_forward_skips_the_nonexistent_time_that_day(world):
    await asyncio.sleep(24 * 3600)
    (fired,) = world.started()
    assert fired.date() == datetime(2026, 3, 30).date()


# ------------------------------------------------------------------ modèle et fuseau du système


def test_schedule_model_rejects_bad_cron_and_timezone():
    triggers, issues = parse_triggers(
        [
            {"id": "ok", "source": "schedule", "cron": "0 18 31 10 *", "program": "p"},
            {"id": "badcron", "source": "schedule", "cron": "0 18 31", "program": "p"},
            {"id": "never", "source": "schedule", "cron": "0 0 31 2 *", "program": "p"},
            {
                "id": "badtz",
                "source": "schedule",
                "cron": "* * * * *",
                "timezone": "Mars/Olympus",
                "program": "p",
            },
        ]
    )
    assert [t.id for t in triggers] == ["ok"]
    assert [i.component_id for i in issues] == ["badcron", "never", "badtz"]
    assert "cron invalide" in issues[0].message and "fuseau horaire inconnu" in issues[2].message


def test_system_timezone_from_tz_variable(tmp_path):
    assert (
        system_timezone(
            env={"TZ": "Europe/Paris"}, localtime=tmp_path / "x", timezone_file=tmp_path / "y"
        )
        == PARIS
    )
    assert (
        system_timezone(
            env={"TZ": ":Europe/Paris"}, localtime=tmp_path / "x", timezone_file=tmp_path / "y"
        )
        == PARIS
    )


def test_system_timezone_from_localtime_link(tmp_path):
    zoneinfo = tmp_path / "usr" / "share" / "zoneinfo" / "Europe"
    zoneinfo.mkdir(parents=True)
    (zoneinfo / "Paris").write_text("x")
    link = tmp_path / "localtime"
    link.symlink_to(zoneinfo / "Paris")
    assert system_timezone(env={}, localtime=link, timezone_file=tmp_path / "none") == PARIS


def test_system_timezone_from_timezone_file(tmp_path):
    f = tmp_path / "timezone"
    f.write_text("Europe/Paris\n")
    assert system_timezone(env={}, localtime=tmp_path / "none", timezone_file=f) == PARIS


def test_system_timezone_falls_back_to_a_fixed_offset(tmp_path):
    tz = system_timezone(env={}, localtime=tmp_path / "none", timezone_file=tmp_path / "none2")
    assert datetime.now(tz).utcoffset() is not None
    assert not isinstance(tz, ZoneInfo)
