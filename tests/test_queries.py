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
from sqlalchemy import select, text
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
    normalize_label,
    slot_scope_conditions,
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


# ---------------------------------------------------------------------------
# Fixture: Section-specific slots for CS branch
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def section_slots(setup_database):
    """Seed slots with NULL and specific section on Thursday (day=3) for CS sem 5."""
    from db.models import Subject
    seed_ids = setup_database
    branch_cs_id = seed_ids["branch_cs_id"]
    async with AsyncSessionLocal() as s:
        # Check if already seeded
        res = await s.execute(
            select(TimetableSlot).where(
                TimetableSlot.branch_id == branch_cs_id,
                TimetableSlot.semester == 5,
                TimetableSlot.day_of_week == 3,
            )
        )
        existing = res.scalars().all()
        if existing:
            return existing

        subj_res = await s.execute(
            select(Subject).where(Subject.branch_id == branch_cs_id, Subject.semester == 5)
        )
        subj = subj_res.scalars().first()
        created = []
        for sec, tm in [(None, time(9, 0)), ("A", time(10, 0)), ("B", time(11, 0))]:
            slot = TimetableSlot(
                branch_id=branch_cs_id,
                semester=5,
                subject_id=subj.id,
                day_of_week=3,  # Thursday
                start_time=tm,
                end_time=time(tm.hour + 1, 0),
                room=f"SEC-{sec or 'NULL'}",
                section=sec,
                batch=None,
                academic_session="2024-25-ODD",
                effective_from=date(2024, 7, 1),
                needs_review=False,
            )
            s.add(slot)
            created.append(slot)
        await s.commit()
        for sl in created:
            await s.refresh(sl)
        return created


# ---------------------------------------------------------------------------
# Tests: Label Normalisation
# ---------------------------------------------------------------------------

class TestNormalizeLabel:
    def test_empty_string_returns_none(self):
        assert normalize_label("") is None
        assert normalize_label("   ") is None

    def test_null_and_none_strings_return_none(self):
        assert normalize_label("null") is None
        assert normalize_label("NULL") is None
        assert normalize_label("  null  ") is None
        assert normalize_label("none") is None
        assert normalize_label("NONE") is None
        assert normalize_label("  None  ") is None

    def test_none_input_returns_none(self):
        assert normalize_label(None) is None

    def test_labels_are_trimmed_and_uppercased(self):
        assert normalize_label("  a  ") == "A"
        assert normalize_label("b") == "B"
        assert normalize_label("a+b") == "A+B"
        assert normalize_label("  batch-1 ") == "BATCH-1"


# ---------------------------------------------------------------------------
# Tests: Batch Scope Conditions (NULL, "A", "B", "C")
# ---------------------------------------------------------------------------

class TestBatchScopeConditions:
    """A NULL-batch slot is visible to everyone; "A+B" to students in A or B;

    single-batch "B" only to batch B; student with no batch sees NULL and "A+B".
    """

    @pytest.mark.asyncio
    async def test_ai_tuesday_batches(self, session, seed_ids):
        # AI sem 5 on Tuesday has 5 NULL-batch slots (including seed) and 1 "A+B" joint slot
        branch_ai_id = seed_ids["branch_ai_id"]

        # Student with batch=None sees NULL-batch and joint "A+B" slots
        slots_none = await get_todays_classes(
            session, branch_ai_id, 5, section=None, batch=None, day=1
        )
        assert len(slots_none) == 6
        assert any(s.batch == "A+B" for s in slots_none)
        assert any(s.batch is None for s in slots_none)

        # Student with batch="A" sees NULL-batch and "A+B"
        slots_a = await get_todays_classes(
            session, branch_ai_id, 5, section=None, batch="A", day=1
        )
        assert len(slots_a) == 6
        assert any(s.batch == "A+B" for s in slots_a)

        # Student with batch="B" sees NULL-batch and "A+B"
        slots_b = await get_todays_classes(
            session, branch_ai_id, 5, section=None, batch="B", day=1
        )
        assert len(slots_b) == 6
        assert any(s.batch == "A+B" for s in slots_b)

        # Student with batch="C" sees only NULL-batch slots, NOT "A+B"
        slots_c = await get_todays_classes(
            session, branch_ai_id, 5, section=None, batch="C", day=1
        )
        assert len(slots_c) == 5
        assert not any(s.batch == "A+B" for s in slots_c)
        assert all(s.batch is None for s in slots_c)

    @pytest.mark.asyncio
    async def test_single_batch_slot_visibility(self, session):
        # Check AIML branch (id=4) sem 5 Tuesday, which has a single-batch "B" slot
        res = await session.execute(
            select(Branch.id).where(Branch.code == "AIML")
        )
        aiml_id = res.scalar()
        if aiml_id is None:
            pytest.skip("AIML branch not present in database")

        slots_b = await get_todays_classes(
            session, aiml_id, 5, section=None, batch="B", day=1
        )
        # Should see the single-batch "B" slot
        assert any(s.batch == "B" for s in slots_b)

        # Batch "A", "C", and None must NOT see the single-batch "B" slot
        slots_a = await get_todays_classes(
            session, aiml_id, 5, section=None, batch="A", day=1
        )
        assert not any(s.batch == "B" for s in slots_a)

        slots_c = await get_todays_classes(
            session, aiml_id, 5, section=None, batch="C", day=1
        )
        assert not any(s.batch == "B" for s in slots_c)

        slots_none = await get_todays_classes(
            session, aiml_id, 5, section=None, batch=None, day=1
        )
        assert not any(s.batch == "B" for s in slots_none)


# ---------------------------------------------------------------------------
# Tests: Section Scope Conditions
# ---------------------------------------------------------------------------

class TestSectionScopeConditions:
    """NULL-section slots are visible to all sections; section-specific only to that section;

    student with no section sees only NULL-section slots.
    """

    @pytest.mark.asyncio
    async def test_section_rules(self, session, seed_ids, section_slots):
        branch_cs_id = seed_ids["branch_cs_id"]

        # Student with no section (None) sees only NULL-section slots
        slots_none = await get_todays_classes(
            session, branch_cs_id, 5, section=None, batch=None, day=3
        )
        assert len(slots_none) == 1
        assert slots_none[0].section is None

        # Student with section="A" sees NULL-section slot AND section "A" slot
        slots_a = await get_todays_classes(
            session, branch_cs_id, 5, section="A", batch=None, day=3
        )
        assert len(slots_a) == 2
        sections_a = {s.section for s in slots_a}
        assert sections_a == {None, "A"}

        # Student with section="B" sees NULL-section slot AND section "B" slot
        slots_b = await get_todays_classes(
            session, branch_cs_id, 5, section="B", batch=None, day=3
        )
        assert len(slots_b) == 2
        sections_b = {s.section for s in slots_b}
        assert sections_b == {None, "B"}

        # Student with section="C" sees only NULL-section slot
        slots_c = await get_todays_classes(
            session, branch_cs_id, 5, section="C", batch=None, day=3
        )
        assert len(slots_c) == 1
        assert slots_c[0].section is None

    @pytest.mark.asyncio
    async def test_section_label_normalisation_in_query(self, session, seed_ids, section_slots):
        branch_cs_id = seed_ids["branch_cs_id"]

        # section="  a  " matches section "A"
        slots_trimmed = await get_todays_classes(
            session, branch_cs_id, 5, section="  a  ", batch=None, day=3
        )
        assert len(slots_trimmed) == 2

        # section="none" treated as no section (None)
        slots_none_str = await get_todays_classes(
            session, branch_cs_id, 5, section="none", batch=None, day=3
        )
        assert len(slots_none_str) == 1
        assert slots_none_str[0].section is None


# ---------------------------------------------------------------------------
# Tests: Admin Unrestricted
# ---------------------------------------------------------------------------

class TestAdminUnrestricted:
    """unrestricted=True bypasses section/batch restrictions but retains branch and semester."""

    @pytest.mark.asyncio
    async def test_unrestricted_sees_all_sections(self, session, seed_ids, section_slots):
        branch_cs_id = seed_ids["branch_cs_id"]

        # Regular student without section sees 1 slot
        restricted = await get_todays_classes(
            session, branch_cs_id, 5, section=None, batch=None, day=3, unrestricted=False
        )
        assert len(restricted) == 1

        # Admin with unrestricted=True sees all 3 slots
        unrestricted = await get_todays_classes(
            session, branch_cs_id, 5, section=None, batch=None, day=3, unrestricted=True
        )
        assert len(unrestricted) == 3
        sections = {s.section for s in unrestricted}
        assert sections == {None, "A", "B"}

    @pytest.mark.asyncio
    async def test_unrestricted_get_next_class(self, session, seed_ids, section_slots):
        branch_cs_id = seed_ids["branch_cs_id"]
        # Query at 09:30 on Thursday (between 09:00 NULL slot and 10:00 "A" slot)
        now = datetime(2024, 7, 4, 9, 30)  # Thursday

        # Student without section has no slots left after 09:30
        next_student = await get_next_class(
            session, branch_cs_id, 5, section=None, batch=None, now=now, unrestricted=False
        )
        assert next_student is None

        # Admin with unrestricted=True sees the 10:00 section "A" slot
        next_admin = await get_next_class(
            session, branch_cs_id, 5, section=None, batch=None, now=now, unrestricted=True
        )
        assert next_admin is not None
        assert next_admin.section == "A"
        assert next_admin.start_time == time(10, 0)


# ---------------------------------------------------------------------------
# Tests: Branch and Semester Never Leak
# ---------------------------------------------------------------------------

class TestBranchAndSemesterNeverLeak:
    """Branch and semester scoping is absolute and can never leak across tenants."""

    @pytest.mark.asyncio
    async def test_queries_never_leak_different_branch(self, session, seed_ids):
        branch_ai_id = seed_ids["branch_ai_id"]
        branch_cs_id = seed_ids["branch_cs_id"]

        ai_slots = await get_todays_classes(
            session, branch_ai_id, 5, section=None, batch=None, day=None
        )
        assert all(s.branch_id == branch_ai_id for s in ai_slots)

        cs_slots = await get_todays_classes(
            session, branch_cs_id, 5, section=None, batch=None, day=None
        )
        assert all(s.branch_id == branch_cs_id for s in cs_slots)

    @pytest.mark.asyncio
    async def test_queries_never_leak_different_semester(self, session, seed_ids):
        branch_ai_id = seed_ids["branch_ai_id"]

        # AI sem 5 slots
        sem5_slots = await get_todays_classes(
            session, branch_ai_id, 5, section=None, batch=None, day=None
        )
        assert all(s.semester == 5 for s in sem5_slots)

        # AI sem 99 should return empty
        sem99_slots = await get_todays_classes(
            session, branch_ai_id, 99, section=None, batch=None, day=None
        )
        assert sem99_slots == []

    @pytest.mark.asyncio
    async def test_unrestricted_does_not_leak_other_branches(self, session, seed_ids):
        branch_ai_id = seed_ids["branch_ai_id"]
        branch_cs_id = seed_ids["branch_cs_id"]

        slots = await get_todays_classes(
            session, branch_ai_id, 5, section=None, batch=None, day=None, unrestricted=True
        )
        assert all(s.branch_id == branch_ai_id for s in slots)
        assert not any(s.branch_id == branch_cs_id for s in slots)


# ---------------------------------------------------------------------------
# Tests: day=None (whole week)
# ---------------------------------------------------------------------------

class TestDayNone:
    """day=None returns classes for the whole week ordered by day, then start_time."""

    @pytest.mark.asyncio
    async def test_todays_classes_day_none_returns_whole_week(self, session, seed_ids):
        branch_ai_id = seed_ids["branch_ai_id"]
        slots = await get_todays_classes(
            session, branch_ai_id, 5, section=None, batch=None, day=None
        )
        assert len(slots) > 5, "Expected whole week of AI classes"
        days_seen = {s.day_of_week for s in slots}
        assert len(days_seen) > 1, f"Expected multiple days in whole week, got {days_seen}"

        # Verify ordering: (day_of_week, start_time)
        pairs = [(s.day_of_week, s.start_time) for s in slots]
        assert pairs == sorted(pairs), "Slots not ordered by (day_of_week, start_time)"

    @pytest.mark.asyncio
    async def test_classes_by_faculty_day_none_returns_whole_week(self, session, seed_ids):
        fac_mc_id = seed_ids["fac_mc_id"]
        slots = await get_classes_by_faculty(session, faculty_id=fac_mc_id, day=None)
        assert len(slots) >= 1
        pairs = [(s.day_of_week, s.start_time) for s in slots]
        assert pairs == sorted(pairs), "Faculty slots not ordered by (day_of_week, start_time)"


# ---------------------------------------------------------------------------
# Regression: batch "A" student sees AI Tuesday non-lab classes
# ---------------------------------------------------------------------------

class TestRegressionBatchATuesdayAI:
    @pytest.mark.asyncio
    async def test_batch_a_sees_ai_tuesday_non_lab_classes(self, session, seed_ids):
        """A student with batch 'A' must see the whole-class (non-lab) slots on Tuesday."""
        branch_ai_id = seed_ids["branch_ai_id"]
        slots = await get_todays_classes(
            session,
            branch_id=branch_ai_id,
            semester=5,
            section=None,
            batch="A",
            day=1,  # TUE
        )

        non_lab_slots = [s for s in slots if s.batch is None]
        assert len(non_lab_slots) >= 4, (
            f"Expected at least 4 non-lab slots on Tuesday for batch 'A', got {len(non_lab_slots)}"
        )
        subjects = {s.subject.name for s in non_lab_slots if s.subject}
        assert "Cloud Computing & Virtualization" in subjects
        assert "Machine Learning" in subjects
        assert "Statistical Computing" in subjects

