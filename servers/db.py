"""Shared database engine setup for MCP servers.

All servers share this module for creating async SQLAlchemy engines
from environment variables. Supports both local Postgres (password auth)
and Azure Database for PostgreSQL (Entra ID token auth).
"""

import logging
import os

from dotenv import load_dotenv
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

load_dotenv(override=True)

logger = logging.getLogger("db_mcp")


def _get_azure_credential():
    """Get Azure credential for token-based auth."""
    from azure.identity import AzureDeveloperCliCredential

    tenant_id = os.getenv("AZURE_TENANT_ID")
    if tenant_id:
        return AzureDeveloperCliCredential(tenant_id=tenant_id, process_timeout=60)
    return AzureDeveloperCliCredential(process_timeout=60)


async def create_engine() -> AsyncEngine:
    """Create an async SQLAlchemy engine from environment variables."""
    host = os.environ["POSTGRES_HOST"]
    username = os.environ["POSTGRES_USERNAME"]
    database = os.environ["POSTGRES_DATABASE"]
    password = os.environ.get("POSTGRES_PASSWORD", "")
    sslmode = os.environ.get("POSTGRES_SSL", "")

    azure_credential = None
    token_based_password = False

    if host.endswith(".database.azure.com"):
        token_based_password = True
        azure_credential = _get_azure_credential()
        token = azure_credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
        password = token.token

    database_uri = f"postgresql+asyncpg://{username}:{password}@{host}/{database}"
    if sslmode:
        database_uri += f"?ssl={sslmode}"

    engine = create_async_engine(database_uri, echo=False)

    if token_based_password and azure_credential:

        @event.listens_for(engine.sync_engine, "do_connect")
        def update_password_token(dialect, conn_rec, cargs, cparams):
            token = azure_credential.get_token("https://ossrdbms-aad.database.windows.net/.default")
            cparams["password"] = token.token

    return engine


async def create_session(engine: AsyncEngine) -> AsyncSession:
    """Create a new async session."""
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    return session_factory()


async def get_db_schema_text(engine: AsyncEngine) -> str:
    """Retrieve database schema as text for the get_db_schema tool."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text("""
                SELECT table_name, column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public'
                ORDER BY table_name, ordinal_position
            """)
        )
        rows = result.fetchall()

    tables: dict[str, list[str]] = {}
    for table_name, column_name, data_type, is_nullable, column_default in rows:
        if table_name not in tables:
            tables[table_name] = []
        nullable = "NULL" if is_nullable == "YES" else "NOT NULL"
        default = f" DEFAULT {column_default}" if column_default else ""
        tables[table_name].append(f"  {column_name} {data_type} {nullable}{default}")

    lines = []
    for table_name, columns in sorted(tables.items()):
        lines.append(f"TABLE {table_name}:")
        lines.extend(columns)
        lines.append("")

    return "\n".join(lines)
