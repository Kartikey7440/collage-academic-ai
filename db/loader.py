"""Phase 1 JSON → Postgres loader.

Reads a Phase 1 pipeline output JSON file and upserts all timetable entries
into the database. Fully idempotent — safe to re-run without creating
duplicate rows.

Usage
-----
    python -m db.loader --json out.json --session 2024-25-ODD

    # With a specific document source name:
    python -m db.loader --json out.json --session 2024-25-ODD --doc sample_timetable.pdf
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure project root is in path when running as __main__
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.session import AsyncSessionLocal
from db.models import (
    Branch,
    Document,
    Faculty,
    ReviewStatus,
    Subject,
    TimetableSlot,
    TimetableSlotFaculty,
)

logger = logging.getLogger(__name__)

# Day abbreviation → 0-based int (matching ISO weekday - 1)
_DAY_TO_INT: dict[str, int] = {
    "MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6,
}


# ---------------------------------------------------------------------------
# Helpers: upsert-or-get reference rows
# ---------------------------------------------------------------------------

async def _get_or_create_branch(session: AsyncSession, code: str) -> Branch:
    """Return an existing branch by code, or create it with a placeholder name."""
    result = await session.execute(select(Branch).where(Branch.code == code))
    branch = result.scalars().first()
    if branch is None:
        branch = Branch(code=code, name=code)
        session.add(branch)
        await session.flush()  # Assign PK without committing
        logger.info("Created branch: %s", code)
    return branch


async def _get_or_create_faculty(session: AsyncSession, code: str, name: Optional[str]) -> Faculty:
    """Return an existing faculty by code, or create it."""
    result = await session.execute(select(Faculty).where(Faculty.code == code))
    faculty = result.scalars().first()
    if faculty is None:
        faculty = Faculty(code=code, name=name or code)
        session.add(faculty)
        await session.flush()
        logger.info("Created faculty: %s (%s)", code, name)
    return faculty


async def _get_or_create_subject(
    session: AsyncSession,
    code: str,
    name: Optional[str],
    branch_id: Optional[int],
    semester: Optional[int],
    is_lab: bool = False,
) -> Subject:
    """Return an existing subject by code, or create it."""
    result = await session.execute(select(Subject).where(Subject.code == code))
    subject = result.scalars().first()
    if subject is None:
        subject = Subject(
            code=code,
            name=name or code,
            branch_id=branch_id,
            semester=semester,
            is_lab=is_lab,
        )
        session.add(subject)
        await session.flush()
        logger.info("Created subject: %s (%s)", code, name)
    return subject


async def _get_or_create_document(
    session: AsyncSession,
    filename: str,
    scope_branch: Optional[str],
    scope_semester: Optional[int],
) -> Document:
    """Return existing document row by filename, or create a new one."""
    result = await session.execute(
        select(Document).where(Document.filename == filename)
    )
    doc = result.scalars().first()
    if doc is None:
        doc = Document(
            filename=filename,
            doc_type="timetable",
            uploaded_by=None,
            uploaded_at=date.today(),
            scope_branch=scope_branch,
            scope_semester=scope_semester,
            review_status=ReviewStatus.pending,
        )
        session.add(doc)
        await session.flush()
        logger.info("Created document record: %s", filename)
    return doc


def _parse_time(t: str) -> time:
    """Parse 'HH:MM' string into a time object."""
    return datetime.strptime(t, "%H:%M").time()


def _determine_is_lab(
    subject_name: Optional[str],
    start_time: time,
    end_time: time,
    batch: Optional[str],
) -> bool:
    """Heuristic: mark as lab if name contains 'lab' or slot spans ≥ 2 hours."""
    if subject_name and "lab" in subject_name.lower():
        return True
    if batch:
        return True
    start_mins = start_time.hour * 60 + start_time.minute
    end_mins = end_time.hour * 60 + end_time.minute
    return (end_mins - start_mins) >= 120


# ---------------------------------------------------------------------------
# Natural key upsert
# ---------------------------------------------------------------------------

async def _upsert_slot(
    session: AsyncSession,
    branch_id: int,
    semester: int,
    section: Optional[str],
    batch: Optional[str],
    subject_id: int,
    day_of_week: int,
    start_time: time,
    end_time: time,
    room: Optional[str],
    academic_session: str,
    source_document_id: Optional[int],
    needs_review: bool,
    raw_cell_text: str,
    review_reason: Optional[str],
) -> int:
    """Insert or update a timetable_slot row, returning its id.

    Natural key: (branch_id, semester, section, batch, subject_id,
                  day_of_week, start_time, academic_session)

    On conflict: updates mutable fields (room, needs_review, end_time, etc.)
    but never clears needs_review if already True.
    """
    stmt = (
        pg_insert(TimetableSlot)
        .values(
            branch_id=branch_id,
            semester=semester,
            section=section,
            batch=batch,
            subject_id=subject_id,
            day_of_week=day_of_week,
            start_time=start_time,
            end_time=end_time,
            room=room,
            academic_session=academic_session,
            effective_from=date.today(),
            effective_to=None,
            source_document_id=source_document_id,
            needs_review=needs_review,
            raw_cell_text=raw_cell_text,
            review_reason=review_reason,
        )
        .on_conflict_do_update(
            # Constraint name defined in migration; fallback to index inference
            index_elements=None,
            constraint="uq_timetable_slot_natural_key",
            set_={
                "end_time": end_time,
                "room": room,
                "source_document_id": source_document_id,
                "raw_cell_text": raw_cell_text,
                "review_reason": review_reason,
                # NEVER clear needs_review if it was already True in DB
                "needs_review": TimetableSlot.__table__.c.needs_review | needs_review,
            },
        )
        .returning(TimetableSlot.id)
    )
    result = await session.execute(stmt)
    row = result.fetchone()
    return row[0]


async def _upsert_slot_faculty(
    session: AsyncSession, slot_id: int, faculty_id: int
) -> None:
    """Insert (slot_id, faculty_id) pair, silently ignore if already exists."""
    stmt = (
        pg_insert(TimetableSlotFaculty)
        .values(slot_id=slot_id, faculty_id=faculty_id)
        .on_conflict_do_nothing()
    )
    await session.execute(stmt)


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------

async def load_json(
    json_path: str,
    academic_session: str,
    doc_filename: Optional[str] = None,
) -> None:
    """Load a Phase 1 JSON output file into the database.

    Args:
        json_path: Path to the Phase 1 output JSON file.
        academic_session: Academic session string, e.g. "2024-25-ODD".
        doc_filename: Optional document filename to use for the documents row.
                      Defaults to the basename of json_path.
    """
    json_path = str(Path(json_path).resolve())
    with open(json_path, encoding="utf-8") as f:
        entries: list[dict] = json.load(f)

    filename = doc_filename or Path(json_path).name
    logger.info("Loading %d entries from %s (session=%s)", len(entries), filename, academic_session)

    # Track counts for summary log
    inserted = skipped = 0

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Create document record once per load
            doc = await _get_or_create_document(
                session,
                filename=filename,
                scope_branch=None,      # Will be set per-branch below if single branch
                scope_semester=None,
            )

            for entry in entries:
                branch_code: str = entry["branch"]
                semester: int = entry["semester"]
                day_str: str = entry["day"]          # e.g. "TUE"
                start_t: str = entry["start_time"]   # e.g. "10:00"
                end_t: str = entry["end_time"]        # e.g. "11:00"
                subject_code: str = entry["subject_code"]
                subject_name: Optional[str] = entry.get("subject_name")
                faculty_codes: list[str] = entry.get("faculty_codes", [])
                faculty_names: list[Optional[str]] = entry.get("faculty_names", [])
                batch: Optional[str] = entry.get("batch")
                room: Optional[str] = entry.get("room")
                needs_review: bool = bool(entry.get("needs_review", False))
                review_reason: Optional[str] = entry.get("review_reason")
                raw_cell_text: str = entry.get("raw_cell_text", "")

                # --- Reference rows ---
                branch = await _get_or_create_branch(session, branch_code)

                parsed_start = _parse_time(start_t)
                parsed_end = _parse_time(end_t)

                subject = await _get_or_create_subject(
                    session,
                    code=subject_code,
                    name=subject_name,
                    branch_id=branch.id,
                    semester=semester,
                    is_lab=_determine_is_lab(subject_name, parsed_start, parsed_end, batch),
                )

                # Resolve faculty
                resolved_faculty: list[Faculty] = []
                for i, code in enumerate(faculty_codes):
                    name = faculty_names[i] if i < len(faculty_names) else None
                    fac = await _get_or_create_faculty(session, code=code, name=name)
                    resolved_faculty.append(fac)

                # Day conversion
                day_int = _DAY_TO_INT.get(day_str.upper())
                if day_int is None:
                    logger.warning("Unknown day code %r — skipping entry: %s", day_str, raw_cell_text)
                    skipped += 1
                    continue

                # --- Upsert slot ---
                slot_id = await _upsert_slot(
                    session=session,
                    branch_id=branch.id,
                    semester=semester,
                    section=None,       # Phase 1 JSON doesn't carry section; can be updated later
                    batch=batch,
                    subject_id=subject.id,
                    day_of_week=day_int,
                    start_time=parsed_start,
                    end_time=parsed_end,
                    room=room,
                    academic_session=academic_session,
                    source_document_id=doc.id,
                    needs_review=needs_review,
                    raw_cell_text=raw_cell_text,
                    review_reason=review_reason,
                )

                # --- Upsert faculty assignments ---
                for fac in resolved_faculty:
                    await _upsert_slot_faculty(session, slot_id=slot_id, faculty_id=fac.id)

                inserted += 1

    logger.info("Done — %d entries inserted/updated, %d skipped.", inserted, skipped)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Load Phase 1 timetable JSON into the Postgres database."
    )
    p.add_argument("--json", required=True, metavar="PATH", help="Path to Phase 1 output JSON")
    p.add_argument(
        "--session", required=True, metavar="SESSION",
        help='Academic session string, e.g. "2024-25-ODD"'
    )
    p.add_argument(
        "--doc", default=None, metavar="FILENAME",
        help="Optional document filename for the documents table row"
    )
    p.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return p


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asyncio.run(load_json(json_path=args.json, academic_session=args.session, doc_filename=args.doc))
