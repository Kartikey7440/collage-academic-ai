"""Test seed data — inserts deterministic fixtures for query tests.

Run directly:
    python -m db.seed

Or import `seed_database()` in pytest fixtures.
Calling seed_database() on an already-seeded database is idempotent
(uses get-or-create logic).
"""

import asyncio
import logging
import sys
from datetime import date, time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.models import (
    AcademicEvent,
    Branch,
    Document,
    Faculty,
    FacultyUser,
    ReviewStatus,
    Student,
    StudentSubjectEnrollment,
    Subject,
    TimetableSlot,
    TimetableSlotFaculty,
    User,
    UserRole,
)
from db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def _get_or_create(session: AsyncSession, model, **filters):
    """Generic helper: fetch row matching filters, or create it."""
    result = await session.execute(select(model).filter_by(**filters))
    obj = result.scalars().first()
    if obj is None:
        obj = model(**filters)
        session.add(obj)
        await session.flush()
    return obj


async def seed_database() -> dict:
    """Insert deterministic seed data. Returns a dict of created object IDs.

    Idempotent — can be called multiple times safely.
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():

            # ----------------------------------------------------------------
            # Branches
            # ----------------------------------------------------------------
            branch_ai = await _get_or_create(session, Branch, code="AI", name="Artificial Intelligence")
            branch_cs = await _get_or_create(session, Branch, code="CS", name="Computer Science")

            # ----------------------------------------------------------------
            # Subjects
            # ----------------------------------------------------------------
            subj_ml = await _get_or_create(
                session, Subject,
                code="31243101",
                name="Machine Learning",
                branch_id=branch_ai.id,
                semester=5,
                is_lab=False,
            )
            subj_cc = await _get_or_create(
                session, Subject,
                code="31243102",
                name="Cloud Computing & Virtualization",
                branch_id=branch_ai.id,
                semester=5,
                is_lab=False,
            )
            subj_ml_lab = await _get_or_create(
                session, Subject,
                code="31243108",
                name="Statistical Computing Lab",
                branch_id=branch_ai.id,
                semester=5,
                is_lab=True,
            )
            subj_ds = await _get_or_create(
                session, Subject,
                code="27243101",
                name="Data Structures",
                branch_id=branch_cs.id,
                semester=5,
                is_lab=False,
            )

            # ----------------------------------------------------------------
            # Faculty
            # ----------------------------------------------------------------
            fac_mc = await _get_or_create(session, Faculty, code="MC", name="Dr. Mausam Chouksey")
            fac_gh = await _get_or_create(session, Faculty, code="GH", name="Mrs. Geetika Hazra")
            fac_na = await _get_or_create(session, Faculty, code="NA", name="Dr. Neelam Arya")

            # ----------------------------------------------------------------
            # Users + Profiles
            # ----------------------------------------------------------------
            # Student 1: AI branch, sem 5
            user_s1 = await _get_or_create(
                session, User,
                email="student1@college.edu",
                password_hash="$2b$12$PLACEHOLDER_HASH_S1",
                role=UserRole.student,
            )
            student1 = await _get_or_create(
                session, Student,
                user_id=user_s1.id,
                branch_id=branch_ai.id,
                semester=5,
                section=None,
                batch=None,
                roll_no="AI2021001",
            )

            # Student 2: CS branch, sem 5 (used to verify cross-branch isolation)
            user_s2 = await _get_or_create(
                session, User,
                email="student2@college.edu",
                password_hash="$2b$12$PLACEHOLDER_HASH_S2",
                role=UserRole.student,
            )
            student2 = await _get_or_create(
                session, Student,
                user_id=user_s2.id,
                branch_id=branch_cs.id,
                semester=5,
                section=None,
                batch=None,
                roll_no="CS2021001",
            )

            # Faculty user (MC)
            user_mc = await _get_or_create(
                session, User,
                email="mc@college.edu",
                password_hash="$2b$12$PLACEHOLDER_HASH_MC",
                role=UserRole.faculty,
            )
            await _get_or_create(
                session, FacultyUser,
                user_id=user_mc.id,
                faculty_id=fac_mc.id,
            )

            # ----------------------------------------------------------------
            # Document record
            # ----------------------------------------------------------------
            doc = await _get_or_create(
                session, Document,
                filename="seed_timetable.pdf",
                doc_type="timetable",
                scope_branch="AI",
                scope_semester=5,
                review_status=ReviewStatus.approved,
            )

            # ----------------------------------------------------------------
            # Timetable slots (AI branch, sem 5)
            # ----------------------------------------------------------------
            # Slot 1: MON 10:00-11:00 ML (MC)
            slot_mon_ml = await _get_or_create(
                session, TimetableSlot,
                branch_id=branch_ai.id,
                semester=5,
                section=None,
                batch=None,
                subject_id=subj_ml.id,
                day_of_week=0,     # MON
                start_time=time(10, 0),
                end_time=time(11, 0),
                room="SH1",
                academic_session="2024-25-ODD",
                effective_from=date(2024, 7, 1),
                effective_to=None,
                source_document_id=doc.id,
                needs_review=False,
                raw_cell_text="31243101 MC SH1",
            )
            await _get_or_create(
                session, TimetableSlotFaculty,
                slot_id=slot_mon_ml.id,
                faculty_id=fac_mc.id,
            )

            # Slot 2: MON 11:00-12:00 CC (GH) — used to test "next class"
            slot_mon_cc = await _get_or_create(
                session, TimetableSlot,
                branch_id=branch_ai.id,
                semester=5,
                section=None,
                batch=None,
                subject_id=subj_cc.id,
                day_of_week=0,     # MON
                start_time=time(11, 0),
                end_time=time(12, 0),
                room="SH2",
                academic_session="2024-25-ODD",
                effective_from=date(2024, 7, 1),
                effective_to=None,
                source_document_id=doc.id,
                needs_review=False,
                raw_cell_text="31243102 GH SH2",
            )
            await _get_or_create(
                session, TimetableSlotFaculty,
                slot_id=slot_mon_cc.id,
                faculty_id=fac_gh.id,
            )

            # Slot 3: TUE 14:00-16:00 ML Lab (NA) — needs_review=True
            slot_tue_lab = await _get_or_create(
                session, TimetableSlot,
                branch_id=branch_ai.id,
                semester=5,
                section=None,
                batch=None,
                subject_id=subj_ml_lab.id,
                day_of_week=1,     # TUE
                start_time=time(14, 0),
                end_time=time(16, 0),
                room="M104",
                academic_session="2024-25-ODD",
                effective_from=date(2024, 7, 1),
                effective_to=None,
                source_document_id=doc.id,
                needs_review=True,
                raw_cell_text="31243108 Batch A+B (NA+RES) M104",
                review_reason="faculty code 'RES' not found in lookup table",
            )
            await _get_or_create(
                session, TimetableSlotFaculty,
                slot_id=slot_tue_lab.id,
                faculty_id=fac_na.id,
            )

            # Slot 4: CS branch slot (must NOT appear in AI queries)
            slot_cs_ds = await _get_or_create(
                session, TimetableSlot,
                branch_id=branch_cs.id,
                semester=5,
                section=None,
                batch=None,
                subject_id=subj_ds.id,
                day_of_week=0,     # MON
                start_time=time(10, 0),
                end_time=time(11, 0),
                room="LH3",
                academic_session="2024-25-ODD",
                effective_from=date(2024, 7, 1),
                effective_to=None,
                source_document_id=doc.id,
                needs_review=False,
                raw_cell_text="27243101 HSP LH3",
            )

            # ----------------------------------------------------------------
            # Enrollments
            # ----------------------------------------------------------------
            await _get_or_create(
                session, StudentSubjectEnrollment,
                student_id=student1.id,
                subject_id=subj_ml.id,
                academic_session="2024-25-ODD",
            )
            await _get_or_create(
                session, StudentSubjectEnrollment,
                student_id=student1.id,
                subject_id=subj_cc.id,
                academic_session="2024-25-ODD",
            )
            await _get_or_create(
                session, StudentSubjectEnrollment,
                student_id=student2.id,
                subject_id=subj_ds.id,
                academic_session="2024-25-ODD",
            )

            # ----------------------------------------------------------------
            # Academic events
            # ----------------------------------------------------------------
            # Holiday that suppresses timetable (institution-wide)
            holiday = await _get_or_create(
                session, AcademicEvent,
                branch_id=None,
                semester=None,
                event_type="holiday",
                title="Independence Day",
                start_date=date(2025, 8, 15),
                end_date=date(2025, 8, 15),
                suppresses_timetable=True,
            )

            # Non-suppressing event for AI branch
            exam = await _get_or_create(
                session, AcademicEvent,
                branch_id=branch_ai.id,
                semester=5,
                event_type="exam",
                title="Mid-Semester Exam",
                start_date=date(2024, 10, 1),
                end_date=date(2024, 10, 7),
                suppresses_timetable=False,
            )

        logger.info("Seed complete.")
        return {
            "branch_ai_id": branch_ai.id,
            "branch_cs_id": branch_cs.id,
            "student1_id": student1.id,
            "student2_id": student2.id,
            "fac_mc_id": fac_mc.id,
            "fac_gh_id": fac_gh.id,
            "fac_na_id": fac_na.id,
            "slot_mon_ml_id": slot_mon_ml.id,
            "slot_mon_cc_id": slot_mon_cc.id,
            "slot_tue_lab_id": slot_tue_lab.id,
            "slot_cs_ds_id": slot_cs_ds.id,
            "holiday_id": holiday.id,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ids = asyncio.run(seed_database())
    print("Seed data created:", ids)
