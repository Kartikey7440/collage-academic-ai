"""Academic Calendar Loader.

Loads academic calendar events into the `academic_events` table
and regulatory guidelines into `documents` and `document_chunks`.
Idempotent and safe to run multiple times.

Usage:
    python -m db.calendar_loader
    python -m db.calendar_loader --json "college data/academic_calendar.json"
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.models import (
    AcademicEvent,
    Document,
    DocumentChunk,
    ReviewStatus,
)
from db.session import AsyncSessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("calendar_loader")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = PROJECT_ROOT / "college data" / "academic_calendar.json"
CALENDAR_DOC_FILENAME = "Second  Third Year Academic Calendar 2026-27_F 1 (2).pdf"


def _format_event_title(title: str, session: str) -> str:
    """Disambiguate activity titles with session context if not already present."""
    t = title.strip()
    session_label = "Odd Semester" if "ODD" in session else ("Even Semester" if "EVEN" in session else "Summer Semester")
    if session_label.lower() in t.lower():
        return t
    return f"{t} ({session_label})"


async def load_academic_calendar(
    json_path: Path = DEFAULT_JSON,
    doc_filename: str = CALENDAR_DOC_FILENAME,
) -> Dict[str, int]:
    """Load extracted academic calendar events and instructions into the database."""
    if not json_path.exists():
        raise FileNotFoundError(f"Academic calendar JSON not found: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw_events: List[Dict[str, Any]] = data.get("events", [])
    instructions: List[str] = data.get("instructions", [])

    logger.info("Loaded JSON with %d events and %d instructions", len(raw_events), len(instructions))

    events_inserted = 0
    chunks_inserted = 0

    async with AsyncSessionLocal() as session:
        # 1. Document record
        doc_res = await session.execute(
            select(Document).where(Document.filename == doc_filename)
        )
        doc = doc_res.scalars().first()
        if doc is None:
            doc = Document(
                filename=doc_filename,
                doc_type="academic_calendar",
                uploaded_by=None,
                uploaded_at=date.today(),
                scope_branch=None,
                scope_semester=None,
                review_status=ReviewStatus.approved,
            )
            session.add(doc)
            await session.flush()
            logger.info("Created document row for %s (id=%d)", doc_filename, doc.id)

        # 2. Academic Events
        for ev in raw_events:
            title = _format_event_title(ev["title"], ev["academic_session"])
            start_d = datetime.strptime(ev["start_date"], "%Y-%m-%d").date()
            end_d = datetime.strptime(ev["end_date"], "%Y-%m-%d").date()
            event_type = ev.get("event_type", "academic")
            suppresses = bool(ev.get("suppresses_timetable", False))
            desc = ev.get("description")

            # Check if event already exists
            existing_res = await session.execute(
                select(AcademicEvent).where(
                    AcademicEvent.title == title,
                    AcademicEvent.start_date == start_d,
                    AcademicEvent.end_date == end_d,
                )
            )
            existing = existing_res.scalars().first()
            if existing is None:
                new_event = AcademicEvent(
                    branch_id=None,  # institution-wide across UG II/III & PG II
                    semester=None,   # session disambiguated in title & description
                    event_type=event_type,
                    title=title,
                    start_date=start_d,
                    end_date=end_d,
                    description=desc,
                    suppresses_timetable=suppresses,
                )
                session.add(new_event)
                events_inserted += 1

        await session.flush()

        # 3. Document chunks for guidelines / instructions
        for idx, inst in enumerate(instructions, 1):
            # Check if chunk already exists
            chunk_res = await session.execute(
                select(DocumentChunk).where(
                    DocumentChunk.source_document_id == doc.id,
                    DocumentChunk.content == inst,
                )
            )
            chunk = chunk_res.scalars().first()
            if chunk is None:
                new_chunk = DocumentChunk(
                    source_document_id=doc.id,
                    content=inst,
                    embedding=None,  # Can be populated by embedding pipeline
                    branch=None,
                    semester=None,
                    doc_type="academic_regulation",
                )
                session.add(new_chunk)
                chunks_inserted += 1

        await session.commit()

    logger.info("Calendar load complete: %d events inserted, %d instruction chunks inserted", events_inserted, chunks_inserted)
    return {"events_inserted": events_inserted, "chunks_inserted": chunks_inserted}


def main():
    parser = argparse.ArgumentParser(description="Load Academic Calendar JSON into Postgres")
    parser.add_argument("--json", default=str(DEFAULT_JSON), help="Path to academic calendar JSON")
    parser.add_argument("--doc", default=CALENDAR_DOC_FILENAME, help="Document filename")
    args = parser.parse_args()

    res = asyncio.run(load_academic_calendar(Path(args.json), args.doc))
    print(f"Done: {res['events_inserted']} events, {res['chunks_inserted']} instructions.")


if __name__ == "__main__":
    main()

