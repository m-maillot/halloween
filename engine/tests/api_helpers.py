"""Outils communs aux tests de l'API : un Pi simulé et un client HTTP authentifié."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from halloween.api import create_app
from halloween.backend import Backend
from halloween.config import AppConfig
from halloween.drivers import FakeButtonDriver, FakeHAClient, FakeRelayDriver
from halloween.program import Program
from halloween.store import Store

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "jeton-de-test-0123456789"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class Pi:
    """Pilotes fictifs + dossier de données ; construit l'application et un client authentifié."""

    def __init__(self, tmp_path: Path, config_patch: dict | None = None):
        raw = json.loads((ROOT / "deploy" / "config.example.json").read_text(encoding="utf-8"))
        raw.update(config_patch or {})
        self.store = Store(tmp_path / "data")
        self.store.initialize()
        self.store.save_config(AppConfig.model_validate(raw))
        self.relays: FakeRelayDriver | None = None
        self.buttons: FakeButtonDriver | None = None
        self.ha: FakeHAClient | None = None

    def backend(self) -> Backend:
        def relays(config):
            self.relays = FakeRelayDriver.from_config(config)
            return self.relays

        def buttons(config):
            self.buttons = FakeButtonDriver(b.id for b in config.buttons)
            return self.buttons

        def ha(_config, _write, _dry):
            self.ha = FakeHAClient()
            return self.ha

        return Backend(relays, buttons, ha)

    def app(self, **kwargs):
        return create_app(
            self.store, self.backend(), token=TOKEN, write=lambda _line: None, **kwargs
        )

    def client(self, **kwargs) -> TestClient:
        client = TestClient(self.app(**kwargs), headers=AUTH)
        return client

    def program(self, id_: str, *children: dict, **kw) -> Program:
        root = {"id": "n", "type": "sequence", "children": list(children)}
        prog = Program.model_validate(
            {"id": id_, "name": id_, "scripts": [{"id": "s", "root": root}], **kw}
        )
        self.store.save_program(prog)
        return prog
