"""Pytest root configuration and test environment bootstrap.

Guarantees:
1. TESTING=1 is set before any project modules are imported.
2. Both DATABASE_URL and DATABASE_URL_UNPOOLED point to TEST_DATABASE_URL
   (fails loudly if unset, if its name matches the dev DB, or if the name
   does not contain "test").
3. NullPool is active for all test DB connections.
4. Database tables and vector extension are initialized on the test database.
5. Seeding fixtures and test helpers run on the proper loop and engine is
   disposed at teardown.
"""

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv

# Ensure project root is on sys.path before any local imports
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env file
load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Safety checks — must run BEFORE any db/ or api/ imports
# ---------------------------------------------------------------------------

test_db_url = os.getenv("TEST_DATABASE_URL", "").strip()

if not test_db_url:
    raise RuntimeError(
        "TEST_DATABASE_URL environment variable is not set. "
        "Cannot run tests safely without a dedicated test database."
    )

# Extract database name from TEST_DATABASE_URL
_test_parsed = urlparse(test_db_url)
_test_db_name = _test_parsed.path.lstrip("/").split("?")[0]

# Fail if the test database name does not contain "test"
if "test" not in _test_db_name.lower():
    raise RuntimeError(
        f"TEST_DATABASE_URL database name '{_test_db_name}' does not contain 'test'. "
        "Refusing to run tests on a database that might be production/dev."
    )

# Check that the test DB is not the same as the dev DB (either pooled or unpooled)
for _var in ("DATABASE_URL", "DATABASE_URL_UNPOOLED"):
    _dev_url = os.getenv(_var, "").strip()
    if _dev_url:
        _dev_parsed = urlparse(_dev_url)
        _dev_db_name = _dev_parsed.path.lstrip("/").split("?")[0]
        if _test_db_name == _dev_db_name:
            raise RuntimeError(
                f"TEST_DATABASE_URL database name '{_test_db_name}' matches {_var} "
                f"database name '{_dev_db_name}'. Tests will wipe data — point "
                "TEST_DATABASE_URL to a separate test database."
            )

# ---------------------------------------------------------------------------
# Redirect BOTH database URL env vars to the test database
# ---------------------------------------------------------------------------

os.environ["TESTING"] = "1"
os.environ["DATABASE_URL"] = test_db_url
os.environ["DATABASE_URL_UNPOOLED"] = test_db_url
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-test-suite")
os.environ.setdefault("COLLEGE_TIMEZONE", "Asia/Kolkata")

# ---------------------------------------------------------------------------
# NOW it is safe to import project modules
# ---------------------------------------------------------------------------

import pytest
import pytest_asyncio
from sqlalchemy import text
from db.models import Base
from db.session import engine, dispose_engine


@pytest.fixture(scope="session")
def event_loop():
    """Create a single session-scoped event loop for session fixtures."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def init_test_database():
    """Initialize schema once per test session and dispose engine at teardown."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    yield

    # Dispose the engine and connection pool at teardown
    await dispose_engine()
