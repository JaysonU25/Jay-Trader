from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from marketpulse.api import deps
from marketpulse.api.cache import CacheControlMiddleware
from marketpulse.api.routes import assets, health, series
from marketpulse.config import get_settings
from marketpulse.db.session import make_engine, make_session_factory


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.database_url)
        factory = make_session_factory(engine)

        async def session_dependency():
            async with factory() as session:
                yield session

        app.dependency_overrides[deps.get_session] = session_dependency
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Market Pulse API", version="1.0.0", lifespan=lifespan)
    app.add_middleware(CacheControlMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/v1")
    app.include_router(assets.router, prefix="/v1")
    app.include_router(series.router, prefix="/v1")
    return app


app = create_app()
