"""Lookup table extraction using pdfplumber for subject and faculty tables."""

import re
from typing import Optional
import pdfplumber

from ingestion.models import FacultyLookupEntry, LookupTables, SubjectLookupEntry


def _clean_cell(val: Optional[str]) -> str:
    """Normalize whitespace and linebreaks in a cell value."""
    if not val:
        return ""
    text = re.sub(r"\s+", " ", str(val)).strip()
    return text


def _is_header_or_empty(val: str, keywords: list[str]) -> bool:
    """Check if value matches header keywords or is empty."""
    cleaned = val.lower().strip()
    if not cleaned:
        return True
    return any(kw in cleaned for kw in keywords)


def extract_subject_tables(pdf: pdfplumber.PDF, page_numbers: list[int]) -> list[SubjectLookupEntry]:
    """Parse subject lookup tables from the specified pages."""
    subjects: list[SubjectLookupEntry] = []
    seen_keys: set[tuple[Optional[str], str]] = set()

    for page_num in page_numbers:
        if page_num < 1 or page_num > len(pdf.pages):
            continue
        page = pdf.pages[page_num - 1]
        tables = page.extract_tables()

        for table in tables:
            if not table or len(table) < 2:
                continue

            # Locate the header row
            header_row_idx: Optional[int] = None
            for idx, row in enumerate(table[:5]):
                row_str = " ".join(_clean_cell(c).lower() for c in row if c)
                if "code" in row_str and ("course" in row_str or "subject" in row_str or "name" in row_str):
                    header_row_idx = idx
                    break

            if header_row_idx is None:
                # Fallback: check if row 0 or 1 looks like header
                header_row_idx = 0 if len(table) > 1 else 0

            header_row = [_clean_cell(c).lower() for c in table[header_row_idx]]
            num_cols = len(header_row)

            # Detect repeated column sets (e.g. [Branch, Code, Course Name] * N)
            # Find indices where 'code' appears
            code_indices = [i for i, h in enumerate(header_row) if "code" in h]
            if not code_indices:
                # Guess standard step
                step = 3 if num_cols >= 6 else (2 if num_cols >= 4 else num_cols)
                column_groups = []
                for start_c in range(0, num_cols, step):
                    if start_c + 1 < num_cols:
                        column_groups.append((
                            start_c if step == 3 else None,  # branch
                            start_c + (1 if step == 3 else 0),  # code
                            start_c + (2 if step == 3 else 1),  # name
                        ))
            else:
                # Determine column groups based on detected code positions
                column_groups = []
                for code_idx in code_indices:
                    # Look backwards for branch
                    branch_idx = code_idx - 1 if code_idx > 0 and "branch" in header_row[code_idx - 1] else None
                    # Look forward for course/subject name
                    name_idx = None
                    for next_i in range(code_idx + 1, min(code_idx + 3, num_cols)):
                        if "course" in header_row[next_i] or "subject" in header_row[next_i] or "name" in header_row[next_i]:
                            name_idx = next_i
                            break
                    if name_idx is None and code_idx + 1 < num_cols:
                        name_idx = code_idx + 1

                    if name_idx is not None:
                        column_groups.append((branch_idx, code_idx, name_idx))

            # Process data rows
            data_rows = table[header_row_idx + 1:]
            for row in data_rows:
                for branch_col, code_col, name_col in column_groups:
                    if code_col >= len(row) or name_col >= len(row):
                        continue

                    code_val = _clean_cell(row[code_col])
                    name_val = _clean_cell(row[name_col])
                    branch_val = _clean_cell(row[branch_col]) if branch_col is not None and branch_col < len(row) else None

                    # Ignore headers, titles, or empty codes
                    if not code_val or not name_val:
                        continue
                    if _is_header_or_empty(code_val, ["code", "course", "subject", "branch", "faculty"]):
                        continue
                    if len(code_val) < 3 or code_val.isdigit() and len(code_val) < 4:
                        continue

                    # Clean branch
                    if branch_val and _is_header_or_empty(branch_val, ["branch", "course", "code"]):
                        branch_val = None

                    key = (branch_val, code_val)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        subjects.append(SubjectLookupEntry(
                            code=code_val,
                            name=name_val,
                            branch=branch_val,
                        ))

    return subjects


def extract_faculty_tables(pdf: pdfplumber.PDF, page_numbers: list[int]) -> list[FacultyLookupEntry]:
    """Parse faculty lookup tables from the specified pages."""
    faculty: list[FacultyLookupEntry] = []
    seen_codes: set[str] = set()

    for page_num in page_numbers:
        if page_num < 1 or page_num > len(pdf.pages):
            continue
        page = pdf.pages[page_num - 1]
        tables = page.extract_tables()

        for table in tables:
            if not table or len(table) < 2:
                continue

            # Locate the header row
            header_row_idx: Optional[int] = None
            for idx, row in enumerate(table[:4]):
                row_str = " ".join(_clean_cell(c).lower() for c in row if c)
                if "faculty" in row_str and "code" in row_str:
                    header_row_idx = idx
                    break

            if header_row_idx is None:
                header_row_idx = 0

            header_row = [_clean_cell(c).lower() for c in table[header_row_idx]]
            num_cols = len(header_row)

            # Identify pairs of (name_col, code_col)
            # Typically [Faculty Name, Code, Faculty Name, Code, ...]
            column_pairs = []
            for c in range(0, num_cols, 2):
                if c + 1 < num_cols:
                    # Check if col c is name and col c+1 is code, or vice-versa
                    c0_head = header_row[c]
                    c1_head = header_row[c + 1]
                    if "code" in c0_head and "name" in c1_head:
                        column_pairs.append((c + 1, c))
                    else:
                        column_pairs.append((c, c + 1))

            data_rows = table[header_row_idx + 1:]
            for row in data_rows:
                for name_col, code_col in column_pairs:
                    if name_col >= len(row) or code_col >= len(row):
                        continue

                    name_val = _clean_cell(row[name_col])
                    code_val = _clean_cell(row[code_col])

                    if not name_val or not code_val:
                        continue
                    if _is_header_or_empty(name_val, ["faculty", "name", "code", "department"]):
                        continue
                    if _is_header_or_empty(code_val, ["code", "faculty", "name"]):
                        continue

                    # Faculty codes are typically 2-6 uppercase letters/alphanumeric
                    code_clean = code_val.strip().upper()
                    if code_clean not in seen_codes:
                        seen_codes.add(code_clean)
                        faculty.append(FacultyLookupEntry(
                            code=code_clean,
                            name=name_val,
                        ))

    return faculty


def extract_lookup_tables(
    pdf_path: str,
    subject_pages: list[int],
    faculty_pages: list[int],
) -> LookupTables:
    """Extract both subject and faculty lookup tables using pdfplumber."""
    with pdfplumber.open(pdf_path) as pdf:
        subjects = extract_subject_tables(pdf, subject_pages)
        faculty = extract_faculty_tables(pdf, faculty_pages)

    return LookupTables(subjects=subjects, faculty=faculty)
