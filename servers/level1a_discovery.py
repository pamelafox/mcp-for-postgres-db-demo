"""Level 1a: Granular schema discovery + free-form SQL.

Like Level 1 but replaces get_db_schema() with list_tables() and describe_table(),
forcing the LLM into a "look → plan → query" workflow. This avoids dumping the
full schema into context upfront.

Inspired by MotherDuck's MCP server pattern.
"""

import logging

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from sqlalchemy import text

from servers.db import create_engine

logging.basicConfig(level=logging.WARNING, format="%(asctime)s - %(message)s")
logger = logging.getLogger("db_mcp.level1a")
logger.setLevel(logging.INFO)

mcp = FastMCP("Bees DB - Discovery SQL")

_engine = None


async def _get_engine():
    global _engine
    if _engine is None:
        _engine = await create_engine()
    return _engine


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def list_tables() -> str:
    """List all tables in the public schema.

    Call this first to discover available tables before describing or querying them.
    """
    engine = await _get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """)
        )
        tables = [row[0] for row in result.fetchall()]
    return "\n".join(tables) if tables else "No tables found."


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
async def describe_table(table_name: str) -> str:
    """Describe the columns of a specific table.

    Returns column names, data types, and nullability for the given table.
    Call list_tables() first to see available tables.
    """
    engine = await _get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :table_name
                ORDER BY ordinal_position
            """),
            {"table_name": table_name},
        )
        rows = result.fetchall()

    if not rows:
        return f"Table '{table_name}' not found. Use list_tables() to see available tables."

    lines = [f"TABLE {table_name}:"]
    for column_name, data_type, is_nullable in rows:
        nullable = "NULL" if is_nullable == "YES" else "NOT NULL"
        lines.append(f"  {column_name} {data_type} {nullable}")
    return "\n".join(lines)


@mcp.tool()
async def execute_sql(sql: str) -> str:
    """Execute a SQL query against the database and return results.

    You can run any SQL statement including SELECT, INSERT, UPDATE, DELETE.
    Results are returned as text rows.
    """
    engine = await _get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(text(sql))
        if result.returns_rows:
            columns = list(result.keys())
            rows = result.fetchmany(100)
            return {"columns": columns, "rows": [[str(v) for v in row] for row in rows]}
        await conn.commit()
        return f"Statement executed. Rows affected: {result.rowcount}"


if __name__ == "__main__":
    logger.info("Starting Level 1a (discovery SQL) MCP server on port 8000")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
