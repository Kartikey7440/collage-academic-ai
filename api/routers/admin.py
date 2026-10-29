"""Admin review queue router for flagged timetable rows.

Prefix: /admin (mounted under /api/v1)
All endpoints require the 'admin' role.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.config import DAY_INT_TO_NAME
from api.deps import ScopedIdentity, get_db, require_role
from db.models import Branch, Faculty, TimetableSlot, TimetableSlotFaculty

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

_admin = require_role("admin")


class SlotPatchRequest(BaseModel):
    faculty_codes: Optional[List[str]] = None
    room: Optional[str] = None
    mark_reviewed: bool = False


def _slot_eager_query():
    return select(TimetableSlot).options(
        selectinload(TimetableSlot.branch),
        selectinload(TimetableSlot.subject),
        selectinload(TimetableSlot.faculty_assignments).selectinload(
            TimetableSlotFaculty.faculty
        ),
    )


def _serialize_slot_item(slot: TimetableSlot) -> dict:
    return {
        "id": slot.id,
        "branch_code": slot.branch.code if slot.branch else None,
        "semester": slot.semester,
        "day_name": DAY_INT_TO_NAME.get(slot.day_of_week, "Unknown"),
        "start_time": slot.start_time.strftime("%H:%M") if slot.start_time else None,
        "end_time": slot.end_time.strftime("%H:%M") if slot.end_time else None,
        "batch": slot.batch,
        "room": slot.room,
        "needs_review": slot.needs_review,
        "subject": {
            "code": slot.subject.code,
            "name": slot.subject.name,
        }
        if slot.subject
        else None,
        "faculty": [
            {"code": a.faculty.code, "name": a.faculty.name}
            for a in (slot.faculty_assignments or [])
            if a.faculty is not None
        ],
        "raw_cell_text": slot.raw_cell_text,
    }


async def _get_slot_by_id(db: AsyncSession, slot_id: int) -> Optional[TimetableSlot]:
    stmt = _slot_eager_query().where(TimetableSlot.id == slot_id)
    result = await db.execute(stmt)
    return result.scalars().first()


@router.get("/review-queue", summary="List timetable slots needing review")
async def get_review_queue(
    _: ScopedIdentity = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        _slot_eager_query()
        .join(Branch, TimetableSlot.branch_id == Branch.id)
        .where(TimetableSlot.needs_review.is_(True))
        .order_by(Branch.code, TimetableSlot.day_of_week, TimetableSlot.start_time)
    )
    result = await db.execute(stmt)
    slots = result.scalars().all()
    items = [_serialize_slot_item(s) for s in slots]
    return {
        "total": len(items),
        "items": items,
    }


@router.get("/faculty", summary="List all faculty code and name pairs")
async def get_all_faculty(
    _: ScopedIdentity = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Faculty).order_by(Faculty.code)
    result = await db.execute(stmt)
    faculty_rows = result.scalars().all()
    return [{"code": f.code, "name": f.name} for f in faculty_rows]


@router.patch("/slots/{slot_id}", summary="Update and optionally confirm a slot")
async def patch_slot(
    slot_id: int,
    body: SlotPatchRequest,
    identity: ScopedIdentity = Depends(_admin),
    db: AsyncSession = Depends(get_db),
):
    slot = await _get_slot_by_id(db, slot_id)
    if slot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Slot with id {slot_id} not found.",
        )

    changed_fields: list[str] = []

    # If faculty_codes is provided, validate every code first before changing anything
    new_faculty_rows: Optional[list[Faculty]] = None
    if body.faculty_codes is not None:
        normalized_codes: list[str] = []
        for raw in body.faculty_codes:
            code = (raw or "").strip().upper()
            if code and code not in normalized_codes:
                normalized_codes.append(code)

        if normalized_codes:
            stmt = select(Faculty).where(Faculty.code.in_(normalized_codes))
            res = await db.execute(stmt)
            found_faculty = res.scalars().all()
            by_code = {f.code: f for f in found_faculty}
            unknown = [c for c in normalized_codes if c not in by_code]
            if unknown:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Unknown faculty code(s): {', '.join(unknown)}",
                )
            new_faculty_rows = [by_code[c] for c in normalized_codes]
        else:
            new_faculty_rows = []

    # Apply faculty changes
    if new_faculty_rows is not None:
        await db.execute(
            delete(TimetableSlotFaculty).where(TimetableSlotFaculty.slot_id == slot.id)
        )
        for f in new_faculty_rows:
            db.add(TimetableSlotFaculty(slot_id=slot.id, faculty_id=f.id))
        changed_fields.append("faculty_codes")

    # Apply room changes (blank string or None means leave unchanged)
    if body.room is not None:
        trimmed_room = body.room.strip()
        if trimmed_room:
            slot.room = trimmed_room
            changed_fields.append("room")

    # Apply mark_reviewed
    if body.mark_reviewed:
        slot.needs_review = False
        changed_fields.append("mark_reviewed")

    await db.commit()
    db.expire_all()
    updated_slot = await _get_slot_by_id(db, slot_id)

    logger.info(
        "admin_slot_update admin_user_id=%s slot_id=%s changed=%s",
        identity.user_id,
        slot_id,
        ",".join(changed_fields) or "none",
    )
    return _serialize_slot_item(updated_slot)

