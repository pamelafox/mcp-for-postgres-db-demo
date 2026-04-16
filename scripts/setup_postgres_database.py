import asyncio
import logging
import os

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = logging.getLogger("db_mcp.setup")

TABLE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS species (
        taxon_id INTEGER PRIMARY KEY,
        scientific_name TEXT NOT NULL,
        common_name TEXT,
        family TEXT,
        subfamily TEXT,
        tribe TEXT,
        genus TEXT,
        species_epithet TEXT,
        rank TEXT,
        total_observations INTEGER,
        phenology_counts INTEGER[],
        phenology_normalized DOUBLE PRECISION[],
        peak_month INTEGER,
        window_start INTEGER,
        window_end INTEGER,
        seasonality_index DOUBLE PRECISION,
        insufficient_data BOOLEAN,
        peak_prominence DOUBLE PRECISION,
        total_observations_all INTEGER,
        phenology_counts_all INTEGER[],
        phenology_normalized_all DOUBLE PRECISION[],
        peak_month_all INTEGER,
        window_start_all INTEGER,
        window_end_all INTEGER,
        seasonality_index_all DOUBLE PRECISION,
        insufficient_data_all BOOLEAN,
        peak_prominence_all DOUBLE PRECISION
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS observations (
        observation_id INTEGER PRIMARY KEY,
        taxon_id INTEGER REFERENCES species(taxon_id),
        observed_date DATE,
        observed_year INTEGER,
        observed_month INTEGER,
        latitude DOUBLE PRECISION,
        longitude DOUBLE PRECISION,
        geom GEOGRAPHY(Point, 4326),
        coordinates_obscured BOOLEAN,
        positional_accuracy INTEGER,
        quality_grade TEXT,
        license TEXT,
        county TEXT,
        captive_cultivated BOOLEAN
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS historical_observations (
        observation_id INTEGER PRIMARY KEY,
        taxon_id INTEGER REFERENCES species(taxon_id),
        obs_date VARCHAR,
        obs_year INTEGER,
        latitude REAL,
        longitude REAL,
        verified BOOLEAN
    )
    """,
]

INDEX_STATEMENTS = [
    """
    CREATE INDEX IF NOT EXISTS observations_observed_month_taxon_idx
    ON public.observations (observed_month, taxon_id)
    """,
]


async def create_db_schema(engine: AsyncEngine):
    async with engine.begin() as conn:
        logger.info("Enabling PostGIS extension...")
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        logger.info("Creating database tables...")
        for stmt in TABLE_STATEMENTS:
            await conn.execute(text(stmt))
        logger.info("Ensuring performance indexes...")
        for stmt in INDEX_STATEMENTS:
            await conn.execute(text(stmt))


def _build_engine(database: str) -> AsyncEngine:
    load_dotenv(override=True)
    host = os.getenv("POSTGRES_HOST", "localhost")
    username = os.getenv("POSTGRES_USERNAME", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    sslmode = os.getenv("POSTGRES_SSL", "")
    database_uri = f"postgresql+asyncpg://{username}:{password}@{host}:{port}/{database}"
    if sslmode:
        database_uri += f"?ssl={sslmode}"
    return create_async_engine(database_uri, echo=False)


async def ensure_database_exists(database: str):
    admin_engine = _build_engine("postgres")
    async with admin_engine.connect() as conn:
        result = await conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": database})
        exists = result.scalar() is not None
    if not exists:
        logger.info("Creating database %s...", database)
        async with admin_engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(text(f'CREATE DATABASE "{database}"'))
    else:
        logger.info("Database %s already exists", database)
    await admin_engine.dispose()


async def main():
    load_dotenv(override=True)
    database = os.getenv("POSTGRES_DATABASE", "postgres")
    await ensure_database_exists(database)
    engine = _build_engine(database)
    await create_db_schema(engine)
    await engine.dispose()
    logger.info("Database extension and tables created successfully.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    logger.setLevel(logging.INFO)
    load_dotenv(override=True)
    asyncio.run(main())
