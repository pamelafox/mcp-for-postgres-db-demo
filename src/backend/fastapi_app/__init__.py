import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import fastapi
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from fastapi_app.dependencies import (
    create_async_sessionmaker,
    get_azure_credential,
)
from fastapi_app.postgres_engine import create_postgres_engine_from_env

logger = logging.getLogger("ragapp")


@asynccontextmanager
async def lifespan(app: fastapi.FastAPI) -> AsyncIterator[None]:
    """Application lifespan.

    We previously yielded a state object for request.state access, but the
    starlette test client used by Schemathesis does not advertise support for
    lifespan state extension, causing a RuntimeError when a value is yielded.

    To remain compatible, we instead attach resources to app.state and yield
    no value. Downstream code should use request.app.state.
    """
    azure_credential = None
    if os.getenv("POSTGRES_HOST", "").endswith(".database.azure.com"):
        azure_credential = await get_azure_credential()
    engine = await create_postgres_engine_from_env(azure_credential)
    sessionmaker = await create_async_sessionmaker(engine)
    app.state.sessionmaker = sessionmaker  # type: ignore[attr-defined]
    try:
        yield
    finally:
        await engine.dispose()


def create_app(testing: bool = False):
    if not testing:
        load_dotenv(override=True)
    logging.basicConfig(level=logging.INFO)

    app = fastapi.FastAPI(docs_url="/docs", lifespan=lifespan)

    from fastapi_app.api import routes

    app.include_router(routes.router)

    return app
