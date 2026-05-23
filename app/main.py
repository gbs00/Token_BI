from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.container import ServiceContainer
from app.routes.api_routes import router as api_router
from app.routes.page_routes import router as page_router


def create_app(
    settings: Optional[Settings] = None,
    container: Optional[ServiceContainer] = None,
) -> FastAPI:
    settings = settings or get_settings()

    resolved_container = container or ServiceContainer(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            resolved_container.startup()
            yield
        finally:
            resolved_container.shutdown()

    app = FastAPI(title="Token BI", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.container = resolved_container

    app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")
    app.include_router(page_router)
    app.include_router(api_router)
    return app


app = create_app()
