import os
from unittest import mock

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from fastapi_app import create_app
from fastapi_app.postgres_engine import create_postgres_engine_from_env

# Always use localhost for testing
POSTGRES_HOST = "localhost"
POSTGRES_USERNAME = os.getenv("POSTGRES_USERNAME", "admin")
POSTGRES_DATABASE = os.getenv("POSTGRES_DATABASE", os.getenv("TEST_DB_NAME", "observations_test"))
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
POSTGRES_SSL = "prefer"
POSTGRESQL_DATABASE_URL = (
    f"postgresql+asyncpg://{POSTGRES_USERNAME}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}/{POSTGRES_DATABASE}"
)


@pytest.fixture(scope="session")
def monkeypatch_session():
    with pytest.MonkeyPatch.context() as monkeypatch_session:
        yield monkeypatch_session


@pytest.fixture(scope="session")
def mock_session_env(monkeypatch_session):
    """Mock the environment variables for testing."""
    # Note that this does *not* clear existing env variables by default-
    # we used to specify clear=True but this caused issues with Playwright tests
    # https://github.com/microsoft/playwright-python/issues/2506
    with mock.patch.dict(os.environ):
        # Database
        monkeypatch_session.setenv("POSTGRES_HOST", POSTGRES_HOST)
        monkeypatch_session.setenv("POSTGRES_USERNAME", POSTGRES_USERNAME)
        monkeypatch_session.setenv("POSTGRES_DATABASE", POSTGRES_DATABASE)
        monkeypatch_session.setenv("POSTGRES_PASSWORD", POSTGRES_PASSWORD)
        monkeypatch_session.setenv("POSTGRES_SSL", POSTGRES_SSL)

        yield


@pytest_asyncio.fixture(scope="session")
async def app(mock_session_env):
    """Create a FastAPI app."""
    app = create_app(testing=True)
    return app


@pytest_asyncio.fixture(scope="function")
async def test_client(app):
    """Create a test client."""
    with TestClient(app) as test_client:
        yield test_client


@pytest_asyncio.fixture(scope="function")
async def db_session(mock_session_env):
    """Create a new database session with a rollback at the end of the test."""
    engine = await create_postgres_engine_from_env()
    async_sesion = async_sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = async_sesion()
    await session.begin()
    yield session
    await session.rollback()
    await session.close()
    await engine.dispose()
