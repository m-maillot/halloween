"""Contrat OpenAPI de l'API : génération, enrichissement, export.

Le fichier exporté (`docs/openapi.json`) est **versionné** et sert de contrat à l'interface, qui en
génère son client TypeScript. Un test échoue si l'API change sans que le fichier soit régénéré
(`make openapi`).

L'OpenAPI ne sait pas décrire un WebSocket : les messages de `/api/events` sont ajoutés comme
schémas (`Event` et chaque type d'événement) avec une extension `x-websocket`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import TypeAdapter

from halloween.api import create_app
from halloween.backend import gpio_backend
from halloween.events import EVENT_MODELS, Event
from halloween.store import Store

TAGS = [
    {"name": "système", "description": "Vivacité et état du moteur"},
    {"name": "composants", "description": "Relais, boutons, lumières, interrupteurs et catalogue"},
    {"name": "home-assistant", "description": "Connexion à Home Assistant et entités"},
    {"name": "images", "description": "Images des composants"},
    {"name": "programmes", "description": "Programmes (blocs), validation et simulation"},
    {"name": "exécution", "description": "Runs, arrêts et déclencheurs"},
]

# Routes sans authentification (le reste exige le jeton).
PUBLIC_OPERATIONS = {"health", "get_image"}


def build_openapi(app: FastAPI) -> dict[str, Any]:
    """OpenAPI de l'application, complété (événements WebSocket, sécurité, étiquettes)."""
    # Contrat de base de FastAPI (copié : son cache ne doit pas être modifié).
    spec = json.loads(json.dumps(FastAPI.openapi(app)))
    schemas = spec.setdefault("components", {}).setdefault("schemas", {})

    # Schémas des événements du WebSocket.
    union = TypeAdapter(Event).json_schema(ref_template="#/components/schemas/{model}")
    for definition, schema in union.pop("$defs", {}).items():
        schemas.setdefault(definition, schema)
    for model in EVENT_MODELS:
        schemas[model.__name__] = model.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
    schemas["Event"] = union
    spec["x-websocket"] = {
        "path": "/api/events",
        "description": (
            "Flux temps réel. Authentification : paramètre `?token=` ou en-tête `Authorization`. "
            "Le premier message est un `snapshot`, puis un objet JSON `Event` par message."
        ),
        "message": {"$ref": "#/components/schemas/Event"},
    }

    # Sécurité : jeton Bearer partout, sauf les routes publiques.
    spec["tags"] = TAGS
    spec["security"] = [{"HTTPBearer": []}]
    for methods in spec["paths"].values():
        for operation in methods.values():
            if isinstance(operation, dict) and operation.get("operationId") in PUBLIC_OPERATIONS:
                operation["security"] = []
    return spec


def openapi_document() -> dict[str, Any]:
    """Construit l'application (sans la démarrer) et retourne son contrat."""
    app = create_app(Store(Path("/nonexistent")), gpio_backend(), token="x" * 16)
    return build_openapi(app)


def render(spec: dict[str, Any]) -> str:
    return json.dumps(spec, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    """`python -m halloween.api.openapi [--check] [--output docs/openapi.json]`."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Exporte le contrat OpenAPI.")
    parser.add_argument("--output", type=Path, default=Path("docs/openapi.json"))
    parser.add_argument("--check", action="store_true", help="échoue si le fichier est périmé")
    args = parser.parse_args(argv)
    rendered = render(openapi_document())
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if current != rendered:
            print(f"{args.output} est périmé : relancer `make openapi`.", file=sys.stderr)
            return 1
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"{args.output} écrit ({len(rendered) // 1024} Ko)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
