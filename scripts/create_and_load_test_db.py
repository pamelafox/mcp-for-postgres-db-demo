"""Utility script to create a dedicated test database, apply schema, and ingest observations.

This is intended for integration / large-data test runs so regular unit tests
can remain fast. It will:
  1. Connect to the *server* (using a maintenance database like 'postgres').
  2. Create the target test database if it does not exist.
  3. Run the schema creation (tables, extensions, indexes).
  4. Ingest the full observations CSV via existing ingestion script logic.

Environment variables honored (can be overridden by CLI flags):
  TEST_DB_NAME (default: observations_test)
  POSTGRES_HOST (default: localhost)
  POSTGRES_USERNAME (default: postgres)
  POSTGRES_PASSWORD (default: postgres)
  POSTGRES_PORT (default: 5432)

Example usage:
  python scripts/create_and_load_test_db.py \
      --csv data/observations.csv \
      --test-db observations_test

After running, set for pytest session:
  export POSTGRES_DATABASE=observations_test
  pytest -m full
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

from dotenv import load_dotenv
from ingest_observations import build_engine_from_env, run_ingestion
from setup_postgres_database import create_db_schema  # type: ignore
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = logging.getLogger("testdb.setup")


async def ensure_database_exists(admin_engine: AsyncEngine, db_name: str):
    """Idempotently create the test database if missing."""

    # First check for existence using a simple connection (may start a transaction implicitly)
    async with admin_engine.connect() as conn:
        res = await conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": db_name})
        exists = res.scalar() is not None

    if exists:
        logger.info("Database %s already exists", db_name)
        return

    # Run CREATE DATABASE outside of a transaction using AUTOCOMMIT on a fresh connection
    logger.info("Creating database %s", db_name)
    async with admin_engine.connect() as conn:
        conn_ac = await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn_ac.execute(text(f"CREATE DATABASE {db_name} TEMPLATE template0"))


def build_admin_engine(host: str, user: str, password: str, port: int) -> AsyncEngine:
    # Connect to maintenance database for create DB (cannot create DB inside its own connection)
    url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/postgres"
    return create_async_engine(url, echo=False, pool_pre_ping=True)


async def apply_schema_to_db(db_name: str, host: str, user: str, password: str, port: int):
    url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db_name}"
    engine = create_async_engine(url, echo=False, pool_pre_ping=True)
    try:
        await create_db_schema(engine)
    finally:
        await engine.dispose()


async def ingest_csv_into_db(csv_path: str, db_name: str, host: str, user: str, password: str, port: int):
    # Re-use ingestion engine builder but patch env for simplicity
    os.environ.setdefault("POSTGRES_HOST", host)
    os.environ.setdefault("POSTGRES_USERNAME", user)
    os.environ.setdefault("POSTGRES_PASSWORD", password)
    os.environ.setdefault("POSTGRES_DB", db_name)
    os.environ.setdefault("POSTGRES_PORT", str(port))
    engine = build_engine_from_env()
    try:
        await run_ingestion(csv_path, engine)
    finally:
        await engine.dispose()


async def orchestrate(args):
    await ensure_database_exists(args.admin_engine, args.test_db)
    await apply_schema_to_db(args.test_db, args.host, args.username, args.password, args.port)
    await ingest_csv_into_db(args.csv, args.test_db, args.host, args.username, args.password, args.port)
    logger.info("Test database %s prepared with observations data", args.test_db)
    # Dispose admin engine within same event loop to avoid cross-loop issues
    await args.admin_engine.dispose()


def parse_args():
    load_dotenv()
    p = argparse.ArgumentParser(description="Create & load dedicated test database with observations data")
    p.add_argument("--csv", required=True, help="Path to full observations CSV (raw source)")
    p.add_argument("--test-db", default=os.getenv("TEST_DB_NAME", "observations_test"), help="Test database name")
    p.add_argument("--host", default=os.getenv("POSTGRES_HOST", "localhost"))
    p.add_argument("--username", default=os.getenv("POSTGRES_USERNAME", "postgres"))
    p.add_argument("--password", default=os.getenv("POSTGRES_PASSWORD", "postgres"))
    p.add_argument("--port", type=int, default=int(os.getenv("POSTGRES_PORT", "5432")))
    return p.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()
    admin_engine = build_admin_engine(args.host, args.username, args.password, args.port)
    setattr(args, "admin_engine", admin_engine)
    asyncio.run(orchestrate(args))


if __name__ == "__main__":
    main()
