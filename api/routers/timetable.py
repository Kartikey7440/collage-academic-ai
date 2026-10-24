"""Timetable router — read-only schedule and calendar endpoints.

Endpoints
---------
GET /timetable/today          Today's classes (scoped by identity)
GET /timetable/next-class     Next upcoming class from now
GET /timetable/day/{day}      Classes for a specific weekday (0=MON … 5=SAT)
GET /timetable/suppressed     Is today's timetable suppressed by a holiday/event?
GET /events/upcoming          Upcoming academic events (next N, scoped)

Scoping rules
-------------
- Students: scope = branch_id + semester (+ section/batch if set).
  ``needs_review`` slots are **excluded** from student responses — a student
  should never silently see a slot whose faculty is unconfirmed.
- Faculty:  scope = faculty_id (uses get_classes_by_faculty / get_next_class_for_faculty).
  ``needs_review`` slots are included with the flag visible so faculty can
  flag discrepancies to admin.
- Admin:    must pass explicit query params (branch_id, semester).
  All slots returned, ``needs_review`` flag always visible.

Timezone
--------
All "now" calculations use ``api.config.now_college()`` which reads the
``COLLEGE_TIMEZONE`` env var (default: Asia/Kolkata).  Never call
``datetime.now()`` directly here.

Day convention
--------------
0 = Monday … 6 = Sunday, matching Python's ``datetime.weekday()``.
The ``day_name`` field in every slot response carries the human-readable
name so clients never need to guess.

All endpoints require a valid Bearer access token.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import DAY_INT_TO_NAME, now_college
from api.deps import ScopedIdentity, get_current_identity, get_db
from api.schemas import AcademicEventOut, SuppressedResponse, TimetableSlotOut
from db import queries
from db.models import TimetableSlot

router = APIRouter(tags=["timetable"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _serialize_slot(slot: TimetableSlot) -> TimetableSlotOut:
    """Convert a TimetableSlot ORM object into its API schema.

    Eagerly-loaded relationships (subject, faculty_assignments) are expected
    to already be present on the object.
    """
    faculty_list = [
        {"id": tsf.faculty.id, "code": tsf.faculty.code, "name": tsf.faculty.name}
        for tsf in (slot.faculty_assignments or [])
        if tsf.faculty is not None
    ]
    return TimetableSlotOut(
        id=slot.id,
        day_of_week=slot.day_of_week,
        day_name=DAY_INT_TO_NAME.get(slot.day_of_week, "Unknown"),
        start_time=slot.start_time,
        end_time=slot.end_time,
        room=slot.room,
        section=slot.section,
        batch=slot.batch,
        needs_review=slot.needs_review,
        subject={
            "id": slot.subject.id,
            "code": slot.subject.code,
            "name": slot.subject.name,
            "is_lab": slot.subject.is_lab,
        },
        faculty=faculty_list,
    )


def _filter_for_students(slots: list[TimetableSlot]) -> list[TimetableSlot]:
    """Exclude needs_review=True rows from student-facing responses.

    Rationale: a needs_review slot may have an unconfirmed subject code,
    missing/wrong faculty, or a generic elective placeholder (e.g. 'DE-1').
    Showing it silently to students defeats the admin review step.
    """
    return [s for s in slots if not s.needs_review]


def _resolve_student_scope(
    identity: ScopedIdentity,
) -> tuple[int, int, Optional[str], Optional[str]]:
    """Extract (branch_id, semester, section, batch) or raise 403."""
    if identity.branch_id is None or identity.semester is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student profile is incomplete (missing branch or semester).",
        )
    return identity.branch_id, identity.semester, identity.section, identity.batch


def _resolve_admin_scope(
    branch_id: Optional[int],
    semester: Optional[int],
) -> tuple[int, int]:
    """Admins must supply branch_id and semester explicitly."""
    if branch_id is None or semester is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Admins must supply both 'branch_id' and 'semester' query parameters.",
        )
    return branch_id, semester


# ---------------------------------------------------------------------------
# GET /timetable/today
# ---------------------------------------------------------------------------


@router.get(
    "/timetable/today",
    response_model=List[TimetableSlotOut],
    summary="Get today's classes for the authenticated user",
)
async def get_today(
    branch_id: Optional[int] = Query(None, description="Admin only: target branch ID"),
    semester: Optional[int] = Query(None, description="Admin only: target semester", ge=1, le=8),
    identity: ScopedIdentity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> List[TimetableSlotOut]:
    """Return all timetable slots for today, ordered by start_time.

    - **Students**: auto-scoped; ``needs_review`` slots are excluded.
    - **Faculty**: see their own assigned slots (``needs_review`` flag visible).
    - **Admins**: must provide ``branch_id`` and ``semester``; all slots returned.

    'Today' is determined in the college's local timezone (``COLLEGE_TIMEZONE``).
    """
    today_int = now_college().weekday()  # 0=MON … 6=SUN  (college local time)

    if identity.is_faculty():
        if identity.faculty_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Faculty profile not found.",
            )
        slots = await queries.get_classes_by_faculty(db, identity.faculty_id, today_int)
        return [_serialize_slot(s) for s in slots]

    elif identity.is_student():
        b_id, sem, section, batch = _resolve_student_scope(identity)
        slots = await queries.get_todays_classes(db, b_id, sem, section, batch, today_int)
        return [_serialize_slot(s) for s in _filter_for_students(slots)]

    else:  # admin
        b_id, sem = _resolve_admin_scope(branch_id, semester)
        slots = await queries.get_todays_classes(db, b_id, sem, None, None, today_int)
        return [_serialize_slot(s) for s in slots]


# ---------------------------------------------------------------------------
# GET /timetable/next-class
# ---------------------------------------------------------------------------


@router.get(
    "/timetable/next-class",
    response_model=Optional[TimetableSlotOut],
    summary="Get the next upcoming class from now",
)
async def get_next_class(
    branch_id: Optional[int] = Query(None, description="Admin only: target branch ID"),
    semester: Optional[int] = Query(None, description="Admin only: target semester", ge=1, le=8),
    identity: ScopedIdentity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> Optional[TimetableSlotOut]:
    """Return the next upcoming class for the rest of today, or ``null`` if none remain.

    'Now' is determined in the college's local timezone (``COLLEGE_TIMEZONE``).

    - **Students**: next confirmed (non-review) slot for their branch/semester.
    - **Faculty**: next slot across all their assigned classes today.
    - **Admins**: must supply ``branch_id`` and ``semester``.
    """
    now = now_college()  # college local time

    if identity.is_faculty():
        if identity.faculty_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Faculty profile not found.",
            )
        slot = await queries.get_next_class_for_faculty(db, identity.faculty_id, now)
        return _serialize_slot(slot) if slot else None

    elif identity.is_student():
        b_id, sem, section, batch = _resolve_student_scope(identity)
        # get_next_class returns one row; filter needs_review before returning.
        slot = await queries.get_next_class(db, b_id, sem, section, batch, now)
        if slot is None or slot.needs_review:
            return None
        return _serialize_slot(slot)

    else:  # admin
        b_id, sem = _resolve_admin_scope(branch_id, semester)
        slot = await queries.get_next_class(db, b_id, sem, None, None, now)
        return _serialize_slot(slot) if slot else None


# ---------------------------------------------------------------------------
# GET /timetable/day/{day}
# ---------------------------------------------------------------------------


@router.get(
    "/timetable/day/{day}",
    response_model=List[TimetableSlotOut],
    summary="Get classes for a specific weekday (0=Monday … 6=Sunday)",
)
async def get_day(
    day: int,
    branch_id: Optional[int] = Query(None, description="Admin only: target branch ID"),
    semester: Optional[int] = Query(None, description="Admin only: target semester", ge=1, le=8),
    identity: ScopedIdentity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> List[TimetableSlotOut]:
    """Return all classes for a given weekday.

    ``day`` is a 0-based integer: **0=Monday … 5=Saturday … 6=Sunday**.
    The ``day_name`` field in each slot echoes the human-readable name
    so clients never need to maintain their own mapping.

    ``needs_review`` filtering follows the same rules as ``/timetable/today``.
    """
    if day < 0 or day > 6:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'day' must be between 0 (Monday) and 6 (Sunday).",
        )

    if identity.is_faculty():
        if identity.faculty_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Faculty profile not found.",
            )
        slots = await queries.get_classes_by_faculty(db, identity.faculty_id, day)
        return [_serialize_slot(s) for s in slots]

    elif identity.is_student():
        b_id, sem, section, batch = _resolve_student_scope(identity)
        slots = await queries.get_todays_classes(db, b_id, sem, section, batch, day)
        return [_serialize_slot(s) for s in _filter_for_students(slots)]

    else:  # admin
        b_id, sem = _resolve_admin_scope(branch_id, semester)
        slots = await queries.get_todays_classes(db, b_id, sem, None, None, day)
        return [_serialize_slot(s) for s in slots]


# ---------------------------------------------------------------------------
# GET /timetable/suppressed
# ---------------------------------------------------------------------------


@router.get(
    "/timetable/suppressed",
    response_model=SuppressedResponse,
    summary="Check if the timetable is suppressed for a given date",
)
async def check_suppressed(
    check_date: Optional[date] = Query(
        None,
        description="Date to check (ISO 8601, e.g. 2024-11-01). Defaults to today in college timezone.",
    ),
    branch_id: Optional[int] = Query(None, description="Admin only: target branch ID"),
    semester: Optional[int] = Query(None, description="Admin only: target semester", ge=1, le=8),
    identity: ScopedIdentity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> SuppressedResponse:
    """Return whether a holiday/event suppresses the timetable for the given date.

    'Today' (when ``check_date`` is omitted) is determined in the college's
    local timezone so a request at 23:00 UTC on a Friday is correctly treated
    as Saturday morning IST.
    """
    target_date = check_date or now_college().date()

    if identity.is_student():
        b_id, sem, _, _ = _resolve_student_scope(identity)
    elif identity.is_faculty():
        # Faculty have no single branch scope; perform an institution-wide check
        # using branch_id=0 (guaranteed to never match a real branch) so that
        # only the branch_id IS NULL (institution-wide) path fires in queries.py.
        b_id = branch_id or 0
        sem = semester or 0
    else:  # admin
        b_id, sem = _resolve_admin_scope(branch_id, semester)

    suppressed = await queries.is_timetable_suppressed(db, b_id, sem, target_date)
    return SuppressedResponse(
        suppressed=suppressed,
        check_date=target_date,
        branch_id=b_id if not identity.is_faculty() else None,
        semester=sem if not identity.is_faculty() else None,
    )


# ---------------------------------------------------------------------------
# GET /events/upcoming
# ---------------------------------------------------------------------------


@router.get(
    "/events/upcoming",
    response_model=List[AcademicEventOut],
    summary="Get upcoming academic events",
)
async def get_upcoming_events(
    from_date: Optional[date] = Query(
        None,
        description="Start date (ISO 8601). Defaults to today in college timezone.",
    ),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of events to return"),
    branch_id: Optional[int] = Query(None, description="Admin only: target branch ID"),
    semester: Optional[int] = Query(None, description="Admin only: target semester", ge=1, le=8),
    identity: ScopedIdentity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> List[AcademicEventOut]:
    """Return upcoming academic events on or after ``from_date``.

    Includes both institution-wide events (``branch_id IS NULL``) and
    branch/semester-specific events within the caller's scope.
    """
    start = from_date or now_college().date()

    if identity.is_student():
        b_id, sem, _, _ = _resolve_student_scope(identity)
    elif identity.is_faculty():
        b_id = branch_id
        sem = semester
    else:  # admin — optional scope; None returns institution-wide only
        b_id = branch_id
        sem = semester

    events = await queries.get_upcoming_events(db, b_id, sem, start, limit=limit)
    return [AcademicEventOut.model_validate(e) for e in events]
