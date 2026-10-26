import asyncio
import io
import json

import pytest

from halloween.log import get_logger, log_context, setup_logging


@pytest.fixture
def lines():
    stream = io.StringIO()
    setup_logging("DEBUG", stream)

    def read() -> list[dict]:
        return [json.loads(line) for line in stream.getvalue().splitlines()]

    yield read
    setup_logging()  # remet un handler propre pour les autres tests


def test_line_is_valid_json_with_base_fields(lines):
    get_logger("test").info("bonjour %s", "monde")
    (entry,) = lines()
    assert entry["message"] == "bonjour monde"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "halloween.test"
    assert entry["ts"].endswith("+00:00")


def test_no_context_fields_without_context(lines):
    get_logger("test").info("x")
    (entry,) = lines()
    assert not {"run_id", "script_id", "node_id"} & entry.keys()


def test_context_fields_are_added_and_nested(lines):
    log = get_logger("test")
    with log_context(run_id="r1", script_id="s1"):
        log.info("début")
        with log_context(node_id="n3"):
            log.info("bloc")
        log.info("fin du bloc")
    log.info("hors contexte")
    a, b, c, d = lines()
    assert (a["run_id"], a["script_id"], "node_id" in a) == ("r1", "s1", False)
    assert b["node_id"] == "n3" and b["run_id"] == "r1"
    assert "node_id" not in c and c["run_id"] == "r1"
    assert "run_id" not in d


def test_extra_fields_and_non_serializable_values(lines):
    get_logger("test").info("appel", extra={"component": "fantome", "obj": object()})
    (entry,) = lines()
    assert entry["component"] == "fantome"
    assert isinstance(entry["obj"], str)


def test_base_fields_cannot_be_overridden(lines):
    with log_context(level="CONTEXT", logger="ctx"):
        get_logger("test").warning("m", extra={"ts": "faux"})
    (entry,) = lines()
    assert entry["level"] == "WARNING"
    assert entry["logger"] == "halloween.test"
    assert entry["ts"] != "faux"


def test_exception_is_logged(lines):
    try:
        raise ValueError("boum")
    except ValueError:
        get_logger("test").exception("échec")
    (entry,) = lines()
    assert "ValueError: boum" in entry["exc"]


def test_accents_are_not_escaped():
    stream = io.StringIO()
    setup_logging("INFO", stream)
    get_logger("test").info("Épouvantail éteint")
    assert "Épouvantail" in stream.getvalue()
    setup_logging()


def test_setup_is_idempotent():
    stream = io.StringIO()
    setup_logging("INFO", stream)
    setup_logging("INFO", stream)
    get_logger("test").info("une seule fois")
    assert len(stream.getvalue().splitlines()) == 1
    setup_logging()


async def test_concurrent_tasks_keep_their_own_run_id(lines):
    log = get_logger("test")

    async def run(run_id: str):
        with log_context(run_id=run_id):
            log.info("avant")
            await asyncio.sleep(0)
            log.info("après")

    await asyncio.gather(run("a"), run("b"))
    entries = lines()
    assert len(entries) == 4
    assert {e["run_id"] for e in entries} == {"a", "b"}
    for run_id in ("a", "b"):
        assert [e["message"] for e in entries if e["run_id"] == run_id] == ["avant", "après"]


async def test_child_task_inherits_context(lines):
    async def child():
        get_logger("test").info("dans la tâche")

    with log_context(run_id="r9"):
        await asyncio.create_task(child())
    (entry,) = lines()
    assert entry["run_id"] == "r9"
