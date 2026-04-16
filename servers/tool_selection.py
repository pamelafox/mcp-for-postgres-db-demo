"""Tool selection experiment: routing across recent vs. historical tables.

Exposes search_species, search_observations (2020+), and search_historical_observations (pre-2020)
with rich, cross-referencing descriptions. Tests whether the LLM correctly queries
both tables for time-spanning queries.
"""

import logging
from datetime import date

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from sqlalchemy import text

from servers.db import create_engine

logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(message)s")
logger = logging.getLogger("db_mcp.tool_selection")
logger.setLevel(logging.INFO)

mcp = FastMCP("Bees DB - Tool Selection")

_engine = None


async def _get_engine():
    global _engine
    if _engine is None:
        _engine = await create_engine()
    return _engine


class SpeciesResult(BaseModel):
    taxon_id: int
    scientific_name: str
    common_name: str | None = None
    family: str | None = None
    genus: str | None = None
    total_observations: int | None = None


class ObservationResult(BaseModel):
    observation_id: int
    taxon_id: int
    scientific_name: str | None = None
    common_name: str | None = None
    observed_date: str
    latitude: float | None = None
    longitude: float | None = None
    quality_grade: str


class HistoricalObservationResult(BaseModel):
    observation_id: int
    taxon_id: int
    scientific_name: str | None = None
    common_name: str | None = None
    obs_date: str
    latitude: float | None = None
    longitude: float | None = None
    verified: bool


# --------------- Tools ---------------


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def search_species(
    q: str,
    limit: int = 10,
) -> list[SpeciesResult]:
    """Search bee species by scientific or common name.

    Returns matching species with taxonomy info and observation counts.
    Use this to resolve a common name (e.g. 'sweat bee') or scientific name
    to a taxon_id before calling search_observations or search_historical_observations.
    """
    limit = min(limit, 50)
    engine = await _get_engine()

    sql = text("""
        SELECT taxon_id, scientific_name, common_name, family, genus, total_observations,
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

    Returns individual observation records within a radius of the given coordinates.
    Only contains data from 2020 onward.
    Use search_historical_observations for records before 2020.
    For comprehensive queries spanning all years, call both tools.
    Use search_species first to resolve a species name to a taxon_id.
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


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def search_historical_observations(
    lat: float = Field(ge=-90, le=90, description="Latitude of search center"),
    lon: float = Field(ge=-180, le=180, description="Longitude of search center"),
    start_year: int = Field(ge=1900, le=2019, description="Start year (inclusive, max 2019)"),
    end_year: int = Field(ge=1900, le=2019, description="End year (inclusive, max 2019)"),
    radius_km: float = Field(25, gt=0, le=100, description="Search radius in kilometers (max 100)"),
    taxon_id: int | None = Field(None, description="Filter to a specific species by taxon_id"),
    limit: int = Field(25, gt=0, le=100, description="Maximum number of results"),
) -> list[HistoricalObservationResult]:
    """Search historical bee observations (before 2020) by location and year range.

    This table has a different schema than recent observations: no PostGIS,
    lat/lon stored as REAL, dates as VARCHAR, and 'verified' boolean instead of quality_grade.
    Only contains data before 2020.
    Use search_observations for records from 2020 onward.
    For comprehensive queries spanning all years, call both tools.
    """
    import math

    limit = min(limit, 100)
    engine = await _get_engine()

    params: dict = {
        "lat": lat,
        "lon": lon,
        "radius_km": radius_km,
        "start_year": start_year,
        "end_year": end_year,
        "limit": limit,
    }

    taxon_filter = ""
    if taxon_id is not None:
        taxon_filter = "AND h.taxon_id = :taxon_id"
        params["taxon_id"] = taxon_id

    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * max(0.01, abs(math.cos(math.radians(lat)))))
    params["lat_min"] = lat - lat_delta
    params["lat_max"] = lat + lat_delta
    params["lon_min"] = lon - lon_delta
    params["lon_max"] = lon + lon_delta

    sql = text(f"""
        SELECT h.observation_id, h.taxon_id, s.scientific_name, s.common_name,
               h.obs_date, h.latitude, h.longitude, h.verified
        FROM historical_observations h
        LEFT JOIN species s ON h.taxon_id = s.taxon_id
        WHERE h.latitude BETWEEN :lat_min AND :lat_max
          AND h.longitude BETWEEN :lon_min AND :lon_max
          AND h.obs_year BETWEEN :start_year AND :end_year
          {taxon_filter}
        ORDER BY h.obs_date DESC
        LIMIT :limit
    """)

    async with engine.connect() as conn:
        result = await conn.execute(sql, params)
        return [
            HistoricalObservationResult(
                observation_id=row.observation_id,
                taxon_id=row.taxon_id,
                scientific_name=row.scientific_name,
                common_name=row.common_name,
                obs_date=str(row.obs_date),
                latitude=row.latitude,
                longitude=row.longitude,
                verified=row.verified,
            )
            for row in result.fetchall()
        ]


if __name__ == "__main__":
    logger.info("Starting tool selection MCP server on port 8000")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
