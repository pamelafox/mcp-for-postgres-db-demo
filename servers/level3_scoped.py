"""Level 3: Scoped WHERE clause MCP server.

Exposes query_observations(where_clause, ...) and query_species(where_clause, ...).
The server controls SELECT ... FROM <table> WHERE; the LLM only fills in filtering.
Read-only, single-table per tool, with max LIMIT enforcement.
"""

import logging

from fastmcp import FastMCP
from sqlalchemy import text

from servers.db import create_engine

logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(message)s")
logger = logging.getLogger("bees_mcp.level3")
logger.setLevel(logging.INFO)

MAX_LIMIT = 100

mcp = FastMCP("Bees DB - Scoped SQL")

_engine = None


async def _get_engine():
    global _engine
    if _engine is None:
        _engine = await create_engine()
    return _engine


async def _run_scoped_query(table: str, columns: str, where_clause: str, order_by: str | None, limit: int) -> str:
    """Build and execute a scoped SELECT query."""
    limit = min(limit, MAX_LIMIT)

    sql = f"SELECT {columns} FROM {table}"
    if where_clause:
        sql += f" WHERE {where_clause}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    sql += f" LIMIT {limit}"

    engine = await _get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text(sql))
        rows = result.fetchall()
        columns_list = list(result.keys())
        lines = [" | ".join(columns_list)]
        for row in rows:
            lines.append(" | ".join(str(v) for v in row))
        return "\n".join(lines)


@mcp.tool(annotations={"readOnlyHint": True})
async def query_observations(
    where_clause: str,
    order_by: str | None = None,
    limit: int = 25,
) -> str:
    """Query the observations table with a WHERE clause.

    The server runs: SELECT observation_id, taxon_id, observed_date, latitude, longitude,
    quality_grade FROM observations WHERE <your_clause> ORDER BY <order_by> LIMIT <limit>.

    Available columns: observation_id, taxon_id, observed_date, observed_year, observed_month,
    latitude, longitude, geom (PostGIS GEOGRAPHY), coordinates_obscured, positional_accuracy,
    quality_grade, license, county, captive_cultivated.

    Example where_clause: "taxon_id = 630955 AND observed_month = 6"
    """
    return await _run_scoped_query(
        table="observations",
        columns="observation_id, taxon_id, observed_date, latitude, longitude, quality_grade",
        where_clause=where_clause,
        order_by=order_by,
        limit=limit,
    )


@mcp.tool(annotations={"readOnlyHint": True})
async def query_species(
    where_clause: str,
    order_by: str | None = None,
    limit: int = 25,
) -> str:
    """Query the species table with a WHERE clause.

    The server runs: SELECT taxon_id, scientific_name, common_name, family, genus,
    total_observations, peak_month FROM species WHERE <your_clause> ORDER BY <order_by> LIMIT <limit>.

    Available columns: taxon_id, scientific_name, common_name, family, subfamily, tribe,
    genus, species_epithet, rank, total_observations, peak_month, phenology_counts (INT[12]),
    phenology_normalized (NUMERIC[12]), window_start, window_end, seasonality_index.

    Example where_clause: "common_name ILIKE '%leafcutter%'"
    """
    return await _run_scoped_query(
        table="species",
        columns="taxon_id, scientific_name, common_name, family, genus, total_observations, peak_month",
        where_clause=where_clause,
        order_by=order_by,
        limit=limit,
    )


if __name__ == "__main__":
    logger.info("Starting Level 3 (scoped SQL) MCP server on port 8000")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
