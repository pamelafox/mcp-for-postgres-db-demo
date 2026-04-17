"""Level 5: Typed tools with MCP elicitation.

Builds on Level 4's fully typed tools by adding server-side elicitation:
- Destructive operations ask for user confirmation with record details
- Boundary violations (e.g. huge search radius) prompt the user to narrow
- Invalid entities suggest alternatives

All queries built server-side. No SQL surface.
"""

import logging
import math
from datetime import date

from fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from sqlalchemy import text

from servers.db import create_engine, create_session

logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(message)s")
logger = logging.getLogger("db_mcp.level5")
logger.setLevel(logging.INFO)

mcp = FastMCP("Bees DB - Typed Tools + Elicitation")

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


class DeleteConfirmation(BaseModel):
    confirm: bool = Field(title="Confirm deletion", description="Check to confirm permanent deletion")


# --------------- Constants ---------------

RADIUS_WARNING_KM = 50


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
    ctx: Context,
    lat: float = Field(ge=-90, le=90, description="Latitude of search center"),
    lon: float = Field(ge=-180, le=180, description="Longitude of search center"),
    start_date: date = Field(description="Start date (inclusive)"),
    end_date: date = Field(description="End date (inclusive)"),
    radius_km: float = Field(25, gt=0, le=100, description="Search radius in kilometers (max 100)"),
    taxon_id: int | None = Field(None, description="Filter to a specific species by taxon_id"),
    limit: int = Field(25, gt=0, le=100, description="Maximum number of results"),
) -> list[ObservationResult] | str:
    """Search recent bee observations (2020-present) by location and date range.

    Returns observations within a radius of the given coordinates during the date window.
    """
    if radius_km > RADIUS_WARNING_KM:
        area_km2 = int(math.pi * radius_km**2)
        result = await ctx.elicit(
            f"That radius ({radius_km} km) covers ~{area_km2:,} km² and may return a very large result set. "
            f"Would you like to narrow to {RADIUS_WARNING_KM} km instead?",
            response_type=["yes, narrow it", "no, keep the full radius"],
        )
        if result.action == "cancel":
            return "Search cancelled."
        if result.action == "accept" and result.data == "yes, narrow it":
            radius_km = RADIUS_WARNING_KM

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


# --------------- Write tools with elicitation ---------------


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
async def add_observation(
    ctx: Context,
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
            text("SELECT scientific_name, common_name FROM species WHERE taxon_id = :tid"),
            {"tid": taxon_id},
        )
        species_row = result.fetchone()

    if not species_row:
        # Suggest alternatives
        async with engine.connect() as conn:
            result = await conn.execute(
                text("""
                    SELECT taxon_id, scientific_name, common_name
                    FROM species ORDER BY total_observations DESC LIMIT 5
                """)
            )
            suggestions = result.fetchall()

        suggestion_text = "\n".join(
            f"  - {s.scientific_name} ({s.common_name or 'no common name'}, taxon_id: {s.taxon_id})"
            for s in suggestions
        )
        return f"Error: taxon_id {taxon_id} does not exist. Did you mean one of these?\n{suggestion_text}"

    # Check for suspicious coordinates (0,0 = Gulf of Guinea)
    if abs(lat) < 0.1 and abs(lon) < 0.1:
        result = await ctx.elicit(
            f"The coordinates ({lat}, {lon}) are in the Gulf of Guinea (off the coast of Africa). "
            "This is a common error for missing or default coordinates. Did you mean a different location?",
            response_type=["proceed anyway", "cancel"],
        )
        if result.action != "accept" or result.data == "cancel":
            return "Observation not added — please provide corrected coordinates."

    species_name = species_row.scientific_name
    common = f" ({species_row.common_name})" if species_row.common_name else ""

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
        return f"Observation added: {species_name}{common} at ({lat}, {lon}) on {observed_date}"
    finally:
        await session.close()


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
async def delete_observation(ctx: Context, observation_id: int) -> str:
    """Delete a bee observation by its observation_id.

    This permanently removes the observation record. The server will show
    the record details and ask for confirmation before deleting.
    """
    engine = await _get_engine()

    # Look up the record first
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT o.observation_id, o.taxon_id, s.scientific_name, s.common_name,
                       o.observed_date, o.latitude, o.longitude, o.quality_grade
                FROM observations o
                LEFT JOIN species s ON o.taxon_id = s.taxon_id
                WHERE o.observation_id = :oid
            """),
            {"oid": observation_id},
        )
        row = result.fetchone()

    if not row:
        return f"Error: observation_id {observation_id} not found."

    species_name = row.scientific_name or "unknown species"
    common = f" ({row.common_name})" if row.common_name else ""

    # Elicit confirmation with record details
    confirmation = await ctx.elicit(
        f"You're about to permanently delete:\n"
        f"  Observation #{row.observation_id} — {species_name}{common}\n"
        f"  Observed {row.observed_date} at ({row.latitude}, {row.longitude})\n"
        f"  Quality: {row.quality_grade}\n\n"
        f"Proceed?",
        response_type=DeleteConfirmation,
    )

    if confirmation.action != "accept" or not confirmation.data.confirm:
        return "Deletion cancelled."

    session = await create_session(engine)
    try:
        await session.execute(
            text("DELETE FROM observations WHERE observation_id = :oid"),
            {"oid": observation_id},
        )
        await session.commit()
        return (
            f"Deleted observation #{row.observation_id}: {species_name}{common} "
            f"on {row.observed_date} at ({row.latitude}, {row.longitude})"
        )
    finally:
        await session.close()


if __name__ == "__main__":
    logger.info("Starting Level 5 (elicitation) MCP server on port 8000")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
