"""Application FastAPI : le moteur complet derrière une API HTTP sous `/api`, plus l'interface.

Le moteur (`Engine`) démarre et s'arrête avec l'application (lifespan). Toutes les routes de
`/api` exigent le jeton, sauf `/api/health` (vivacité seulement).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from halloween import __version__
from halloween.api import components, ha, images, schemas
from halloween.api.auth import make_dependencies
from halloween.api.deps import EngineDep
from halloween.api.static import placeholder_response, static_app
from halloween.app import Engine, StartupError, StartupReport
from halloween.backend import Backend
from halloween.drivers.homeassistant import HttpHAClient
from halloween.store import Store


def create_app(
    store: Store,
    backend: Backend,
    *,
    token: str,
    static_dir: Path | None = None,
    ha_dry_run: bool = False,
    clock: Callable[[], datetime] | None = None,
    write: Callable[[str], None] = print,
    on_ready: Callable[[StartupReport], None] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = Engine(store, backend, write, ha_dry_run, clock)
        try:
            report = await engine.start()
        except StartupError as exc:
            app.state.startup_error = exc  # la commande qui nous lance l'affiche
            raise
        app.state.engine = engine
        if on_ready is not None:
            on_ready(report)
        try:
            yield
        finally:
            await engine.stop()

    app = FastAPI(
        title="Déco Halloween",
        version=__version__,
        description="API du moteur : composants, programmes, exécution, déclencheurs.",
        lifespan=lifespan,
    )
    require_token, require_ws_token = make_dependencies(token)
    app.state.require_ws_token = require_ws_token

    public = APIRouter(prefix="/api")

    @public.get("/health", response_model=schemas.Health, tags=["système"], operation_id="health")
    async def health() -> schemas.Health:
        """Vivacité du service (sans authentification, sans détail)."""
        return schemas.Health(ok=True)

    api = APIRouter(
        prefix="/api",
        dependencies=[Depends(require_token)],
        responses={401: {"description": "Jeton d'API manquant ou invalide"}},
    )

    @api.get("/status", response_model=schemas.Status, tags=["système"], operation_id="get_status")
    async def get_status(engine: EngineDep) -> schemas.Status:
        """État du moteur : runs, relais, connexion Home Assistant, problèmes au démarrage."""
        ha = engine.ha
        real = isinstance(ha, HttpHAClient)
        settings = engine.config.home_assistant
        return schemas.Status(
            version=__version__,
            runs=[schemas.RunOut(**run.to_json()) for run in engine.manager.active],
            relays={r.id: engine.relays.is_on(r.id) for r in engine.config.relays},
            home_assistant=schemas.HomeAssistantStatus(
                mode="real" if real else "dry-run",
                url=settings.url if settings else None,
                last_ok_at=ha.last_ok_at if real else None,
                last_error=ha.last_error if real else None,
            ),
            startup_issues=[schemas.IssueOut.from_issue(i) for i in engine.report.issues],
        )

    api.include_router(components.router)
    api.include_router(ha.router)
    api.include_router(images.router)
    public.include_router(images.public_router)
    app.state.api_router = api
    app.include_router(public)
    app.include_router(api)

    ui = static_app(static_dir)
    if ui is not None:
        app.mount("/", ui, name="ui")
    else:

        @app.get("/{path:path}", include_in_schema=False, response_class=HTMLResponse)
        async def placeholder(path: str):  # noqa: ARG001
            if path.startswith("api/") or path == "api":
                raise HTTPException(404, "route d'API inconnue")
            return placeholder_response()

    return app
