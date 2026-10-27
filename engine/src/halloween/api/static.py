"""Service de l'interface (build statique), repli `index.html` pour les routes de l'application."""

from __future__ import annotations

from pathlib import Path

from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

PLACEHOLDER = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Déco Halloween</title></head>
<body><h1>Déco Halloween</h1>
<p>Le moteur fonctionne, mais l'interface n'est pas installée sur cet appareil.</p>
<p>L'API est disponible sous <code>/api</code>.</p></body></html>
"""


class SPAStaticFiles(StaticFiles):
    """Fichiers statiques ; toute route inconnue (hors `/api`) renvoie `index.html`."""

    async def get_response(self, path: str, scope) -> Response:
        if path.startswith("api/") or path == "api":
            raise HTTPException(404, "route d'API inconnue")
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


def placeholder_response() -> HTMLResponse:
    return HTMLResponse(PLACEHOLDER)


def static_app(directory: Path | None) -> SPAStaticFiles | None:
    if directory is not None and (directory / "index.html").is_file():
        return SPAStaticFiles(directory=directory, html=True)
    return None
