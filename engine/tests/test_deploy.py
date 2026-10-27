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
