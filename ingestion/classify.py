"""Page classification module to differentiate timetable grids from lookup tables."""

import re
from typing import Optional
import fitz
import pdfplumber

from ingestion.models import PageClassification

DAY_PATTERNS = [r"\bMON\b", r"\bTUE\b", r"\bWED\b", r"\bTHU\b", r"\bFRI\b", r"\bSAT\b"]
TIME_PATTERNS = [r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}", r"\d{1,2}:\d{2}"]
TIMETABLE_KEYWORDS = ["time table", "timetable", "master time table", "time-table", "break", "branch & sem"]
SUBJECT_KEYWORDS = ["course name", "subject name", "course code", "subject code", "digital logic", "machine learning"]
FACULTY_KEYWORDS = ["faculty name", "faculty code", "teacher name", "staff code", "dr.", "prof."]


def classify_pages(pdf_path: str) -> PageClassification:
    """Classify pages of a timetable PDF into timetable grid vs lookup tables.

    Uses structural and textual heuristics to identify:
    - timetable_pages (grid with days and time intervals)
    - subject_lookup_pages (course code to course name tables)
    - faculty_lookup_pages (faculty code to name tables)
    """
    timetable_pages: list[int] = []
    subject_lookup_pages: list[int] = []
    faculty_lookup_pages: list[int] = []

    with pdfplumber.open(pdf_path) as pdf:
        num_pages = len(pdf.pages)

        for idx, page in enumerate(pdf.pages, start=1):
            text = (page.extract_text() or "").lower()
            tables = page.extract_tables()

            # Flatten text from any detected table cells if page text is empty
            if not text.strip() and tables:
                cell_texts = []
                for tbl in tables:
                    for row in tbl:
                        for c in row:
                            if c:
                                cell_texts.append(str(c).lower())
                text = " ".join(cell_texts)

            # Score the page for each category
            timetable_score = 0
            subject_score = 0
            faculty_score = 0

            # Timetable signals
            for day in ["mon", "tue", "wed", "thu", "fri", "sat"]:
                if day in text:
                    timetable_score += 2
            for kw in TIMETABLE_KEYWORDS:
                if kw in text:
                    timetable_score += 3
            if re.search(r"\d{1,2}:\d{2}", text):
                timetable_score += 3

            # Subject lookup signals
            for kw in SUBJECT_KEYWORDS:
                if kw in text:
                    subject_score += 4
            if "course" in text and "code" in text:
                subject_score += 3
            if "branch" in text and "code" in text:
                subject_score += 2

            # Faculty lookup signals
            for kw in FACULTY_KEYWORDS:
                if kw in text:
                    faculty_score += 4
            if "faculty" in text:
                faculty_score += 4

            # Decision
            if faculty_score > subject_score and faculty_score > timetable_score and faculty_score >= 3:
                faculty_lookup_pages.append(idx)
            elif subject_score > timetable_score and subject_score >= 3:
                subject_lookup_pages.append(idx)
            elif timetable_score >= 3:
                timetable_pages.append(idx)
            else:
                # Structural fallback by table geometry
                # Timetable grids typically have 7+ columns (hourly slots)
                if tables and any(len(row) >= 7 for tbl in tables for row in tbl if row):
                    timetable_pages.append(idx)
                elif idx == 1:
                    timetable_pages.append(idx)
                elif idx == num_pages:
                    faculty_lookup_pages.append(idx)
                else:
                    subject_lookup_pages.append(idx)

    # Fallback if any category is empty in a multi-page document
    if not timetable_pages and num_pages >= 1:
        timetable_pages = [1]
    if not faculty_lookup_pages and num_pages > 1:
        faculty_lookup_pages = [num_pages]
    if not subject_lookup_pages and num_pages > 2:
        subject_lookup_pages = [p for p in range(2, num_pages) if p not in timetable_pages]

    return PageClassification(
        timetable_pages=sorted(timetable_pages),
        subject_lookup_pages=sorted(subject_lookup_pages),
        faculty_lookup_pages=sorted(faculty_lookup_pages),
    )
