"""Tests for api.timetable_service access rules and api.clock.

Tests access control for:
- Student: only own branch/sem, sees needs_review slots, incomplete profile raises 403
- Faculty: only assigned slots, incomplete profile raises 403
- Admin: requires branch_id and semester (raises 422 if omitted), unrestricted=True
- upcoming_class: later today (ahead=0), tomorrow (ahead=1), wraps to next week (ahead>1 or ahead=7)
- clock: current_now() honours DEMO_NOW
"""

import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from api import clock
from api import timetable_service as service
from api.deps import ScopedIdentity
from db.models import Branch, Faculty, Subject, TimetableSlot
from db.seed import seed_database
from db.session import AsyncSessionLocal, engine


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database():
    seed_ids = await seed_database()
    yield seed_ids


@pytest_asyncio.fixture
async def session():
    async with AsyncSessionLocal() as s:
        yield s


# ---------------------------------------------------------------------------
# Tests: classes() access rules
# ---------------------------------------------------------------------------

class TestTimetableServiceClasses:
    @pytest.mark.asyncio
    async def test_student_sees_own_scope_and_needs_review(self, session, setup_database):
        branch_ai_id = setup_database["branch_ai_id"]
        identity = ScopedIdentity(
            user_id=1,
            role="student",
            branch_id=branch_ai_id,
            semester=5,
            section=None,
            batch=None,
        )

        slots = await service.classes(session, identity, day=1)  # Tuesday
        assert len(slots) >= 1
        assert all(s.branch_id == branch_ai_id for s in slots)
        assert all(s.semester == 5 for s in slots)

        # Students now SEE needs_review slots (unconfirmed)
        assert any(s.needs_review is True for s in slots), (
            "Students must see needs_review slots when SHOW_UNCONFIRMED_TO_STUDENTS is True"
        )

    @pytest.mark.asyncio
    async def test_student_incomplete_profile_raises_403(self, session):
        identity_no_branch = ScopedIdentity(
            user_id=1, role="student", branch_id=None, semester=5
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.classes(session, identity_no_branch, day=1)
        assert exc_info.value.status_code == 403

        identity_no_sem = ScopedIdentity(
            user_id=1, role="student", branch_id=1, semester=None
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.classes(session, identity_no_sem, day=1)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_faculty_sees_only_assigned_slots(self, session, setup_database):
        fac_mc_id = setup_database["fac_mc_id"]
        identity = ScopedIdentity(
            user_id=2, role="faculty", faculty_id=fac_mc_id
        )

        slots = await service.classes(session, identity, day=0)  # Monday
        assert len(slots) >= 1
        for s in slots:
            faculty_ids = [fa.faculty_id for fa in s.faculty_assignments]
            assert fac_mc_id in faculty_ids

    @pytest.mark.asyncio
    async def test_faculty_missing_profile_raises_403(self, session):
        identity = ScopedIdentity(user_id=2, role="faculty", faculty_id=None)
        with pytest.raises(HTTPException) as exc_info:
            await service.classes(session, identity, day=0)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_requires_branch_and_semester(self, session, setup_database):
        branch_ai_id = setup_database["branch_ai_id"]
        admin_identity = ScopedIdentity(user_id=99, role="admin")

        # Missing both
        with pytest.raises(HTTPException) as exc_info:
            await service.classes(session, admin_identity, day=1)
        assert exc_info.value.status_code == 422

        # Missing semester
        with pytest.raises(HTTPException) as exc_info:
            await service.classes(session, admin_identity, day=1, branch_id=branch_ai_id)
        assert exc_info.value.status_code == 422

        # Missing branch_id
        with pytest.raises(HTTPException) as exc_info:
            await service.classes(session, admin_identity, day=1, semester=5)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_admin_sees_unrestricted_slots(self, session, setup_database):
        branch_ai_id = setup_database["branch_ai_id"]
        admin_identity = ScopedIdentity(user_id=99, role="admin")

        slots = await service.classes(
            session, admin_identity, day=1, branch_id=branch_ai_id, semester=5
        )
        assert len(slots) >= 5
        assert all(s.branch_id == branch_ai_id for s in slots)

    @pytest.mark.asyncio
    async def test_classes_day_none_returns_whole_week(self, session, setup_database):
        branch_ai_id = setup_database["branch_ai_id"]
        identity = ScopedIdentity(
            user_id=1,
            role="student",
            branch_id=branch_ai_id,
            semester=5,
            section=None,
            batch=None,
        )
        week = await service.classes(session, identity, day=None)
        assert len(week) > 5
        days = {s.day_of_week for s in week}
        assert len(days) > 1


# ---------------------------------------------------------------------------
# Tests: upcoming_class()
# ---------------------------------------------------------------------------

class TestTimetableServiceUpcomingClass:
    @pytest.mark.asyncio
    async def test_upcoming_class_later_today(self, session, setup_database):
        branch_ai_id = setup_database["branch_ai_id"]
        identity = ScopedIdentity(
            user_id=1,
            role="student",
            branch_id=branch_ai_id,
            semester=5,
            section=None,
            batch=None,
        )
        # Tuesday at 10:30 (class at 10:00 already started; next is at 11:00)
        tuesday_1030 = datetime(2024, 7, 2, 10, 30)
        assert tuesday_1030.weekday() == 1  # Tuesday

        slot, ahead = await service.upcoming_class(session, identity, tuesday_1030)
        assert slot is not None
        assert ahead == 0, f"Expected ahead=0 (later today), got {ahead}"
        assert slot.day_of_week == 1
        assert slot.start_time > time(10, 30)

    @pytest.mark.asyncio
    async def test_upcoming_class_tomorrow(self, session, setup_database):
        branch_ai_id = setup_database["branch_ai_id"]
        identity = ScopedIdentity(
            user_id=1,
            role="student",
            branch_id=branch_ai_id,
            semester=5,
            section=None,
            batch=None,
        )
        # Monday night at 23:00 (no more classes on Monday; next is Tuesday 10:00)
        monday_2300 = datetime(2024, 7, 1, 23, 0)
        assert monday_2300.weekday() == 0  # Monday

        slot, ahead = await service.upcoming_class(session, identity, monday_2300)
        assert slot is not None
        assert ahead == 1, f"Expected ahead=1 (tomorrow), got {ahead}"
        assert slot.day_of_week == 1  # Tuesday

    @pytest.mark.asyncio
    async def test_upcoming_class_wraps_to_next_week(self, session, setup_database):
        branch_ai_id = setup_database["branch_ai_id"]
        identity = ScopedIdentity(
            user_id=1,
            role="student",
            branch_id=branch_ai_id,
            semester=5,
            section=None,
            batch=None,
        )
        # Saturday night at 20:00 (no weekend classes; wraps to Monday)
        saturday_2000 = datetime(2024, 7, 6, 20, 0)
        assert saturday_2000.weekday() == 5  # Saturday

        slot, ahead = await service.upcoming_class(session, identity, saturday_2000)
        assert slot is not None
        assert ahead == 2, f"Expected ahead=2 (Monday), got {ahead}"
        assert slot.day_of_week == 0  # Monday

    @pytest.mark.asyncio
    async def test_upcoming_class_wraps_7_days_ahead(self):
        """When classes are only on one weekday and today's class has passed, wraps 7 days."""
        mock_slot = TimetableSlot(
            id=999,
            day_of_week=2,  # Wednesday only
            start_time=time(10, 0),
            end_time=time(11, 0),
        )
        identity = ScopedIdentity(user_id=1, role="student", branch_id=1, semester=1)
        wednesday_night = datetime(2024, 7, 3, 22, 0)  # Wednesday at 22:00
        assert wednesday_night.weekday() == 2

        with patch.object(service, "classes", new=AsyncMock(return_value=[mock_slot])):
            slot, ahead = await service.upcoming_class(None, identity, wednesday_night)
            assert slot is not None
            assert ahead == 7, f"Expected ahead=7 (next week Wednesday), got {ahead}"
            assert slot.id == 999


# ---------------------------------------------------------------------------
# Tests: Clock / DEMO_NOW
# ---------------------------------------------------------------------------

class TestClockDemoNow:
    def test_current_now_normal(self):
        now = clock.current_now()
        assert isinstance(now, datetime)
        assert now.tzinfo is not None

    def test_current_now_honours_demo_now(self, monkeypatch):
        demo_target = datetime(2026, 11, 3, 11, 30, tzinfo=clock.now_college().tzinfo)
        monkeypatch.setattr(clock, "_demo_start", demo_target)
        monkeypatch.setattr(clock, "_real_start", clock.now_college())
        simulated = clock.current_now()
        # Simulated time should be within 2 seconds of demo_target
        assert abs((simulated - demo_target).total_seconds()) < 2
        assert clock.demo_clock_active() is True
