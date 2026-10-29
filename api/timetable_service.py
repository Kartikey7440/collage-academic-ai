"""Who may see which timetable rows.

This is the one place that applies the access rules. Both the REST endpoints
(api/routers/timetable.py) and the AI agent's tools (api/agent/tools.py) call
these functions, so the two can never disagree.

Rules
-----
- Students: only their own branch + semester (+ section/batch rules, which live
  in db/queries.slot_scope_conditions). Slots that are flagged ``needs_review``
  are still shown, marked as unconfirmed, because hiding a real class is worse
  than showing it with a "teacher to be confirmed" note. Set
  ``SHOW_UNCONFIRMED_TO_STUDENTS = False`` to hide them instead.
- Faculty: only the slots assigned to them.
- Admin: must name a branch and semester; sees every slot (including all batches).
"""

from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import ScopedIdentity
from db import queries
from db.models import TimetableSlot

SHOW_UNCONFIRMED_TO_STUDENTS = True


def resolve_student_scope(
    identity: ScopedIdentity,
) -> tuple[int, int, Optional[str], Optional[str]]:
    """Return (branch_id, semester, section, batch) or raise 403."""
    if identity.branch_id is None or identity.semester is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student profile is incomplete (missing branch or semester).",
        )
    return identity.branch_id, identity.semester, identity.section, identity.batch


def resolve_admin_scope(
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


def _faculty_id(identity: ScopedIdentity) -> int:
    if identity.faculty_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Faculty profile not found.",
        )
    return identity.faculty_id


async def classes(
    db: AsyncSession,
    identity: ScopedIdentity,
    day: Optional[int],
    *,
    branch_id: Optional[int] = None,
    semester: Optional[int] = None,
) -> list[TimetableSlot]:
    """The caller's classes on weekday ``day`` (0=Mon … 6=Sun); ``day=None`` = whole week.

    ``branch_id`` / ``semester`` are only honoured for admins.
    """
    if identity.is_faculty():
        return await queries.get_classes_by_faculty(db, _faculty_id(identity), day)

    if identity.is_student():
        b_id, sem, section, batch = resolve_student_scope(identity)
        slots = await queries.get_todays_classes(db, b_id, sem, section, batch, day)
        if not SHOW_UNCONFIRMED_TO_STUDENTS:
            slots = [s for s in slots if not s.needs_review]
        return slots

    b_id, sem = resolve_admin_scope(branch_id, semester)
    return await queries.get_todays_classes(
        db, b_id, sem, None, None, day, unrestricted=True
    )


async def next_class(
    db: AsyncSession,
    identity: ScopedIdentity,
    now: datetime,
    *,
    branch_id: Optional[int] = None,
    semester: Optional[int] = None,
) -> Optional[TimetableSlot]:
    """The next class later TODAY, or None if none remain."""
    todays = await classes(
        db, identity, now.weekday(), branch_id=branch_id, semester=semester
    )
    later = [s for s in todays if s.start_time > now.time()]
    return later[0] if later else None


async def upcoming_class(
    db: AsyncSession,
    identity: ScopedIdentity,
    now: datetime,
    *,
    branch_id: Optional[int] = None,
    semester: Optional[int] = None,
) -> tuple[Optional[TimetableSlot], int]:
    """Next class today, otherwise the first class of the next day that has one.

    Returns (slot, days_ahead); days_ahead 0 = later today, 7 = same weekday next
    week. Uses a single database query for the whole week.
    """
    week = await classes(db, identity, None, branch_id=branch_id, semester=semester)
    by_day: dict[int, list[TimetableSlot]] = {}
    for slot in week:
        by_day.setdefault(slot.day_of_week, []).append(slot)

    today = now.weekday()
    for ahead in range(0, 8):
        candidates = by_day.get((today + ahead) % 7, [])
        if ahead == 0:
            candidates = [s for s in candidates if s.start_time > now.time()]
        if candidates:
            return candidates[0], ahead
    return None, 0


async def is_suppressed(
    db: AsyncSession,
    identity: ScopedIdentity,
    check_date: date,
    *,
    branch_id: Optional[int] = None,
    semester: Optional[int] = None,
) -> bool:
    """True if a holiday/event suppresses the timetable on ``check_date``."""
    if identity.is_student():
        b_id, sem, _, _ = resolve_student_scope(identity)
    elif identity.is_faculty():
        # Faculty teach across branches: only institution-wide events can apply.
        b_id, sem = branch_id or 0, semester or 0
    else:
        b_id, sem = resolve_admin_scope(branch_id, semester)
    return await queries.is_timetable_suppressed(db, b_id, sem, check_date)