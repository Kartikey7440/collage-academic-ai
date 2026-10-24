"""Test that the database engine is connected to the test database, not the dev/prod database."""

import os
from urllib.parse import urlparse

import pytest
from sqlalchemy import text

from db.session import engine


class TestDatabaseGuard:
    """Verify the test suite is running against the correct database."""

    @pytest.mark.asyncio
    async def test_engine_points_at_test_database(self):
        """The SQLAlchemy engine must be connected to a database whose name contains 'test'."""
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT current_database()"))
            db_name = result.scalar()

        assert "test" in db_name.lower(), (
            f"Engine is connected to '{db_name}' which does not contain 'test'. "
            "Tests are NOT running on the test database!"
        )

    @pytest.mark.asyncio
    async def test_database_url_env_var_points_to_test(self):
        """DATABASE_URL must have been redirected to TEST_DATABASE_URL."""
        db_url = os.environ.get("DATABASE_URL", "")
        parsed = urlparse(db_url)
        db_name = parsed.path.lstrip("/").split("?")[0]

        assert "test" in db_name.lower(), (
            f"DATABASE_URL points to '{db_name}' — expected a test database."
        )

    @pytest.mark.asyncio
    async def test_database_url_unpooled_env_var_points_to_test(self):
        """DATABASE_URL_UNPOOLED must also have been redirected."""
        db_url = os.environ.get("DATABASE_URL_UNPOOLED", "")
        parsed = urlparse(db_url)
        db_name = parsed.path.lstrip("/").split("?")[0]

        assert "test" in db_name.lower(), (
            f"DATABASE_URL_UNPOOLED points to '{db_name}' — expected a test database."
        )

    def test_testing_flag_is_set(self):
        """TESTING=1 must be set so NullPool is used."""
        assert os.environ.get("TESTING") == "1", "TESTING env var is not set to '1'"
