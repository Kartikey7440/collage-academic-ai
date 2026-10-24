"""Async SQLAlchemy engine and session factory.

Reads DATABASE_URL from the environment — no hardcoded credentials.
Set it before running any db code:

    export DATABASE_URL="postgresql+asyncpg://college_ai:college_ai_secret@localhost:5432/college_ai"

Or place it in a .env file and load with python-dotenv.

Engine creation is intentionally **lazy** — the engine and session factory
are only instantiated on the first call to ``get_engine()`` / ``get_session_factory()``.
This allows importing this module (and any module that imports it) without a
live database or a set DATABASE_URL, which matters for tests, CLI tooling,
and any code that runs before the environment is fully configured.
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine, async_sessionmaker, create_async_engine

load_dotenv()

# ---------------------------------------------------------------------------
# Module-level singletons — populated lazily via _init()
# ---------------------------------------------------------------------------

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _normalize_database_url(raw_url: str) -> tuple[str, dict]:
    """Normalize a database URL and derive driver-specific connect_args.

    Supports Neon, standard PostgreSQL, and local Docker databases:
    - Upgrades postgresql:// or postgres:// to postgresql+asyncpg://
    - Translates sslmode -> ssl for asyncpg
    - Strips unsupported libpq query parameters like channel_binding
    - Automatically disables asyncpg prepared statement caching when connecting
      through Neon's PgBouncer connection pooler (-pooler)
    """
    from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

    parsed = urlparse(raw_url)
    scheme = parsed.scheme
    if scheme in ("postgresql", "postgres"):
        scheme = "postgresql+asyncpg"

    qs = parse_qs(parsed.query)
    qs.pop("channel_binding", None)
    if "sslmode" in qs:
        qs["ssl"] = [qs.pop("sslmode")[0]]

    new_query = urlencode(qs, doseq=True)
    clean_url = urlunparse(
        (scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
    )

    connect_args: dict = {}
    if "-pooler" in (parsed.hostname or ""):
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_cache_size"] = 0

    return clean_url, connect_args


from sqlalchemy.pool import NullPool

def _init() -> None:
    """Initialise the engine and session factory (called once on first use)."""
    global _engine, _session_factory  # noqa: PLW0603

    if _engine is not None:
        return  # Already initialised

    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is not set.\n"
            "Example: postgresql+asyncpg://college_ai:secret@localhost:5432/college_ai"
        )

    clean_url, connect_args = _normalize_database_url(url)

    if os.getenv("TESTING") == "1":
        _engine = create_async_engine(
            clean_url,
            echo=False,
            poolclass=NullPool,
            connect_args=connect_args,
        )
    else:
        _engine = create_async_engine(
            clean_url,
            echo=False,          # Set to True for SQL query logging during development
            pool_pre_ping=True,  # Verify connections before use (avoids stale connection errors)
            pool_size=10,
            max_overflow=20,
            connect_args=connect_args,
        )
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


async def dispose_engine() -> None:
    """Dispose of the engine and reset module singletons."""
    global _engine, _session_factory  # noqa: PLW0603
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


# ---------------------------------------------------------------------------
# Public accessors
# ---------------------------------------------------------------------------


def get_engine() -> AsyncEngine:
    """Return the shared async engine, initialising it on first call."""
    _init()
    assert _engine is not None
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the shared session factory, initialising it on first call."""
    _init()
    assert _session_factory is not None
    return _session_factory


# ---------------------------------------------------------------------------
# Backwards-compatible module-level aliases
# ---------------------------------------------------------------------------
# These proxy objects allow existing code that does
#   from db.session import engine, AsyncSessionLocal
# to keep working without any changes — they delegate to the lazy singletons
# at access time rather than at import time.

class _LazyEngine:
    """Proxy that forwards attribute access to the real engine on first use."""

    def __getattr__(self, name: str):  # noqa: ANN204
        return getattr(get_engine(), name)


class _LazySessionFactory:
    """Proxy that makes the factory callable (``AsyncSessionLocal()``)."""

    def __call__(self, **kw):  # type: ignore[override]
        return get_session_factory()(**kw)

    def __getattr__(self, name: str):  # noqa: ANN204
        return getattr(get_session_factory(), name)


engine = _LazyEngine()  # type: ignore[assignment]
AsyncSessionLocal = _LazySessionFactory()  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Session context-manager helper
# ---------------------------------------------------------------------------


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager that provides a database session with automatic commit/rollback."""
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
