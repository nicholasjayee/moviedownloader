from contextlib import asynccontextmanager

from a2wsgi import WSGIMiddleware
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from moviebox_app.api.catalog import router as catalog_router
from moviebox_app.api.playback import router as playback_router
from moviebox_app.api.routes import router
from moviebox_app.api.security import RequestBoundary
from moviebox_app.catalog.client import MovieboxClient
from moviebox_app.catalog.models import CatalogError, TitleNotFound
from moviebox_app.catalog.repository import TitleRepository
from moviebox_app.catalog.service import CatalogService
from moviebox_app.config import Settings
from moviebox_app.downloads.manager import DownloadManager, JobConflict
from moviebox_app.playback.service import PlaybackService
from moviebox_app.storage.repository import DownloadRepository
from moviebox_app.web import create_web_app


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = MovieboxClient(settings)
        await client.open()
        titles = TitleRepository(settings.database_path)
        playback = PlaybackService(settings)
        try:
            await playback.open()
            app.state.playback = playback
            await titles.open()
            catalog = CatalogService(client, titles)
            app.state.catalog = catalog
            service = DownloadManager(
                settings, DownloadRepository(settings.database_path), catalog.prepare_download
            )
            await service.start()
            app.state.manager = service
            try:
                yield
            finally:
                await service.close()
        finally:
            await playback.close()
            await titles.close()
            await client.close()

    app = FastAPI(
        title="Moviebox", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.add_middleware(RequestBoundary)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @app.exception_handler(KeyError)
    async def not_found(request: Request, exc: KeyError):
        return JSONResponse({"detail": "Download or file not found."}, status_code=404)

    @app.exception_handler(JobConflict)
    async def conflict(request: Request, exc: JobConflict):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(CatalogError)
    async def provider_error(request: Request, exc: CatalogError):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.exception_handler(TitleNotFound)
    async def missing_title(request: Request, exc: TitleNotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    app.include_router(router)
    app.include_router(catalog_router)
    app.include_router(playback_router)
    app.mount("/", WSGIMiddleware(create_web_app()))
    return app
