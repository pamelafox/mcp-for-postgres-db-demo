"""Level 4: Fully typed MCP server.

Exposes structured, typed tools with no SQL surface:
- search_species (read)
- search_observations, search_historical_observations (read)
- add_observation, delete_observation (write)

All queries built server-side. MCP annotations mark read vs destructive tools.
"""

import logging
from datetime import date

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from sqlalchemy import text

from servers.db import create_engine, create_session

logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(message)s")
logger = logging.getLogger("db_mcp.level4")
logger.setLevel(logging.INFO)

mcp = FastMCP("Bees DB - Typed Tools")

_engine = None


async def _get_engine():
    global _engine
    if _engine is None:
        _engine = await create_engine()
    return _engine


# --------------- Response models ---------------


class SpeciesResult(BaseModel):
    """A species search result."""

    taxon_id: int
    scientific_name: str
    common_name: str | None = None
    family: str | None = None
    genus: str | None = None
    total_observations: int | None = None
    peak_month: int | None = None


class ObservationResult(BaseModel):
    """A single observation record."""

    observation_id: int
    taxon_id: int
    scientific_name: str | None = None
    common_name: str | None = None
    observed_date: str
    latitude: float | None = None
    longitude: float | None = None
    quality_grade: str


# --------------- Read tools ---------------


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def search_species(
    q: str,
    limit: int = 10,
) -> list[SpeciesResult]:
    """Search bee species by scientific or common name.

    Use this to resolve a species name to a taxon_id before calling other tools.
    Returns matching species with taxonomy and peak activity month.
    """
    limit = min(limit, 50)
    engine = await _get_engine()

    sql = text("""
        SELECT taxon_id, scientific_name, common_name, family, genus,
               total_observations, peak_month,
               ts_rank(
                   to_tsvector('simple', coalesce(scientific_name,'') || ' ' || coalesce(common_name,'')),
                   plainto_tsquery('simple', :q)
               ) AS score
        FROM species
        WHERE to_tsvector('simple', coalesce(scientific_name,'') || ' ' || coalesce(common_name,''))
              @@ plainto_tsquery('simple', :q)
        ORDER BY score DESC, scientific_name ASC
        LIMIT :limit
    """)

    async with engine.connect() as conn:
        result = await conn.execute(sql, {"q": q, "limit": limit})
        return [
            SpeciesResult(
                taxon_id=row.taxon_id,
                scientific_name=row.scientific_name,
                common_name=row.common_name,
                family=row.family,
                genus=row.genus,
                total_observations=row.total_observations,
                peak_month=row.peak_month,
            )
            for row in result.fetchall()
        ]


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def search_observations(
    lat: float = Field(ge=-90, le=90, description="Latitude of search center"),
    lon: float = Field(ge=-180, le=180, description="Longitude of search center"),
    start_date: date = Field(description="Start date (inclusive)"),
    end_date: date = Field(description="End date (inclusive)"),
    radius_km: float = Field(25, gt=0, le=100, description="Search radius in kilometers (max 100)"),
    taxon_id: int | None = Field(None, description="Filter to a specific species by taxon_id"),
    limit: int = Field(25, gt=0, le=100, description="Maximum number of results"),
) -> list[ObservationResult]:
    """Search recent bee observations (2020-present) by location and date range.

    Returns observations within a radius of the given coordinates during the date window.
    """
    limit = min(limit, 100)
    radius_m = radius_km * 1000.0
    engine = await _get_engine()

    params: dict = {
        "lon": lon,
        "lat": lat,
        "radius": radius_m,
        "start_date": start_date,
        "end_date": end_date,
        "limit": limit,
    }

    taxon_filter = ""
    if taxon_id is not None:
        taxon_filter = "AND o.taxon_id = :taxon_id"
        params["taxon_id"] = taxon_id

    sql = text(f"""
        SELECT o.observation_id, o.taxon_id, s.scientific_name, s.common_name,
               o.observed_date, o.latitude, o.longitude, o.quality_grade
        FROM observations o
        LEFT JOIN species s ON o.taxon_id = s.taxon_id
        WHERE o.geom IS NOT NULL
          AND ST_DWithin(o.geom, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :radius)
          AND o.observed_date BETWEEN :start_date AND :end_date
          {taxon_filter}
        ORDER BY o.observed_date DESC
        LIMIT :limit
    """)

    async with engine.connect() as conn:
        result = await conn.execute(sql, params)
        return [
            ObservationResult(
                observation_id=row.observation_id,
                taxon_id=row.taxon_id,
                scientific_name=row.scientific_name,
                common_name=row.common_name,
                observed_date=str(row.observed_date),
                latitude=row.latitude,
                longitude=row.longitude,
                quality_grade=row.quality_grade,
            )
            for row in result.fetchall()
        ]


# --------------- Write tools ---------------


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
async def add_observation(
    taxon_id: int = Field(description="Species taxon_id (use search_species to find this)"),
    lat: float = Field(ge=-90, le=90, description="Latitude where the bee was observed"),
    lon: float = Field(ge=-180, le=180, description="Longitude where the bee was observed"),
    observed_date: date = Field(description="Date the observation was made"),
) -> str:
    """Add a new bee observation to the database.

    Use search_species first to resolve a species name to a taxon_id.
    The observation is added to the recent observations table.
    """
    engine = await _get_engine()

    # Validate taxon_id exists
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT scientific_name FROM species WHERE taxon_id = :tid"),
            {"tid": taxon_id},
        )
        species_row = result.fetchone()
        if not species_row:
            return f"Error: taxon_id {taxon_id} does not exist in the species table."

    session = await create_session(engine)
    try:
        await session.execute(
            text("""
                INSERT INTO observations (taxon_id, observed_date, observed_year, observed_month,
                    latitude, longitude, geom, coordinates_obscured, quality_grade)
                VALUES (:taxon_id, :observed_date, :year, :month,
                    :lat, :lon, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                    false, 'casual')
            """),
            {
                "taxon_id": taxon_id,
                "observed_date": observed_date.isoformat(),
                "year": observed_date.year,
                "month": observed_date.month,
                "lat": lat,
                "lon": lon,
            },
        )
        await session.commit()
        return f"Observation added: {species_row.scientific_name} at ({lat}, {lon}) on {observed_date}"
    finally:
        await session.close()


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
async def delete_observation(observation_id: int) -> str:
    """Delete a bee observation by its observation_id.

    This permanently removes the observation record.
    """
    engine = await _get_engine()
    session = await create_session(engine)
    try:
        # Look up first for confirmation message
        result = await session.execute(
            text("""
                SELECT o.observation_id, o.taxon_id, s.scientific_name, o.observed_date, o.latitude, o.longitude
                FROM observations o
                LEFT JOIN species s ON o.taxon_id = s.taxon_id
                WHERE o.observation_id = :oid
            """),
            {"oid": observation_id},
        )
        row = result.fetchone()
        if not row:
            return f"Error: observation_id {observation_id} not found."

        await session.execute(
            text("DELETE FROM observations WHERE observation_id = :oid"),
            {"oid": observation_id},
        )
        await session.commit()
        return (
            f"Deleted observation #{row.observation_id}: {row.scientific_name} "
            f"on {row.observed_date} at ({row.latitude}, {row.longitude})"
        )
    finally:
        await session.close()


if __name__ == "__main__":
    logger.info("Starting Level 4 (typed tools) MCP server on port 8000")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
