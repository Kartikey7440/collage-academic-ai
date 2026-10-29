"""Phase 3 timetable endpoint tests.

Tests every timetable/events REST endpoint against a real Postgres
database, using in-process test data seeded by fixtures.

Run:
    python -m pytest -v tests/test_timetable_api.py

Environment:
    DATABASE_URL must be set (see .env.example).
    JWT_SECRET_KEY and COLLEGE_TIMEZONE are overridden to deterministic
    values via os.environ before any project imports.
"""

import asyncio
import os
from datetime import date, time

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-timetable-tests")
os.environ.setdefault("COLLEGE_TIMEZONE", "Asia/Kolkata")  # deterministic for CI

from api.main import app
from api.security import create_access_token
from db.models import (
    AcademicEvent,
    Base,
    Branch,
    Faculty,
    FacultyUser,
    Student,
    Subject,
    TimetableSlot,
    TimetableSlotFaculty,
    User,
    UserRole,
)
from db.session import AsyncSessionLocal, engine


# ---------------------------------------------------------------------------
# Session-scoped event loop + database bootstrap
# ---------------------------------------------------------------------------




@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database():
    """Create tables (idempotent) once per test session."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Cleanup is intentionally skipped — tests may share DB with other suites.


# ---------------------------------------------------------------------------
# Shared test data fixtures (session-scoped for speed)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def tt_branch(setup_database) -> Branch:
    """Seed and return the TT-TEST branch."""
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        result = await s.execute(select(Branch).where(Branch.code == "TT"))
        branch = result.scalars().first()
        if branch is None:
            branch = Branch(code="TT", name="Timetable Test Branch")
            s.add(branch)
            await s.commit()
            await s.refresh(branch)
    return branch


@pytest_asyncio.fixture(scope="session")
async def tt_faculty(setup_database, tt_branch) -> Faculty:
    """Seed and return a faculty reference row."""
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        result = await s.execute(select(Faculty).where(Faculty.code == "TT-FAC"))
        fac = result.scalars().first()
        if fac is None:
            fac = Faculty(code="TT-FAC", name="Dr. Test Faculty")
            s.add(fac)
            await s.commit()
            await s.refresh(fac)
    return fac


@pytest_asyncio.fixture(scope="session")
async def tt_subject(setup_database, tt_branch) -> Subject:
    """Seed and return a subject."""
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        result = await s.execute(select(Subject).where(Subject.code == "TT-SUB"))
        sub = result.scalars().first()
        if sub is None:
            sub = Subject(code="TT-SUB", name="Test Subject", branch_id=tt_branch.id, semester=3)
            s.add(sub)
            await s.commit()
            await s.refresh(sub)
    return sub


@pytest_asyncio.fixture(scope="session")
async def tt_slot(setup_database, tt_branch, tt_faculty, tt_subject) -> TimetableSlot:
    """Seed a Monday 09:00-10:00 slot for TT branch sem 3 — needs_review=False."""
    from sqlalchemy import select, and_

    async with AsyncSessionLocal() as s:
        result = await s.execute(
            select(TimetableSlot).where(
                and_(
                    TimetableSlot.branch_id == tt_branch.id,
                    TimetableSlot.semester == 3,
                    TimetableSlot.day_of_week == 0,
                    TimetableSlot.subject_id == tt_subject.id,
                    TimetableSlot.needs_review == False,  # noqa: E712
                )
            )
        )
        slot = result.scalars().first()
        if slot is None:
            slot = TimetableSlot(
                branch_id=tt_branch.id,
                semester=3,
                subject_id=tt_subject.id,
                day_of_week=0,  # Monday
                start_time=time(9, 0),
                end_time=time(10, 0),
                room="TT-101",
                academic_session="2024-25-ODD",
                effective_from=date(2024, 8, 1),
                needs_review=False,
            )
            s.add(slot)
            await s.flush()
            s.add(TimetableSlotFaculty(slot_id=slot.id, faculty_id=tt_faculty.id))
            await s.commit()
            await s.refresh(slot)
    return slot


@pytest_asyncio.fixture(scope="session")
async def tt_slot_review(setup_database, tt_branch, tt_subject) -> TimetableSlot:
    """Seed a Monday 10:00-11:00 slot with needs_review=True (no confirmed faculty)."""
    from sqlalchemy import select, and_

    async with AsyncSessionLocal() as s:
        result = await s.execute(
            select(TimetableSlot).where(
                and_(
                    TimetableSlot.branch_id == tt_branch.id,
                    TimetableSlot.semester == 3,
                    TimetableSlot.day_of_week == 0,
                    TimetableSlot.subject_id == tt_subject.id,
                    TimetableSlot.needs_review == True,  # noqa: E712
                )
            )
        )
        slot = result.scalars().first()
        if slot is None:
            slot = TimetableSlot(
                branch_id=tt_branch.id,
                semester=3,
                subject_id=tt_subject.id,
                day_of_week=0,  # Monday
                start_time=time(10, 0),
                end_time=time(11, 0),
                room="TT-102",
                academic_session="2024-25-ODD",
                effective_from=date(2024, 8, 1),
                needs_review=True,
                review_reason="Unresolved elective — faculty not confirmed",
            )
            s.add(slot)
            await s.commit()
            await s.refresh(slot)
    return slot


@pytest_asyncio.fixture(scope="session")
async def tt_event(setup_database, tt_branch) -> AcademicEvent:
    """Seed an institution-wide suppressing holiday."""
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        result = await s.execute(
            select(AcademicEvent).where(AcademicEvent.title == "TT Test Holiday")
        )
        ev = result.scalars().first()
        if ev is None:
            ev = AcademicEvent(
                event_type="holiday",
                title="TT Test Holiday",
                start_date=date(2099, 1, 1),
                end_date=date(2099, 1, 2),
                suppresses_timetable=True,
            )
            s.add(ev)
            await s.commit()
            await s.refresh(ev)
    return ev


# ---------------------------------------------------------------------------
# User fixtures — student and faculty
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def student_token(setup_database, tt_branch, tt_slot) -> str:
    """Create a student user scoped to TT branch sem 3, return access token."""
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        result = await s.execute(select(User).where(User.email == "tt-student@test.local"))
        user = result.scalars().first()
        if user is None:
            from api.security import hash_password
            user = User(
                email="tt-student@test.local",
                password_hash=hash_password("password1234"),
                role=UserRole.student,
            )
            s.add(user)
            await s.flush()
            student = Student(
                user_id=user.id,
                branch_id=tt_branch.id,
                semester=3,
                roll_no="TT/001",
            )
            s.add(student)
            await s.commit()
            await s.refresh(user)

    return create_access_token(user.id, "student")


@pytest_asyncio.fixture(scope="session")
async def faculty_token(setup_database, tt_faculty, tt_slot) -> str:
    """Create a faculty user linked to tt_faculty, return access token."""
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        result = await s.execute(select(User).where(User.email == "tt-faculty@test.local"))
        user = result.scalars().first()
        if user is None:
            from api.security import hash_password
            user = User(
                email="tt-faculty@test.local",
                password_hash=hash_password("password1234"),
                role=UserRole.faculty,
            )
            s.add(user)
            await s.flush()
            s.add(FacultyUser(user_id=user.id, faculty_id=tt_faculty.id))
            await s.commit()
            await s.refresh(user)

    return create_access_token(user.id, "faculty")


@pytest_asyncio.fixture(scope="session")
async def admin_token(setup_database) -> str:
    """Create an admin user and return access token."""
    from sqlalchemy import select

    async with AsyncSessionLocal() as s:
        result = await s.execute(select(User).where(User.email == "tt-admin@test.local"))
        user = result.scalars().first()
        if user is None:
            from api.security import hash_password
            user = User(
                email="tt-admin@test.local",
                password_hash=hash_password("password1234"),
                role=UserRole.admin,
            )
            s.add(user)
            await s.commit()
            await s.refresh(user)

    return create_access_token(user.id, "admin")


# ---------------------------------------------------------------------------
# Test client
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# GET /timetable/day/{day} — basic shape tests
# ---------------------------------------------------------------------------


class TestTimetableDayEndpoint:
    def test_student_gets_monday_classes(self, client, student_token, tt_slot, tt_slot_review):
        """Student sees both confirmed and needs_review Monday slots."""
        resp = client.get(
            "/api/v1/timetable/day/0",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 200, resp.text
        slots = resp.json()
        assert isinstance(slots, list)
        slot_ids = [s["id"] for s in slots]

        # The confirmed slot must appear
        assert tt_slot.id in slot_ids
        # Students now SEE needs_review slots (needs_review=true in response)
        assert tt_slot_review.id in slot_ids

        # Validate shape of the confirmed slot
        found = next(s for s in slots if s["id"] == tt_slot.id)
        assert found["day_of_week"] == 0
        assert found["day_name"] == "Monday"  # Issue 6: human-readable name
        assert found["start_time"] == "09:00:00"
        assert found["end_time"] == "10:00:00"
        assert found["room"] == "TT-101"
        assert found["needs_review"] is False
        assert found["subject"]["code"] == "TT-SUB"
        assert len(found["faculty"]) == 1
        assert found["faculty"][0]["code"] == "TT-FAC"

        found_rev = next(s for s in slots if s["id"] == tt_slot_review.id)
        assert found_rev["needs_review"] is True

    def test_admin_sees_needs_review_slot(self, client, admin_token, tt_branch, tt_slot, tt_slot_review):
        """Admin sees ALL slots including needs_review=True ones."""
        resp = client.get(
            f"/api/v1/timetable/day/0?branch_id={tt_branch.id}&semester=3",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        slot_ids = [s["id"] for s in resp.json()]
        assert tt_slot.id in slot_ids
        assert tt_slot_review.id in slot_ids, (
            "Admin must see needs_review=True slots"
        )

    def test_day_name_present_in_all_slots(self, client, student_token, tt_slot):
        """Every slot in the response carries a 'day_name' string."""
        resp = client.get(
            "/api/v1/timetable/day/0",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 200
        for slot in resp.json():
            assert "day_name" in slot
            assert isinstance(slot["day_name"], str)
            assert len(slot["day_name"]) > 0

    def test_student_sees_no_classes_on_sunday(self, client, student_token):
        """No slots exist for Sunday — should return an empty list."""
        resp = client.get(
            "/api/v1/timetable/day/6",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_invalid_day_returns_422(self, client, student_token):
        """Day out of 0-6 range must return 422."""
        resp = client.get(
            "/api/v1/timetable/day/7",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 422

    def test_unauthenticated_returns_403(self, client):
        """No Bearer token → 401."""
        resp = client.get("/api/v1/timetable/day/0")
        assert resp.status_code == 401

    def test_faculty_sees_their_monday_slot(self, client, faculty_token, tt_slot):
        """Faculty gets their own slots including needs_review (flag visible)."""
        resp = client.get(
            "/api/v1/timetable/day/0",
            headers={"Authorization": f"Bearer {faculty_token}"},
        )
        assert resp.status_code == 200
        slot_ids = [s["id"] for s in resp.json()]
        assert tt_slot.id in slot_ids

    def test_admin_requires_branch_and_semester(self, client, admin_token):
        """Admin without query params must get 422."""
        resp = client.get(
            "/api/v1/timetable/day/0",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 422

    def test_admin_with_params_gets_slots(self, client, admin_token, tt_branch, tt_slot):
        """Admin supplies branch_id + semester and sees the same slot."""
        resp = client.get(
            f"/api/v1/timetable/day/0?branch_id={tt_branch.id}&semester=3",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        slot_ids = [s["id"] for s in resp.json()]
        assert tt_slot.id in slot_ids


# ---------------------------------------------------------------------------
# GET /timetable/today
# ---------------------------------------------------------------------------


class TestTimetableTodayEndpoint:
    def test_student_gets_list(self, client, student_token):
        """Today endpoint returns a list (may be empty if today is Sunday)."""
        resp = client.get(
            "/api/v1/timetable/today",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_faculty_gets_list(self, client, faculty_token):
        resp = client.get(
            "/api/v1/timetable/today",
            headers={"Authorization": f"Bearer {faculty_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# GET /timetable/next-class
# ---------------------------------------------------------------------------


class TestNextClassEndpoint:
    def test_student_gets_null_or_slot(self, client, student_token):
        """next-class returns null or a valid slot — never errors."""
        resp = client.get(
            "/api/v1/timetable/next-class",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body is None or isinstance(body, dict)
        # If a slot is returned, it has needs_review boolean
        if body is not None:
            assert isinstance(body["needs_review"], bool)

    def test_faculty_next_class_succeeds(self, client, faculty_token):
        """Faculty can call next-class; returns null or a slot (never 400)."""
        resp = client.get(
            "/api/v1/timetable/next-class",
            headers={"Authorization": f"Bearer {faculty_token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body is None or isinstance(body, dict)


# ---------------------------------------------------------------------------
# GET /timetable/suppressed
# ---------------------------------------------------------------------------


class TestSuppressedEndpoint:
    def test_far_future_holiday_suppresses(self, client, student_token, tt_event):
        """The seeded far-future holiday (2099-01-01) must return suppressed=True."""
        resp = client.get(
            "/api/v1/timetable/suppressed?check_date=2099-01-01",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["suppressed"] is True
        assert body["check_date"] == "2099-01-01"

    def test_non_holiday_date_not_suppressed(self, client, student_token):
        """A random non-holiday date in the future should return suppressed=False."""
        resp = client.get(
            "/api/v1/timetable/suppressed?check_date=2030-06-15",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["suppressed"] is False

    def test_defaults_to_today(self, client, student_token):
        """Calling suppressed without check_date uses today (won't error)."""
        resp = client.get(
            "/api/v1/timetable/suppressed",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 200
        assert "suppressed" in resp.json()


# ---------------------------------------------------------------------------
# GET /events/upcoming
# ---------------------------------------------------------------------------


class TestUpcomingEventsEndpoint:
    def test_student_gets_events_list(self, client, student_token, tt_event):
        """Upcoming events returns a list including our seeded far-future holiday."""
        resp = client.get(
            "/api/v1/events/upcoming?from_date=2099-01-01",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 200
        events = resp.json()
        assert isinstance(events, list)
        titles = [e["title"] for e in events]
        assert "TT Test Holiday" in titles

    def test_event_shape(self, client, student_token, tt_event):
        """Each event has the expected keys."""
        resp = client.get(
            "/api/v1/events/upcoming?from_date=2099-01-01",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 200
        event = next(e for e in resp.json() if e["title"] == "TT Test Holiday")
        assert event["event_type"] == "holiday"
        assert event["suppresses_timetable"] is True
        assert event["start_date"] == "2099-01-01"
        assert event["end_date"] == "2099-01-02"

    def test_limit_is_respected(self, client, student_token):
        """limit=1 returns at most 1 event."""
        resp = client.get(
            "/api/v1/events/upcoming?limit=1",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) <= 1

    def test_limit_out_of_range_returns_422(self, client, student_token):
        """limit=0 is below the minimum — should 422."""
        resp = client.get(
            "/api/v1/events/upcoming?limit=0",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert resp.status_code == 422

    def test_faculty_gets_events_list(self, client, faculty_token, tt_event):
        resp = client.get(
            "/api/v1/events/upcoming?from_date=2099-01-01",
            headers={"Authorization": f"Bearer {faculty_token}"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_admin_no_params_gets_institution_wide(self, client, admin_token, tt_event):
        """Admin without params sees institution-wide events (branch_id IS NULL)."""
        resp = client.get(
            "/api/v1/events/upcoming?from_date=2099-01-01",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        # The seeded holiday has no branch_id — should appear
        titles = [e["title"] for e in resp.json()]
        assert "TT Test Holiday" in titles
