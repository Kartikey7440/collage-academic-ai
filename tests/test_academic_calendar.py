"""Tests for Academic Calendar extraction, database queries, REST API, and AI Agent tool.

Verifies:
1. JSON schema and integrity of college data/academic_calendar.json.
2. Database loader and queries (get_upcoming_events, is_timetable_suppressed).
3. REST API endpoint GET /api/v1/events/upcoming with ScopedIdentity.
4. AI Agent get_academic_calendar tool (upcoming events, keyword search, regulation chunks).
"""

import json
from datetime import date, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import select

from api.agent.tools import format_result, query_academic_calendar, run_tool
from api.deps import ScopedIdentity
from api.main import app
from api.security import create_access_token, hash_password
from db.models import AcademicEvent, Branch, Student, User, UserRole
from db.queries import get_upcoming_events, is_timetable_suppressed
from db.session import AsyncSessionLocal

CALENDAR_JSON_PATH = Path(__file__).resolve().parents[1] / "college data" / "academic_calendar.json"


# ---------------------------------------------------------------------------
# Test 1: JSON Schema & Integrity
# ---------------------------------------------------------------------------

class TestCalendarDataIntegrity:
    def test_calendar_json_structure(self):
        assert CALENDAR_JSON_PATH.exists(), f"File {CALENDAR_JSON_PATH} not found"
        with open(CALENDAR_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data["academic_year"] == "2026-2027"
        assert len(data["events"]) >= 40
        assert len(data["instructions"]) >= 10

        valid_types = {
            "registration", "instruction", "exam", "attendance",
            "break", "holiday", "evaluation", "internship", "result", "academic"
        }

        for ev in data["events"]:
            assert "title" in ev and ev["title"]
            assert ev["event_type"] in valid_types
            assert "start_date" in ev and "end_date" in ev
            assert ev["start_date"] <= ev["end_date"]
            assert "academic_session" in ev
            assert isinstance(ev["suppresses_timetable"], bool)


# ---------------------------------------------------------------------------
# Test 2: Database Queries
# ---------------------------------------------------------------------------

class TestCalendarDatabaseQueries:
    @pytest.mark.asyncio
    async def test_get_upcoming_events_and_timetable_suppression(self, init_test_database):
        async with AsyncSessionLocal() as session:
            # 1. Fetch upcoming events starting July 2026
            events = await get_upcoming_events(
                session,
                branch_id=None,
                semester=3,
                from_date=date(2026, 7, 1),
                limit=20,
            )
            assert len(events) >= 10
            titles = [e.title for e in events]
            assert any("Semester Break" in t for t in titles)

            # 2. Verify timetable suppression during Odd Semester Break (10th to 13th Nov 2026)
            is_suppressed = await is_timetable_suppressed(
                session,
                branch_id=1,
                semester=3,
                check_date=date(2026, 11, 11),
            )
            assert is_suppressed is True, "Classes should be suppressed during Odd Semester Break"

            # 3. Verify normal instructional day is NOT suppressed
            not_suppressed = await is_timetable_suppressed(
                session,
                branch_id=1,
                semester=3,
                check_date=date(2026, 9, 1),
            )
            assert not_suppressed is False, "Classes should NOT be suppressed on normal working day"


# ---------------------------------------------------------------------------
# Test 3: REST API Endpoint (GET /api/v1/events/upcoming)
# ---------------------------------------------------------------------------

class TestCalendarRestApi:
    @pytest_asyncio.fixture
    async def student_auth(self, init_test_database):
        async with AsyncSessionLocal() as s:
            branch_res = await s.execute(select(Branch).where(Branch.code == "AI"))
            ai_branch = branch_res.scalars().first()

            user_res = await s.execute(select(User).where(User.email == "cal_student@test.local"))
            user = user_res.scalars().first()
            if user is None:
                user = User(
                    email="cal_student@test.local",
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
                    roll_no="CAL2026001",
                )
                s.add(student)
                await s.commit()
                await s.refresh(user)

        token = create_access_token(user.id, "student")
        return {"headers": {"Authorization": f"Bearer {token}"}}

    def test_unauthorized_events_endpoint_returns_401(self):
        client = TestClient(app)
        res = client.get("/api/v1/events/upcoming")
        assert res.status_code == 401

    def test_student_gets_upcoming_events(self, student_auth):
        client = TestClient(app)
        res = client.get(
            "/api/v1/events/upcoming?from_date=2026-07-01&limit=15",
            headers=student_auth["headers"],
        )
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) > 0
        first_event = data[0]
        assert "title" in first_event
        assert "start_date" in first_event
        assert "end_date" in first_event


# ---------------------------------------------------------------------------
# Test 4: AI Agent Calendar Tool
# ---------------------------------------------------------------------------

class TestCalendarAgentTool:
    @pytest.mark.asyncio
    async def test_agent_tool_upcoming_events(self, init_test_database):
        identity = ScopedIdentity(user_id=1, role="student", branch_id=1, semester=3)
        mock_now = datetime(2026, 8, 1, 10, 0)

        async with AsyncSessionLocal() as db:
            result = await run_tool(
                "get_academic_calendar",
                {"query_type": "upcoming"},
                db=db,
                identity=identity,
                now=mock_now,
            )

        assert "events" in result
        assert len(result["events"]) > 0
        plain_text = format_result(result)
        assert "Upcoming Academic Events:" in plain_text

    @pytest.mark.asyncio
    async def test_agent_tool_keyword_search_and_regulations(self, init_test_database):
        identity = ScopedIdentity(user_id=1, role="student", branch_id=1, semester=3)
        mock_now = datetime(2026, 8, 1, 10, 0)

        async with AsyncSessionLocal() as db:
            # 1. Search for break
            break_res = await run_tool(
                "get_academic_calendar",
                {"query_type": "search", "search_term": "break"},
                db=db,
                identity=identity,
                now=mock_now,
            )
            assert "matched_events" in break_res
            assert any("Semester Break" in e["title"] for e in break_res["matched_events"])

            # 2. Search for attendance regulations
            att_res = await run_tool(
                "get_academic_calendar",
                {"query_type": "search", "search_term": "attendance"},
                db=db,
                identity=identity,
                now=mock_now,
            )
            assert len(att_res.get("relevant_guidelines", [])) > 0
            guidelines = " ".join(att_res["relevant_guidelines"])
            assert "AMS" in guidelines or "attendance" in guidelines.lower()

