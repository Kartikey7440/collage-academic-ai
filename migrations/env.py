"""Alembic env.py — configured for async SQLAlchemy (asyncpg).

Reads DATABASE_URL from the environment. Run migrations with:
    alembic upgrade head
"""

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ── Make the project root importable ─────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Load .env so DATABASE_URL is available
load_dotenv()

# ── Alembic config object ─────────────────────────────────────────────────────
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Import models so Alembic can see them ─────────────────────────────────────
from db.models import Base  # noqa: E402  (must come after sys.path setup)

target_metadata = Base.metadata

# ── Inject DATABASE_URL from environment (prefer unpooled for migrations) ────
from db.session import _normalize_database_url  # noqa: E402

_raw_db_url = os.environ.get("DATABASE_URL_UNPOOLED") or os.environ.get("DATABASE_URL")
if not _raw_db_url:
    raise RuntimeError(
        "Neither DATABASE_URL_UNPOOLED nor DATABASE_URL is set. Cannot run migrations.\n"
        "Example: $env:DATABASE_URL='postgresql+asyncpg://college_ai:secret@localhost:5432/college_ai'"
    )
_clean_db_url, _ = _normalize_database_url(_raw_db_url)
config.set_main_option("sqlalchemy.url", _clean_db_url)


# ── Offline mode (generates SQL without connecting) ───────────────────────────
def run_migrations_offline() -> None:
    """Run migrations without a live DB connection, generating SQL to stdout."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode (async) ───────────────────────────────────────────────────────
def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations through a sync wrapper."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # No connection pooling during migrations
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migration mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
