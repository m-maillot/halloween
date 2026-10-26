import json
import os
import stat
from pathlib import Path

import pytest

from halloween.config import AppConfig
from halloween.program import Program
from halloween.store import RevisionConflict, Store, write_atomic

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__file__).parent / "data"


@pytest.fixture
def store(tmp_path) -> Store:
    s = Store(tmp_path / "data")
    s.initialize()
    return s


def program(id_="p", seconds=1, **kw) -> Program:
    root = {"id": "n", "type": "wait", "seconds": seconds}
    return Program.model_validate(
        {"id": id_, "name": id_, "scripts": [{"id": "s", "root": root}], **kw}
    )


# ------------------------------------------------------------------ écriture atomique


def test_write_atomic_creates_parents_and_sets_mode(tmp_path):
    target = tmp_path / "a" / "b.txt"
    write_atomic(target, "hello", 0o600)
    assert target.read_text() == "hello"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_crash_during_replace_keeps_the_old_file_and_leaves_no_temp(tmp_path, monkeypatch):
    target = tmp_path / "f.json"
    write_atomic(target, "ancien")

    def crash(*_args):
        raise OSError("coupure de courant")

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(OSError, match="coupure"):
        write_atomic(target, "nouveau")
    monkeypatch.undo()
    assert target.read_text() == "ancien"
    assert [p.name for p in tmp_path.iterdir()] == ["f.json"]


def test_crash_while_writing_keeps_the_old_file(tmp_path, monkeypatch):
    target = tmp_path / "f.json"
    write_atomic(target, "ancien")
    monkeypatch.setattr(os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("disque plein")))
    with pytest.raises(OSError):
        write_atomic(target, "nouveau")
    monkeypatch.undo()
    assert target.read_text() == "ancien"
    assert [p.name for p in tmp_path.iterdir()] == ["f.json"]


# ------------------------------------------------------------------ configuration et déclencheurs


def test_missing_config_is_empty(store):
    assert store.load_config() == AppConfig()


def test_config_round_trip_and_permissions(store):
    config = AppConfig.model_validate(
        json.loads((ROOT / "deploy" / "config.example.json").read_text(encoding="utf-8"))
        | {"home_assistant": {"url": "http://ha:8123", "token": "secret"}}
    )
    store.save_config(config)
    assert store.load_config() == config
    assert stat.S_IMODE(store.config_path.stat().st_mode) == 0o600  # contient le jeton
    assert "Fantôme" in store.config_path.read_text(encoding="utf-8")  # accents non échappés


def test_triggers_round_trip(store):
    assert store.load_triggers() == []
    triggers = [{"id": "t1", "source": "button", "button": "bouton_principal", "event": "short"}]
    store.save_triggers(triggers)
    assert store.load_triggers() == triggers


# ------------------------------------------------------------------ programmes et révisions


def test_new_program_gets_revision_1_and_round_trips(store):
    saved = store.save_program(program(revision=42))  # la révision du corps est ignorée
    assert saved.revision == 1
    assert store.get_program("p") == saved
    assert json.loads(store.program_path("p").read_text(encoding="utf-8"))["schema"] == 1


def test_revision_increments_on_each_save(store):
    first = store.save_program(program())
    second = store.save_program(program(seconds=2), expected_revision=first.revision)
    third = store.save_program(program(seconds=3), expected_revision=second.revision)
    assert (first.revision, second.revision, third.revision) == (1, 2, 3)
    assert store.get_program("p").scripts[0].root.seconds == 3


def test_stale_revision_is_refused_and_file_unchanged(store):
    first = store.save_program(program(seconds=1))
    store.save_program(program(seconds=2), expected_revision=first.revision)
    with pytest.raises(RevisionConflict) as exc:
        store.save_program(program(seconds=99), expected_revision=first.revision)
    assert (exc.value.expected, exc.value.current) == (1, 2)
    assert store.get_program("p").scripts[0].root.seconds == 2


def test_overwriting_without_revision_is_refused(store):
    store.save_program(program())
    with pytest.raises(RevisionConflict):
        store.save_program(program())


def test_creating_with_a_revision_is_refused(store):
    with pytest.raises(RevisionConflict):
        store.save_program(program(), expected_revision=3)
    assert store.get_program("p") is None
    store.save_program(program(), expected_revision=0)  # 0 = « je crée »


def test_delete_program(store):
    store.save_program(program())
    assert store.delete_program("p") is True
    assert store.delete_program("p") is False
    assert store.get_program("p") is None


def test_load_programs(store):
    store.save_program(program("a"))
    store.save_program(program("b"))
    loaded = store.load_programs()
    assert sorted(loaded.programs) == ["a", "b"] and loaded.issues == []


def test_invalid_files_are_reported_without_blocking_the_others(store):
    store.save_program(program("ok"))
    (store.programs_dir / "cassé.json").write_text("{pas du json", encoding="utf-8")
    (store.programs_dir / "mauvais.json").write_text(
        json.dumps(
            {
                "id": "mauvais",
                "name": "M",
                "scripts": [{"id": "s", "root": {"id": "n", "type": "wait", "seconds": -1}}],
            }
        ),
        encoding="utf-8",
    )
    (store.programs_dir / "autre-nom.json").write_text(
        json.dumps(program("vrai-id").to_json()), encoding="utf-8"
    )
    loaded = store.load_programs()
    assert list(loaded.programs) == ["ok"]
    by_code = {i.code: i for i in loaded.issues}
    assert set(by_code) == {"unreadable_file", "invalid_file", "id_mismatch"}
    assert by_code["invalid_file"].node_id == "n"  # localisé sur le bloc fautif
    # les fichiers invalides sont laissés intacts
    assert (store.programs_dir / "cassé.json").read_text(encoding="utf-8") == "{pas du json"


def test_leftover_temp_files_are_ignored_and_cleaned_at_startup(store):
    store.save_program(program("ok"))
    leftover = store.programs_dir / ".ok.json.abc123.tmp"
    leftover.write_text("à moitié écrit", encoding="utf-8")
    assert list(store.load_programs().programs) == ["ok"]
    store.initialize()
    assert not leftover.exists()


def test_program_ids_cannot_escape_the_data_directory(store):
    with pytest.raises(Exception, match="id"):
        program("../evil")


def test_programs_dir_missing_gives_empty_result(tmp_path):
    loaded = Store(tmp_path / "nothing").load_programs()
    assert loaded.programs == {} and loaded.issues == []


def test_example_programs_survive_a_save_load_cycle(store):
    for name in ("scenario_principal.json", "ambiance.json"):
        original = Program.model_validate(json.loads((DATA / name).read_text(encoding="utf-8")))
        saved = store.save_program(original)
        assert store.get_program(original.id) == saved
        assert saved.model_dump(exclude={"revision"}) == original.model_dump(exclude={"revision"})
