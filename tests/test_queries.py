"""Pytest tests for database query isolation and correctness.

These tests require a running Postgres database with the pgvector extension.
They use the seed data from db/seed.py as fixtures.

Run with:
    python -m pytest -v tests/test_queries.py

Ensure DATABASE_URL is set before running:
    $env:DATABASE_URL="postgresql+asyncpg://college_ai:college_ai_secret@localhost:5432/college_ai"
"""

import asyncio
from datetime import date, datetime, time
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Make project root importable
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.models import Base, Branch, Student, TimetableSlot
from db.queries import (
    get_classes_by_faculty,
    get_next_class,
    get_todays_classes,
    get_upcoming_events,
    is_timetable_suppressed,
)
from db.seed import seed_database
from db.session import AsyncSessionLocal, engine


# ---------------------------------------------------------------------------
# Session-scoped fixtures: create tables once per test session
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database():
    """Create all tables and seed test data once for the entire test session."""
    async with engine.begin() as conn:
        # Enable pgvector extension
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)

    # Seed deterministic test data
    seed_ids = await seed_database()
    yield seed_ids


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a fresh async session for each test."""
    async with AsyncSessionLocal() as s:
        yield s


# ---------------------------------------------------------------------------
# Helper: extract branch IDs from seed
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def seed_ids(setup_database):
    return setup_database


# ---------------------------------------------------------------------------
# Tests: get_todays_classes — branch isolation
# ---------------------------------------------------------------------------

class TestGetTodaysClasses:
    """A student only ever sees rows matching their own branch/semester."""

    @pytest.mark.asyncio
    async def test_ai_branch_returns_only_ai_slots(self, session, seed_ids):
        branch_ai_id = seed_ids["branch_ai_id"]
        slots = await get_todays_classes(
            session, branch_id=branch_ai_id, semester=5,
            section=None, batch=None, day=0  # MON
        )
        assert len(slots) >= 2, "Expected at least 2 AI slots on MON"
        for slot in slots:
            assert slot.branch_id == branch_ai_id, (
                f"Slot {slot.id} has branch_id={slot.branch_id}, expected {branch_ai_id}"
            )

    @pytest.mark.asyncio
    async def test_cs_branch_query_never_returns_ai_slots(self, session, seed_ids):
        branch_ai_id = seed_ids["branch_ai_id"]
        branch_cs_id = seed_ids["branch_cs_id"]

        ai_slots = await get_todays_classes(
            session, branch_id=branch_ai_id, semester=5,
            section=None, batch=None, day=0
        )
        cs_slots = await get_todays_classes(
            session, branch_id=branch_cs_id, semester=5,
            section=None, batch=None, day=0
        )

        ai_ids = {s.id for s in ai_slots}
        cs_ids = {s.id for s in cs_slots}
        overlap = ai_ids & cs_ids
        assert not overlap, f"Branch queries returned overlapping slot IDs: {overlap}"

    @pytest.mark.asyncio
    async def test_results_ordered_by_start_time(self, session, seed_ids):
        branch_ai_id = seed_ids["branch_ai_id"]
        slots = await get_todays_classes(
            session, branch_id=branch_ai_id, semester=5,
            section=None, batch=None, day=0
        )
        times = [s.start_time for s in slots]
        assert times == sorted(times), "Slots not ordered by start_time"

    @pytest.mark.asyncio
    async def test_no_slots_on_day_with_no_classes(self, session, seed_ids):
        branch_ai_id = seed_ids["branch_ai_id"]
        # SUN (day=6) has no seeded slots
        slots = await get_todays_classes(
            session, branch_id=branch_ai_id, semester=5,
            section=None, batch=None, day=6
        )
        assert slots == [], f"Expected no slots on Sunday, got {len(slots)}"


# ---------------------------------------------------------------------------
# Tests: get_next_class
# ---------------------------------------------------------------------------

class TestGetNextClass:

    @pytest.mark.asyncio
    async def test_returns_next_slot_after_now(self, session, seed_ids):
        branch_ai_id = seed_ids["branch_ai_id"]
        # MON at 09:30 → next class should be 10:00
        now = datetime(2024, 7, 1, 9, 30)  # 2024-07-01 is a Monday
        slot = await get_next_class(
            session, branch_id=branch_ai_id, semester=5,
            section=None, batch=None, now=now
        )
        assert slot is not None, "Expected a next class after 09:30 on MON"
        assert slot.start_time >= time(9, 30), (
            f"Returned slot starts at {slot.start_time}, before query time 09:30"
        )

    @pytest.mark.asyncio
    async def test_returns_none_after_last_class(self, session, seed_ids):
        branch_ai_id = seed_ids["branch_ai_id"]
        # MON at 23:00 → no classes left
        now = datetime(2024, 7, 1, 23, 0)  # Monday at 11 PM
        slot = await get_next_class(
            session, branch_id=branch_ai_id, semester=5,
            section=None, batch=None, now=now
        )
        assert slot is None, f"Expected None after last class, got slot {slot}"

    @pytest.mark.asyncio
    async def test_cs_branch_next_class_excludes_ai(self, session, seed_ids):
        branch_ai_id = seed_ids["branch_ai_id"]
        branch_cs_id = seed_ids["branch_cs_id"]
        now = datetime(2024, 7, 1, 9, 0)

        ai_next = await get_next_class(
            session, branch_id=branch_ai_id, semester=5,
            section=None, batch=None, now=now
        )
        cs_next = await get_next_class(
            session, branch_id=branch_cs_id, semester=5,
            section=None, batch=None, now=now
        )
        if ai_next and cs_next:
            assert ai_next.id != cs_next.id, "CS and AI returned the same next class slot"
        if cs_next:
            assert cs_next.branch_id == branch_cs_id


# ---------------------------------------------------------------------------
# Tests: is_timetable_suppressed
# ---------------------------------------------------------------------------

class TestIsTimetableSuppressed:

    @pytest.mark.asyncio
    async def test_holiday_suppresses_timetable(self, session, seed_ids):
        branch_ai_id = seed_ids["branch_ai_id"]
        # Independence Day seeded as a suppressing holiday on 2025-08-15
        suppressed = await is_timetable_suppressed(
            session, branch_id=branch_ai_id, semester=5,
            check_date=date(2025, 8, 15)
        )
        assert suppressed is True, "Expected timetable to be suppressed on Independence Day"

    @pytest.mark.asyncio
    async def test_normal_day_not_suppressed(self, session, seed_ids):
        branch_ai_id = seed_ids["branch_ai_id"]
        suppressed = await is_timetable_suppressed(
            session, branch_id=branch_ai_id, semester=5,
            check_date=date(2024, 7, 1)  # Normal Monday
        )
        assert suppressed is False, "Expected timetable NOT suppressed on a normal day"

    @pytest.mark.asyncio
    async def test_non_suppressing_event_does_not_block(self, session, seed_ids):
        branch_ai_id = seed_ids["branch_ai_id"]
        # Mid-semester exam (2024-10-01 to 2024-10-07) is NOT suppressing
        suppressed = await is_timetable_suppressed(
            session, branch_id=branch_ai_id, semester=5,
            check_date=date(2024, 10, 3)
        )
        assert suppressed is False, (
            "Non-suppressing exam event should not block timetable"
        )

    @pytest.mark.asyncio
    async def test_cs_branch_also_suppressed_by_institution_wide_holiday(self, session, seed_ids):
        branch_cs_id = seed_ids["branch_cs_id"]
        # Institution-wide holiday (branch_id=NULL) should suppress all branches
        suppressed = await is_timetable_suppressed(
            session, branch_id=branch_cs_id, semester=5,
            check_date=date(2025, 8, 15)
        )
        assert suppressed is True, "Institution-wide holiday should suppress CS branch too"


# ---------------------------------------------------------------------------
# Tests: get_upcoming_events
# ---------------------------------------------------------------------------

class TestGetUpcomingEvents:

    @pytest.mark.asyncio
    async def test_returns_events_from_date(self, session, seed_ids):
        branch_ai_id = seed_ids["branch_ai_id"]
        events = await get_upcoming_events(
            session, branch_id=branch_ai_id, semester=5,
            from_date=date(2024, 9, 1), limit=10
        )
        assert len(events) >= 1, "Expected at least the mid-semester exam event"

    @pytest.mark.asyncio
    async def test_does_not_return_past_events(self, session, seed_ids):
        branch_ai_id = seed_ids["branch_ai_id"]
        # Query from 2026 — all seeded events are before this
        events = await get_upcoming_events(
            session, branch_id=branch_ai_id, semester=5,
            from_date=date(2026, 1, 1), limit=10
        )
        for evt in events:
            assert evt.end_date >= date(2026, 1, 1), (
                f"Past event returned: {evt.title} ends {evt.end_date}"
            )

    @pytest.mark.asyncio
    async def test_limit_is_respected(self, session, seed_ids):
        branch_ai_id = seed_ids["branch_ai_id"]
        events = await get_upcoming_events(
            session, branch_id=branch_ai_id, semester=5,
            from_date=date(2024, 1, 1), limit=1
        )
        assert len(events) <= 1, "Limit parameter not respected"


# ---------------------------------------------------------------------------
# Tests: get_classes_by_faculty
# ---------------------------------------------------------------------------

class TestGetClassesByFaculty:

    @pytest.mark.asyncio
    async def test_faculty_sees_own_slots_only(self, session, seed_ids):
        fac_mc_id = seed_ids["fac_mc_id"]
        fac_gh_id = seed_ids["fac_gh_id"]

        mc_slots = await get_classes_by_faculty(session, faculty_id=fac_mc_id, day=0)
        gh_slots = await get_classes_by_faculty(session, faculty_id=fac_gh_id, day=0)

        mc_ids = {s.id for s in mc_slots}
        gh_ids = {s.id for s in gh_slots}
        overlap = mc_ids & gh_ids
        assert not overlap, f"Faculty queries returned overlapping slot IDs: {overlap}"

    @pytest.mark.asyncio
    async def test_faculty_with_no_slots_returns_empty(self, session, seed_ids):
        fac_na_id = seed_ids["fac_na_id"]
        # NA only teaches TUE (day=1), querying MON (day=0) should return empty
        slots = await get_classes_by_faculty(session, faculty_id=fac_na_id, day=0)
        assert slots == [], f"Expected no MON slots for NA, got {len(slots)}"
