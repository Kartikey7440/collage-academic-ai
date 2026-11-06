"""Tests for 3rd semester (2nd year) timetable extraction and ingestion.

Verifies:
1. File schema & integrity for out_sem3.json (114 slots across AI, AIR, AIDS, AIML).
2. Database ingestion via load_json into test database.
3. Scoped query isolation for 3rd semester students (branch & semester boundaries).
4. REST API timetable endpoint (GET /api/v1/timetable/day/{d}) for 3rd semester students.
5. Admin review queue visibility for flagged 3rd semester slots.
"""

import json
from datetime import date, time
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from api.main import app
from api.security import create_access_token, hash_password
from db.loader import load_json
from db.models import Branch, Student, TimetableSlot, User, UserRole
from db.queries import get_todays_classes
from db.session import AsyncSessionLocal

SEM3_JSON_PATH = Path(__file__).resolve().parents[1] / "out_sem3.json"


# ---------------------------------------------------------------------------
# Test 1: JSON Data Integrity & Schema
# ---------------------------------------------------------------------------

class TestSem3DataIntegrity:
    def test_out_sem3_json_exists_and_conforms_to_schema(self):
        assert SEM3_JSON_PATH.exists(), f"{SEM3_JSON_PATH} not found"
        with open(SEM3_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert len(data) >= 100, f"Expected at least 100 entries, got {len(data)}"
        valid_branches = {"AI", "AIR", "AIDS", "AIML"}
        valid_days = {"MON", "TUE", "WED", "THU", "FRI", "SAT"}

        for entry in data:
            assert entry["type"] == "timetable_entry"
            assert entry["branch"] in valid_branches
            assert entry["semester"] == 3
            assert entry["day"] in valid_days
            assert ":" in entry["start_time"]
            assert ":" in entry["end_time"]
            assert isinstance(entry["needs_review"], bool)
            assert isinstance(entry["faculty_codes"], list)


# ---------------------------------------------------------------------------
# Session fixture: Ingest 3rd sem data into the test database
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def sem3_ingestion(init_test_database):
    """Ingest 3rd sem timetable JSON into the test database once."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(func.count(TimetableSlot.id)).where(TimetableSlot.semester == 3)
        )
        count = result.scalar()
        if count and count >= 100:
            return True

    await load_json(
        json_path=str(SEM3_JSON_PATH),
        academic_session="2026-27-ODD",
        doc_filename="III Sem TT July-Dec 2026 w.e.f. 13.8.2026.pdf",
    )
    return True


@pytest_asyncio.fixture(scope="session")
async def sem3_ai_student(init_test_database, sem3_ingestion):
    """Create a 3rd semester AI student (Section 1)."""
    async with AsyncSessionLocal() as s:
        branch_res = await s.execute(select(Branch).where(Branch.code == "AI"))
        ai_branch = branch_res.scalars().first()

        user_res = await s.execute(select(User).where(User.email == "sem3_ai_s1@test.local"))
        user = user_res.scalars().first()
        if user is None:
            user = User(
                email="sem3_ai_s1@test.local",
                password_hash=hash_password("password1234"),
                role=UserRole.student,
            )
            s.add(user)
            await s.flush()
            student = Student(
                user_id=user.id,
                branch_id=ai_branch.id,
                semester=3,
                section="1",
                batch=None,
                roll_no="AI2025001",
            )
            s.add(student)
            await s.commit()
            await s.refresh(user)

    token = create_access_token(user.id, "student")
    return {"user_id": user.id, "branch_id": ai_branch.id, "token": token}


@pytest_asyncio.fixture(scope="session")
async def admin_token_fixture(init_test_database):
    """Ensure an admin user exists and return a valid admin token."""
    async with AsyncSessionLocal() as s:
        user_res = await s.execute(select(User).where(User.email == "sem3_admin@test.local"))
        user = user_res.scalars().first()
        if user is None:
            user = User(
                email="sem3_admin@test.local",
                password_hash=hash_password("password1234"),
                role=UserRole.admin,
            )
            s.add(user)
            await s.commit()
            await s.refresh(user)
    return create_access_token(user.id, "admin")


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Test 2: Database Query Scoping for 3rd Semester
# ---------------------------------------------------------------------------

class TestSem3DatabaseQueries:
    @pytest.mark.asyncio
    async def test_ai_sem3_slots_retrieved_and_isolated_from_sem5(self, sem3_ai_student):
        branch_id = sem3_ai_student["branch_id"]
        async with AsyncSessionLocal() as s:
            # Query Tuesday (day=1) for Sem 3, Section 1
            slots_sem3 = await get_todays_classes(
                session=s,
                branch_id=branch_id,
                semester=3,
                section="1",
                batch=None,
                day=1,  # Tuesday
            )
            assert len(slots_sem3) > 0, "Expected Sem 3 Tuesday classes for AI section 1"

            # All returned slots must be strictly semester 3
            assert all(slot.semester == 3 for slot in slots_sem3)
            assert all(slot.branch_id == branch_id for slot in slots_sem3)

            # Check known 3rd sem subjects appear
            subject_names = [slot.subject.name for slot in slots_sem3 if slot.subject]
            assert any("Operating Systems" in name or "Algorithm" in name or "Network" in name for name in subject_names)

            # Verify that 5th semester query on same branch returns completely different slots
            slots_sem5 = await get_todays_classes(
                session=s,
                branch_id=branch_id,
                semester=5,
                section=None,
                batch=None,
                day=1,
            )
            sem3_ids = {slot.id for slot in slots_sem3}
            sem5_ids = {slot.id for slot in slots_sem5}
            assert sem3_ids.isdisjoint(sem5_ids), "Sem 3 and Sem 5 slots must be strictly isolated"

    @pytest.mark.asyncio
    async def test_air_and_aiml_sem3_branches_populated(self, sem3_ingestion):
        async with AsyncSessionLocal() as s:
            for branch_code in ["AIR", "AIDS", "AIML"]:
                b_res = await s.execute(select(Branch).where(Branch.code == branch_code))
                branch = b_res.scalars().first()
                assert branch is not None, f"Branch {branch_code} should exist"

                # Check slots exist for this branch in sem 3
                slot_res = await s.execute(
                    select(TimetableSlot).where(
                        TimetableSlot.branch_id == branch.id,
                        TimetableSlot.semester == 3,
                    )
                )
                branch_slots = slot_res.scalars().all()
                assert len(branch_slots) >= 15, f"Expected at least 15 slots for {branch_code} sem 3, got {len(branch_slots)}"


# ---------------------------------------------------------------------------
# Test 3: REST API Endpoint for 3rd Semester Student
# ---------------------------------------------------------------------------

class TestSem3RestApi:
    def test_student_gets_sem3_tuesday_classes_via_api(self, client, sem3_ai_student):
        token = sem3_ai_student["token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.get("/api/v1/timetable/day/1", headers=headers)
        assert resp.status_code == 200, resp.text
        classes = resp.json()
        assert len(classes) > 0, "Expected classes returned for Tuesday"

        # Check shape
        for c in classes:
            assert c["day_name"] == "Tuesday"
            assert "subject" in c
            assert "start_time" in c
            assert "room" in c
            assert isinstance(c["needs_review"], bool)

    def test_admin_review_queue_includes_flagged_sem3_slots(self, client, admin_token_fixture, sem3_ingestion):
        headers = {"Authorization": f"Bearer {admin_token_fixture}"}

        resp = client.get("/api/v1/admin/review-queue", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0
        sem3_flagged = [item for item in data["items"] if item["semester"] == 3]
        assert len(sem3_flagged) > 0, "Admin review queue should contain flagged 3rd semester slots"

