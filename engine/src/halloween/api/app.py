"""Application FastAPI : le moteur complet derrière une API HTTP sous `/api`, plus l'interface.

Le moteur (`Engine`) démarre et s'arrête avec l'application (lifespan). Toutes les routes de
`/api` exigent le jeton, sauf `/api/health` (vivacité seulement).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from halloween import __version__
from halloween.api import components, ha, images, programs, runs, schemas
from halloween.api.auth import make_auth
from halloween.api.deps import EngineDep
from halloween.api.static import placeholder_response, static_app
from halloween.app import Engine, StartupError, StartupReport
from halloween.backend import Backend
from halloween.drivers.homeassistant import HttpHAClient
from halloween.events import SnapshotEvent
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
            engine.hub.close()  # termine les connexions WebSocket avant l'arrêt
            await engine.stop()

    app = FastAPI(
        title="Déco Halloween",
        version=__version__,
        description="API du moteur : composants, programmes, exécution, déclencheurs.",
        lifespan=lifespan,
    )
    require_token, websocket_allowed = make_auth(token)

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
    api.include_router(programs.router)
    api.include_router(runs.router)
    public.include_router(images.public_router)
    app.state.api_router = api
    app.include_router(public)
    app.include_router(api)

    @app.websocket("/api/events")
    async def events(websocket: WebSocket) -> None:
        """Flux temps réel (JSON, un événement par message). Jeton : `?token=` ou en-tête Bearer.

        Premier message : `snapshot` (état courant) ; ensuite `run_started`, `node_started`,
        `node_finished`, `run_ended`, `component_changed`, `button_event`, `error`, `lock_changed`.
        """
        if not websocket_allowed(websocket):
            await websocket.close(code=1008)
            return
        engine: Engine = websocket.app.state.engine
        await websocket.accept()
        subscription = engine.hub.subscribe()
        try:
            snapshot = SnapshotEvent(
                runs=[run.to_json() for run in engine.manager.active] if engine.manager else [],
                relays={r.id: engine.relays.is_on(r.id) for r in engine.config.relays}
                if engine.manager
                else {},
            )
            await websocket.send_json(snapshot.model_dump(mode="json"))

            async def forward() -> None:
                async for event in subscription:
                    await websocket.send_json(event)

            async def watch_client() -> None:
                while True:  # détecte la déconnexion même sans événement à envoyer
                    await websocket.receive_text()

            tasks = [asyncio.ensure_future(forward()), asyncio.ensure_future(watch_client())]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        except WebSocketDisconnect:
            pass
        finally:
            subscription.close()

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
