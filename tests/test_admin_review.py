"""Admin review queue tests (/api/v1/admin/*).

Tests verify:
- No token gives 401 Unauthorized
- Student and faculty tokens give 403 Forbidden on all 3 admin endpoints
- GET /admin/review-queue lists only flagged slots (needs_review=True)
- Unknown faculty code in PATCH gives 422 and the slot is unchanged
- Valid PATCH replaces the faculty, clears needs_review flag, and the slot leaves queue
- After PATCH, student's GET /api/v1/timetable/day/{n} shows slot with needs_review=False and new faculty
- Other slots remain untouched
- Unknown slot id in PATCH gives 404 Not Found
"""

import sys
from datetime import date, time
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from api.main import app
from api.security import create_access_token, hash_password
from db.models import (
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
from db.session import AsyncSessionLocal

DAY_WED = 2  # Wednesday


async def _get_or_create(session, model, lookup: dict, **extra):
    stmt = select(model).filter_by(**lookup)
    result = await session.execute(stmt)
    obj = result.scalars().first()
    if obj is None:
        obj = model(**lookup, **extra)
        session.add(obj)
        await session.flush()
    return obj


@pytest_asyncio.fixture(scope="session")
async def ar_data():
    """Seed dedicated AR branch, faculty, flagged and clean slots, and users."""
    async with AsyncSessionLocal() as s:
        branch = await _get_or_create(s, Branch, {"code": "AR"}, name="Admin Review Branch")
        subj = await _get_or_create(
            s,
            Subject,
            {"code": "AR-SUBJ-1"},
            name="Admin Review Subject",
            branch_id=branch.id,
            semester=3,
            is_lab=True,
        )
        f1 = await _get_or_create(s, Faculty, {"code": "ARF1"}, name="AR Faculty 1")
        f2 = await _get_or_create(s, Faculty, {"code": "ARF2"}, name="AR Faculty 2")

        slots = {}
        for key, start_hr, flagged in [("flagged", 10, True), ("other_flagged", 14, True), ("clean", 9, False)]:
            slot = await _get_or_create(
                s,
                TimetableSlot,
                {
                    "branch_id": branch.id,
                    "semester": 3,
                    "day_of_week": DAY_WED,
                    "start_time": time(start_hr, 0),
                },
                subject_id=subj.id,
                end_time=time(start_hr + 1, 0),
                room=f"AR-{key.upper()}",
                academic_session="2024-25-ODD",
                effective_from=date(2024, 7, 1),
            )
            # Ensure reset on each test run
            slot.needs_review = flagged
            slot.room = f"AR-{key.upper()}"
            slot.raw_cell_text = f"AR-SUBJ-1 ({key}) RES"
            await s.execute(delete(TimetableSlotFaculty).where(TimetableSlotFaculty.slot_id == slot.id))
            if key != "other_flagged":
                s.add(TimetableSlotFaculty(slot_id=slot.id, faculty_id=f1.id))
            slots[key] = slot

        # Users
        student_user = await _get_or_create(
            s,
            User,
            {"email": "ar-student@test.local"},
            password_hash=hash_password("password1234"),
            role=UserRole.student,
        )
        await _get_or_create(
            s,
            Student,
            {"user_id": student_user.id},
            branch_id=branch.id,
            semester=3,
            roll_no="AR/001",
        )

        faculty_user = await _get_or_create(
            s,
            User,
            {"email": "ar-faculty@test.local"},
            password_hash=hash_password("password1234"),
            role=UserRole.faculty,
        )
        await _get_or_create(s, FacultyUser, {"user_id": faculty_user.id}, faculty_id=f2.id)

        admin_user = await _get_or_create(
            s,
            User,
            {"email": "ar-admin@test.local"},
            password_hash=hash_password("password1234"),
            role=UserRole.admin,
        )

        await s.commit()

        return {
            "flagged_slot_id": slots["flagged"].id,
            "other_flagged_id": slots["other_flagged"].id,
            "clean_slot_id": slots["clean"].id,
            "student_token": create_access_token(student_user.id, "student"),
            "faculty_token": create_access_token(faculty_user.id, "faculty"),
            "admin_token": create_access_token(admin_user.id, "admin"),
        }


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


ADMIN_ENDPOINTS = [
    ("GET", "/api/v1/admin/review-queue", None),
    ("GET", "/api/v1/admin/faculty", None),
    ("PATCH", "/api/v1/admin/slots/1", {"mark_reviewed": True}),
]


async def _get_slot_state(slot_id: int):
    async with AsyncSessionLocal() as s:
        slot = await s.get(TimetableSlot, slot_id)
        fac_res = await s.execute(
            select(Faculty.code)
            .join(TimetableSlotFaculty, TimetableSlotFaculty.faculty_id == Faculty.id)
            .where(TimetableSlotFaculty.slot_id == slot_id)
            .order_by(Faculty.code)
        )
        faculty_codes = list(fac_res.scalars().all())
        return {
            "room": slot.room,
            "needs_review": slot.needs_review,
            "subject_id": slot.subject_id,
            "start_time": slot.start_time,
            "batch": slot.batch,
            "faculty": faculty_codes,
        }


class TestAdminAccessControl:
    @pytest.mark.parametrize("method,url,body", ADMIN_ENDPOINTS)
    def test_no_token_returns_401(self, client, method, url, body):
        kwargs = {"json": body} if body else {}
        resp = client.request(method, url, **kwargs)
        assert resp.status_code == 401

    @pytest.mark.parametrize("role_key", ["student_token", "faculty_token"])
    @pytest.mark.parametrize("method,url,body", ADMIN_ENDPOINTS)
    def test_non_admin_returns_403(self, client, ar_data, role_key, method, url, body):
        token = ar_data[role_key]
        kwargs = {"headers": _auth_header(token)}
        if body:
            kwargs["json"] = body
        resp = client.request(method, url, **kwargs)
        assert resp.status_code == 403


class TestAdminReviewOperations:
    def test_review_queue_lists_only_flagged(self, client, ar_data):
        resp = client.get("/api/v1/admin/review-queue", headers=_auth_header(ar_data["admin_token"]))
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data and "items" in data
        assert data["total"] == len(data["items"])

        item_ids = {item["id"] for item in data["items"]}
        assert ar_data["flagged_slot_id"] in item_ids
        assert ar_data["other_flagged_id"] in item_ids
        assert ar_data["clean_slot_id"] not in item_ids
        assert all(item["needs_review"] is True for item in data["items"])

        flagged_item = next(i for i in data["items"] if i["id"] == ar_data["flagged_slot_id"])
        assert flagged_item["branch_code"] == "AR"
        assert flagged_item["day_name"] == "Wednesday"
        assert flagged_item["subject"]["code"] == "AR-SUBJ-1"
        assert flagged_item["faculty"] == [{"code": "ARF1", "name": "AR Faculty 1"}]
        assert flagged_item["raw_cell_text"] == "AR-SUBJ-1 (flagged) RES"

    def test_get_all_faculty(self, client, ar_data):
        resp = client.get("/api/v1/admin/faculty", headers=_auth_header(ar_data["admin_token"]))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        codes = {f["code"] for f in data}
        assert "ARF1" in codes
        assert "ARF2" in codes

    @pytest.mark.asyncio
    async def test_unknown_faculty_code_gives_422_and_slot_unchanged(self, client, ar_data):
        slot_id = ar_data["flagged_slot_id"]
        before_state = await _get_slot_state(slot_id)

        resp = client.patch(
            f"/api/v1/admin/slots/{slot_id}",
            headers=_auth_header(ar_data["admin_token"]),
            json={
                "faculty_codes": ["ARF2", "UNKNOWN_NONEXISTENT_CODE"],
                "room": "NEW_ROOM",
                "mark_reviewed": True,
            },
        )
        assert resp.status_code == 422
        assert "UNKNOWN_NONEXISTENT_CODE" in resp.json()["detail"]

        after_state = await _get_slot_state(slot_id)
        assert after_state == before_state

    def test_unknown_slot_id_gives_404(self, client, ar_data):
        resp = client.patch(
            "/api/v1/admin/slots/999999999",
            headers=_auth_header(ar_data["admin_token"]),
            json={"mark_reviewed": True},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_valid_patch_replaces_faculty_and_clears_flag(self, client, ar_data):
        slot_id = ar_data["flagged_slot_id"]
        other_before = await _get_slot_state(ar_data["other_flagged_id"])
        clean_before = await _get_slot_state(ar_data["clean_slot_id"])

        resp = client.patch(
            f"/api/v1/admin/slots/{slot_id}",
            headers=_auth_header(ar_data["admin_token"]),
            json={
                "faculty_codes": [" arf2 ", "ARF2"],  # duplicates and whitespace trimmed/uppercased
                "room": "   ",  # blank string = leave unchanged
                "mark_reviewed": True,
            },
        )
        assert resp.status_code == 200, resp.text
        updated = resp.json()
        assert updated["id"] == slot_id
        assert updated["needs_review"] is False
        assert updated["faculty"] == [{"code": "ARF2", "name": "AR Faculty 2"}]
        assert updated["room"] == "AR-FLAGGED"  # unchanged

        # Verify DB state
        slot_state = await _get_slot_state(slot_id)
        assert slot_state["needs_review"] is False
        assert slot_state["faculty"] == ["ARF2"]

        # Other slots are untouched
        assert await _get_slot_state(ar_data["other_flagged_id"]) == other_before
        assert await _get_slot_state(ar_data["clean_slot_id"]) == clean_before

        # Slot has left the review queue
        q_resp = client.get("/api/v1/admin/review-queue", headers=_auth_header(ar_data["admin_token"]))
        queue_ids = {item["id"] for item in q_resp.json()["items"]}
        assert slot_id not in queue_ids
        assert ar_data["other_flagged_id"] in queue_ids

    def test_student_sees_updated_slot_with_needs_review_false(self, client, ar_data):
        slot_id = ar_data["flagged_slot_id"]
        resp = client.get(f"/api/v1/timetable/day/{DAY_WED}", headers=_auth_header(ar_data["student_token"]))
        assert resp.status_code == 200
        slots = resp.json()
        target = next((s for s in slots if s["id"] == slot_id), None)
        assert target is not None
        assert target["needs_review"] is False
        faculty_codes = [f["code"] for f in target["faculty"]]
        assert faculty_codes == ["ARF2"]

