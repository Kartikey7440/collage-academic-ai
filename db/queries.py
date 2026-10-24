"""Scoped read-only query functions for the AI agent layer (Phase 3).

Design rules
------------
- Every function takes **explicit scope parameters** (branch_id, semester, etc.).
- All filtering happens in the SQL WHERE clause — never a broad fetch
  followed by Python-side filtering.
- Functions return ORM objects or lightweight dicts; callers decide
  how to serialise them.
- All functions are async and expect an active AsyncSession.
"""

from datetime import date, datetime, time
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.config import DAY_CODE_TO_INT
from db.models import (
    AcademicEvent,
    Branch,
    Faculty,
    Subject,
    TimetableSlot,
    TimetableSlotFaculty,
)


# ---------------------------------------------------------------------------
# Day-of-week helpers
# ---------------------------------------------------------------------------

# Day convention: 0=Monday … 6=Sunday (matches Python's datetime.weekday()).
# The canonical mapping lives in api/config.DAY_CODE_TO_INT; it is also
# re-exported here for code that imports from db.queries directly.
_DAY_MAP = DAY_CODE_TO_INT


def day_code_to_int(day: str) -> int:
    """Convert 3-letter day code (e.g. 'MON') to 0-based integer (0=Mon … 6=Sun)."""
    return _DAY_MAP[day.upper()]


def today_day_int() -> int:
    """Return today's day-of-week as a 0-based int (0=MON … 6=SUN) in college timezone."""
    from api.config import now_college
    return now_college().weekday()


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

async def get_todays_classes(
    session: AsyncSession,
    branch_id: int,
    semester: int,
    section: Optional[str],
    batch: Optional[str],
    day: int,
) -> list[TimetableSlot]:
    """Return all timetable slots for the given branch/semester/section/batch on `day`.

    `day` is a 0-based weekday integer (0=MON … 6=SUN).
    Results are ordered by start_time ascending.
    Section and batch filters are applied strictly: a None value means
    the query matches rows where section/batch IS NULL (whole-class slots).
    """
    stmt = (
        select(TimetableSlot)
        .where(
            and_(
                TimetableSlot.branch_id == branch_id,
                TimetableSlot.semester == semester,
                TimetableSlot.day_of_week == day,
                (
                    TimetableSlot.section == section
                    if section is not None
                    else TimetableSlot.section.is_(None)
                ),
                (
                    TimetableSlot.batch == batch
                    if batch is not None
                    else TimetableSlot.batch.is_(None)
                ),
            )
        )
        .options(
            selectinload(TimetableSlot.subject),
            selectinload(TimetableSlot.faculty_assignments).selectinload(
                TimetableSlotFaculty.faculty
            ),
        )
        .order_by(TimetableSlot.start_time)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_next_class(
    session: AsyncSession,
    branch_id: int,
    semester: int,
    section: Optional[str],
    batch: Optional[str],
    now: datetime,
) -> Optional[TimetableSlot]:
    """Return the next upcoming class slot after `now` on the same day.

    Returns None if no slots remain for the rest of today.
    """
    current_time: time = now.time()
    current_day: int = now.weekday()  # 0=MON

    stmt = (
        select(TimetableSlot)
        .where(
            and_(
                TimetableSlot.branch_id == branch_id,
                TimetableSlot.semester == semester,
                TimetableSlot.day_of_week == current_day,
                TimetableSlot.start_time > current_time,
                (
                    TimetableSlot.section == section
                    if section is not None
                    else TimetableSlot.section.is_(None)
                ),
                (
                    TimetableSlot.batch == batch
                    if batch is not None
                    else TimetableSlot.batch.is_(None)
                ),
            )
        )
        .options(
            selectinload(TimetableSlot.subject),
            selectinload(TimetableSlot.faculty_assignments).selectinload(
                TimetableSlotFaculty.faculty
            ),
        )
        .order_by(TimetableSlot.start_time)
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def get_upcoming_events(
    session: AsyncSession,
    branch_id: Optional[int],
    semester: Optional[int],
    from_date: date,
    limit: int = 10,
) -> list[AcademicEvent]:
    """Return upcoming academic events on or after `from_date`.

    Scope logic:
    - Events with branch_id IS NULL apply to everyone (institution-wide).
    - Events with a specific branch_id apply only to that branch.
    - Same logic for semester.
    So we return events that either match the scope or are institution-wide.
    """
    branch_filter = or_(
        AcademicEvent.branch_id.is_(None),
        AcademicEvent.branch_id == branch_id,
    ) if branch_id is not None else AcademicEvent.branch_id.is_(None)

    semester_filter = or_(
        AcademicEvent.semester.is_(None),
        AcademicEvent.semester == semester,
    ) if semester is not None else AcademicEvent.semester.is_(None)

    stmt = (
        select(AcademicEvent)
        .where(
            and_(
                AcademicEvent.end_date >= from_date,
                branch_filter,
                semester_filter,
            )
        )
        .order_by(AcademicEvent.start_date)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def is_timetable_suppressed(
    session: AsyncSession,
    branch_id: int,
    semester: int,
    check_date: date,
) -> bool:
    """Return True if a suppressing academic event covers `check_date` for this scope.

    A suppressing event (suppresses_timetable=True) that:
    - applies institution-wide (branch_id IS NULL) OR matches branch_id, AND
    - applies to all semesters (semester IS NULL) OR matches semester, AND
    - has a date range that includes check_date
    ... means timetable classes do not run that day.
    """
    stmt = (
        select(AcademicEvent.id)
        .where(
            and_(
                AcademicEvent.suppresses_timetable.is_(True),
                AcademicEvent.start_date <= check_date,
                AcademicEvent.end_date >= check_date,
                or_(
                    AcademicEvent.branch_id.is_(None),
                    AcademicEvent.branch_id == branch_id,
                ),
                or_(
                    AcademicEvent.semester.is_(None),
                    AcademicEvent.semester == semester,
                ),
            )
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.first() is not None


async def get_classes_by_faculty(
    session: AsyncSession,
    faculty_id: int,
    day: int,
) -> list[TimetableSlot]:
    """Return all slots assigned to a specific faculty member on a given day.

    `day` is a 0-based weekday integer (0=MON … 6=SUN).
    Results ordered by start_time.

    Note: slots with ``needs_review=True`` are included deliberately —
    the faculty member should still see classes that are pending admin review.
    """
    stmt = (
        select(TimetableSlot)
        .join(
            TimetableSlotFaculty,
            TimetableSlotFaculty.slot_id == TimetableSlot.id,
        )
        .where(
            and_(
                TimetableSlotFaculty.faculty_id == faculty_id,
                TimetableSlot.day_of_week == day,
            )
        )
        .options(
            selectinload(TimetableSlot.subject),
            selectinload(TimetableSlot.branch),
            selectinload(TimetableSlot.faculty_assignments).selectinload(
                TimetableSlotFaculty.faculty
            ),
        )
        .order_by(TimetableSlot.start_time)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_next_class_for_faculty(
    session: AsyncSession,
    faculty_id: int,
    now: datetime,
) -> Optional[TimetableSlot]:
    """Return the next upcoming slot for a faculty member after `now` today.

    Returns None if no slots remain for the rest of today.
    A faculty member may teach across multiple branches/semesters, so this
    searches all their assigned slots and picks the earliest one after `now`.
    """
    current_time: time = now.time()
    current_day: int = now.weekday()

    stmt = (
        select(TimetableSlot)
        .join(
            TimetableSlotFaculty,
            TimetableSlotFaculty.slot_id == TimetableSlot.id,
        )
        .where(
            and_(
                TimetableSlotFaculty.faculty_id == faculty_id,
                TimetableSlot.day_of_week == current_day,
                TimetableSlot.start_time > current_time,
            )
        )
        .options(
            selectinload(TimetableSlot.subject),
            selectinload(TimetableSlot.branch),
            selectinload(TimetableSlot.faculty_assignments).selectinload(
                TimetableSlotFaculty.faculty
            ),
        )
        .order_by(TimetableSlot.start_time)
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()
