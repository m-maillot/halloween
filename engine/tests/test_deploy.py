"""Unité systemd et script d'installation (vérifiés sans les exécuter pour de bon)."""

from __future__ import annotations

import configparser
import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
UNIT = DEPLOY / "halloween-engine.service"
INSTALL = DEPLOY / "install.sh"


def unit() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # les directives systemd sont sensibles à la casse
    parser.read(UNIT, encoding="utf-8")
    return parser


def test_unit_restarts_always_and_has_a_watchdog():
    service = unit()["Service"]
    assert service["Type"] == "notify" and service["NotifyAccess"] == "main"
    assert service["Restart"] == "always"
    assert int(service["WatchdogSec"]) >= 5
    assert int(service["TimeoutStopSec"]) > 0
    assert service["SuccessExitStatus"] == "130"  # code de sortie sur SIGTERM (voir cli.py)
    assert "halloween-cli api" in service["ExecStart"]
    assert service["StateDirectory"] == "halloween"
    assert "gpio" in service["SupplementaryGroups"]
    assert unit()["Install"]["WantedBy"] == "multi-user.target"


def test_unit_does_not_run_as_root():
    assert unit()["Service"]["User"] not in ("", "root")


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="systemd-analyze absent")
def test_unit_is_accepted_by_systemd_analyze(tmp_path):
    # Seul l'exécutable (absent hors du Pi) est remplacé : tout le reste est vérifié tel quel.
    text = UNIT.read_text(encoding="utf-8")
    text = "\n".join(
        "ExecStart=/bin/true" if line.startswith("ExecStart=") else line
        for line in text.splitlines()
    )
    copy = tmp_path / "halloween-engine.service"
    copy.write_text(text, encoding="utf-8")
    result = subprocess.run(
        ["systemd-analyze", "verify", str(copy)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0 and result.stderr.strip() == "", result.stderr


def test_install_script_is_valid_bash_and_executable():
    assert INSTALL.stat().st_mode & 0o111
    subprocess.run(["bash", "-n", str(INSTALL)], check=True)


def test_install_dry_run_shows_every_step_and_changes_nothing(tmp_path):
    env = {
        "PATH": "/usr/bin:/bin",
        "OPT_DIR": str(tmp_path / "opt"),
        "DATA_DIR": str(tmp_path / "data"),
        "ETC_DIR": str(tmp_path / "etc"),
        "UNIT_DIR": str(tmp_path / "units"),
    }
    result = subprocess.run(
        [str(INSTALL), "--dry-run"], capture_output=True, text=True, env=env, check=False
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    for expected in (
        "useradd --system",
        "usermod -aG gpio",
        "-m venv",
        "pip install",
        "engine[pi]",
        f"{tmp_path}/data/config.json",
        "halloween-engine.service",
        "systemctl daemon-reload",
        "systemctl enable halloween-engine",
        "systemctl restart halloween-engine",
    ):
        assert expected in out, expected
    assert not any(tmp_path.iterdir())  # rien n'a été créé


def test_install_uninstall_dry_run_keeps_the_data(tmp_path):
    result = subprocess.run(
        [str(INSTALL), "--uninstall", "--dry-run"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert "systemctl disable --now halloween-engine" in result.stdout
    assert "Conservés" in result.stdout and "rm -f" in result.stdout
    assert "rm -rf" not in result.stdout


def test_install_rejects_unknown_options():
    result = subprocess.run(
        [str(INSTALL), "--nimporte"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 2


def test_install_never_overwrites_the_existing_config():
    text = INSTALL.read_text(encoding="utf-8")
    assert 'if [ ! -e "$DATA_DIR/config.json" ]' in text


# ------------------------------------------------------------------ interface et sauvegarde

BACKUP = DEPLOY / "backup.sh"


def test_unit_serves_the_built_interface_by_default():
    text = UNIT.read_text(encoding="utf-8")
    assert "Environment=HALLOWEEN_UI_DIR=/opt/halloween/ui" in text


def test_install_dry_run_copies_the_interface_next_to_then_swaps_it(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "OPT_DIR": str(tmp_path / "opt"), "UI_DIST": "/chemin/dist"}
    result = subprocess.run(
        [str(INSTALL), "--dry-run"], capture_output=True, text=True, env=env, check=False
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert f"cp -r /chemin/dist {tmp_path}/opt/ui.new" in out
    assert out.index("ui.new") < out.index(f"mv {tmp_path}/opt/ui.new {tmp_path}/opt/ui")


def test_backup_script_is_valid_bash_and_executable():
    assert BACKUP.stat().st_mode & 0o111
    subprocess.run(["bash", "-n", str(BACKUP)], check=True)


def make_data(root: Path) -> Path:
    data = root / "var" / "halloween"
    (data / "programs").mkdir(parents=True)
    (data / "logs").mkdir()
    (data / "images").mkdir()
    (data / "config.json").write_text('{"relays": []}', encoding="utf-8")
    (data / "programs" / "scene.json").write_text('{"id": "scene"}', encoding="utf-8")
    (data / "images" / "abc.webp").write_bytes(b"RIFF")
    (data / "lock.json").write_text('{"locked": false}', encoding="utf-8")
    (data / "logs" / "halloween.log").write_text("bruit\n", encoding="utf-8")
    return data


def run_backup(args: list[str], data: Path, ctl: Path):
    env = {"PATH": "/usr/bin:/bin", "DATA_DIR": str(data), "SYSTEMCTL": str(ctl)}
    return subprocess.run(
        [str(BACKUP), *args], capture_output=True, text=True, env=env, check=False
    )


@pytest.fixture
def systemctl(tmp_path) -> Path:
    """Un faux systemctl qui note ses appels."""
    script = tmp_path / "systemctl"
    script.write_text(f'#!/bin/sh\necho "$@" >> {tmp_path}/ctl.log\n', encoding="utf-8")
    script.chmod(0o755)
    return script


def test_backup_contains_the_data_but_not_the_logs_and_is_private(tmp_path, systemctl):
    import tarfile

    data = make_data(tmp_path)
    result = run_backup(["--out", str(tmp_path / "sauvegardes")], data, systemctl)
    assert result.returncode == 0, result.stderr
    (archive,) = (tmp_path / "sauvegardes").glob("halloween-sauvegarde-*.tar.gz")
    assert archive.stat().st_mode & 0o777 == 0o600  # contient des secrets
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
    expected = {"halloween/config.json", "halloween/programs/scene.json", "halloween/lock.json"}
    assert expected <= names
    assert "halloween/images/abc.webp" in names
    assert not any("logs" in n for n in names)
    assert "jetons" in result.stdout  # l'avertissement est affiché


def test_backup_refuses_when_there_is_no_data(tmp_path, systemctl):
    result = run_backup([], tmp_path / "vide" / "halloween", systemctl)
    assert result.returncode == 1 and "config.json absent" in result.stderr


def test_restore_replaces_the_data_keeps_the_previous_ones_and_restarts_the_service(
    tmp_path, systemctl
):
    data = make_data(tmp_path)
    run_backup(["--out", str(tmp_path / "s")], data, systemctl)
    (archive,) = (tmp_path / "s").glob("*.tar.gz")
    # on abîme les données, puis on restaure
    (data / "config.json").write_text('{"relays": ["abîmé"]}', encoding="utf-8")
    (data / "programs" / "scene.json").unlink()
    result = run_backup(["--restore", str(archive)], data, systemctl)
    assert result.returncode == 0, result.stderr
    assert (data / "config.json").read_text(encoding="utf-8") == '{"relays": []}'
    assert (data / "programs" / "scene.json").exists()
    (kept,) = tmp_path.glob("var/halloween.avant-restauration-*")  # rien n'est perdu
    assert "abîmé" in (kept / "config.json").read_text(encoding="utf-8")
    calls = (tmp_path / "ctl.log").read_text(encoding="utf-8").splitlines()
    assert calls == ["stop halloween-engine", "start halloween-engine"]


def test_restore_rejects_a_file_that_is_not_a_backup(tmp_path, systemctl):
    import tarfile

    data = make_data(tmp_path)
    junk = tmp_path / "autre.tar.gz"
    with tarfile.open(junk, "w:gz") as tar:
        tar.add(data / "programs" / "scene.json", arcname="autre/scene.json")
    result = run_backup(["--restore", str(junk)], data, systemctl)
    assert result.returncode == 1 and "pas une sauvegarde" in result.stderr
    assert not (tmp_path / "ctl.log").exists()  # le service n'a pas été touché
    assert (data / "config.json").exists()
