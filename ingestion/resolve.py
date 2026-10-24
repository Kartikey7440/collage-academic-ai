"""Resolution module to join timetable entries against subject and faculty lookup tables."""

import re
from typing import Optional

from ingestion.models import LookupTables, RawTimetableEntry, TimetableEntry

DAY_MAPPING = {
    "MON": "MON", "MONDAY": "MON",
    "TUE": "TUE", "TUESDAY": "TUE",
    "WED": "WED", "WEDNESDAY": "WED",
    "THU": "THU", "THURSDAY": "THU",
    "FRI": "FRI", "FRIDAY": "FRI",
    "SAT": "SAT", "SATURDAY": "SAT",
    "SUN": "SUN", "SUNDAY": "SUN",
}


def normalize_day(day_str: str) -> str:
    """Normalize day string to standard 3-letter uppercase code."""
    cleaned = day_str.strip().upper()
    return DAY_MAPPING.get(cleaned, cleaned)


def normalize_time(time_str: str) -> str:
    """Normalize time string to standard HH:MM format."""
    cleaned = time_str.strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", cleaned)
    if match:
        h, m = int(match.group(1)), match.group(2)
        return f"{h:02d}:{m}"
    return cleaned


def resolve_timetable_entries(
    raw_entries: list[RawTimetableEntry],
    lookup_tables: LookupTables,
) -> list[TimetableEntry]:
    """Join raw timetable entries against lookup tables and flag unresolved codes."""
    # Build lookup dictionaries
    # 1. Branch-specific subject lookup
    subject_by_branch_and_code: dict[tuple[str, str], str] = {}
    subject_by_code: dict[str, str] = {}

    for subj in lookup_tables.subjects:
        code_key = subj.code.strip()
        if subj.branch:
            branch_key = subj.branch.strip().upper()
            subject_by_branch_and_code[(branch_key, code_key)] = subj.name.strip()
        # General code map (first one seen or last one)
        if code_key not in subject_by_code:
            subject_by_code[code_key] = subj.name.strip()

    # 2. Faculty lookup
    faculty_map: dict[str, str] = {
        f.code.strip().upper(): f.name.strip()
        for f in lookup_tables.faculty
    }

    resolved_entries: list[TimetableEntry] = []

    for raw in raw_entries:
        review_reasons: list[str] = []
        branch_clean = raw.branch.strip().upper()
        subj_code_clean = raw.subject_code.strip()

        # 1. Resolve subject
        resolved_subject_name: Optional[str] = None
        # Try branch + code first
        if (branch_clean, subj_code_clean) in subject_by_branch_and_code:
            resolved_subject_name = subject_by_branch_and_code[(branch_clean, subj_code_clean)]
        # Fallback to general code
        elif subj_code_clean in subject_by_code:
            resolved_subject_name = subject_by_code[subj_code_clean]
        else:
            review_reasons.append(f"subject code '{raw.subject_code}' not found in lookup table")

        # 2. Resolve faculty
        resolved_faculty_names: list[Optional[str]] = []
        for fc in raw.faculty_codes:
            fc_clean = fc.strip().upper()
            if fc_clean in faculty_map:
                resolved_faculty_names.append(faculty_map[fc_clean])
            else:
                resolved_faculty_names.append(None)
                review_reasons.append(f"faculty code '{fc}' not found in lookup table")

        needs_review = len(review_reasons) > 0
        review_reason_str = "; ".join(review_reasons) if needs_review else None

        entry = TimetableEntry(
            type="timetable_entry",
            branch=raw.branch.strip(),
            semester=raw.semester,
            day=normalize_day(raw.day),
            start_time=normalize_time(raw.start_time),
            end_time=normalize_time(raw.end_time),
            subject_code=raw.subject_code.strip(),
            subject_name=resolved_subject_name,
            faculty_codes=[fc.strip() for fc in raw.faculty_codes],
            faculty_names=resolved_faculty_names,
            batch=raw.batch.strip() if raw.batch else None,
            room=raw.room.strip() if raw.room else None,
            raw_cell_text=raw.raw_cell_text.strip(),
            needs_review=needs_review,
            review_reason=review_reason_str,
        )
        resolved_entries.append(entry)

    return resolved_entries
