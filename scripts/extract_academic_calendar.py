"""Extract academic calendar events and guidelines from PDF into structured JSON."""

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("academic_calendar")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PDF_PATH = PROJECT_ROOT / "college data" / "Second  Third Year Academic Calendar 2026-27_F 1 (2).pdf"
OUTPUT_JSON_PATH = PROJECT_ROOT / "college data" / "academic_calendar.json"

MONTH_MAP = {
    "january": 1, "jan": 1, "jan.": 1,
    "february": 2, "feb": 2, "feb.": 2,
    "march": 3, "mar": 3, "mar.": 3,
    "april": 4, "apr": 4, "apr.": 4,
    "may": 5,
    "june": 6, "jun": 6, "jun.": 6,
    "july": 7, "jul": 7, "jul.": 7,
    "august": 8, "aug": 8, "aug.": 8,
    "september": 9, "sep": 9, "sep.": 9, "sept": 9, "sept.": 9,
    "october": 10, "oct": 10, "oct.": 10,
    "november": 11, "nov": 11, "nov.": 11,
    "december": 12, "dec": 12, "dec.": 12,
}


def clean_activity_title(text: str) -> str:
    """Normalize OCR/PDF kerning artifacts in activity names."""
    replacements = [
        ("Onli ne", "Online"),
        ("Teac hing", "Teaching"),
        ("Min or", "Minor"),
        ("Foun dation", "Foundation"),
        ("Noti fication", "Notification"),
        ("Sem ester", "Semester"),
        ("Proj ect", "Project"),
        ("Mak e-up", "Make-up"),
        ("Maj or", "Major"),
        ("Pre- Result", "Pre-Result"),
        ("Grad e", "Grade"),
        ("Resu lt", "Result"),
        ("\n", " "),
        ("\ufffd", '"'),
        ("*", ""),
    ]
    t = text
    for old, new in replacements:
        t = t.replace(old, new)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def parse_date_range(raw: Optional[str]) -> Optional[Tuple[str, str]]:
    """Parse natural language date strings like '21st to 25th September 2026' into ISO (YYYY-MM-DD, YYYY-MM-DD)."""
    if not raw or not raw.strip():
        return None
    s = raw.strip()
    if any(placeholder in s for placeholder in ["", "...", "---", "None"]):
        # Check if there is actual date text inside despite placeholder chars
        cleaned = re.sub(r"[.\-]", "", s).strip()
        if not cleaned:
            return None
        s = cleaned

    # Strip ordinal suffixes
    s = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", s)
    s = s.replace("&", "to").replace("and", "to")

    # 1. Cross-month range: e.g. "23 Nov. to 6 Dec. 2026" or "20 May to 18 June 2027"
    m_cross = re.search(r"(\d+)\s+([A-Za-z.]+)\s+to\s+(\d+)\s+([A-Za-z.]+)\s+(\d{4})", s)
    if m_cross:
        d1, m1, d2, m2, y = m_cross.groups()
        mo1 = MONTH_MAP[m1.lower().rstrip(".")]
        mo2 = MONTH_MAP[m2.lower().rstrip(".")]
        start_d = date(int(y), mo1, int(d1)).isoformat()
        end_d = date(int(y), mo2, int(d2)).isoformat()
        return (start_d, end_d)

    # 2. Same-month range: e.g. "21 to 25 September 2026"
    m_range = re.search(r"(\d+)\s+to\s+(\d+)\s+([A-Za-z.]+)\s+(\d{4})", s)
    if m_range:
        d1, d2, m, y = m_range.groups()
        mo = MONTH_MAP[m.lower().rstrip(".")]
        start_d = date(int(y), mo, int(d1)).isoformat()
        end_d = date(int(y), mo, int(d2)).isoformat()
        return (start_d, end_d)

    # 3. Single date: e.g. "15 July 2026"
    m_single = re.search(r"(\d+)\s+([A-Za-z.]+)\s+(\d{4})", s)
    if m_single:
        d, m, y = m_single.groups()
        mo = MONTH_MAP[m.lower().rstrip(".")]
        dt = date(int(y), mo, int(d)).isoformat()
        return (dt, dt)

    logger.warning("Could not parse date range: %r", raw)
    return None


def classify_event_type(title: str) -> str:
    """Classify activity into standardized event_type category."""
    t = title.lower()
    if "registration" in t:
        return "registration"
    if "teaching starts" in t or "teaching ends" in t:
        return "instruction"
    if "break" in t:
        return "break"
    if "foundation day" in t:
        return "holiday"
    if "attendance" in t:
        return "attendance"
    if "evaluation" in t or "minor" in t or "major" in t or "make-up" in t:
        return "exam"
    if "internship" in t or "training" in t:
        return "internship"
    if "result" in t or "grade" in t:
        return "result"
    return "academic"


def should_suppress_timetable(title: str, event_type: str) -> bool:
    """Return True if the event suspends standard regular timetable classes."""
    t = title.lower()
    if event_type in ("break", "holiday"):
        return True
    if "major evaluation" in t:
        return True
    return False


def extract_academic_calendar() -> Dict[str, Any]:
    """Extract all events and rules from PDF."""
    logger.info("Opening PDF: %s", PDF_PATH)
    events: List[Dict[str, Any]] = []
    instructions: List[str] = []

    with pdfplumber.open(PDF_PATH) as pdf:
        # Page 1: Timeline Events
        page1 = pdf.pages[0]
        table = page1.extract_table()
        if not table:
            raise ValueError("No table detected on Page 1")

        header = table[0]
        logger.info("Table columns detected: %s", header)

        # Columns: [0: S.No., 1: Activity, 2: Odd Sem, 3: Even Sem, 4: Summer Sem]
        for row in table[1:]:
            if not row or len(row) < 5 or not row[0]:
                continue
            s_no = row[0].strip().rstrip(".")
            raw_title = row[1]
            title = clean_activity_title(raw_title)

            # Odd semester (III & V)
            odd_raw = row[2]
            odd_dates = parse_date_range(odd_raw)
            if odd_dates:
                event_type = classify_event_type(title)
                events.append({
                    "title": title,
                    "event_type": event_type,
                    "academic_session": "2026-27-ODD",
                    "semesters": [3, 5],
                    "start_date": odd_dates[0],
                    "end_date": odd_dates[1],
                    "suppresses_timetable": should_suppress_timetable(title, event_type),
                    "description": f"Session 2026-27 Odd Semester (Sem III & V) - Activity #{s_no}: {title}",
                    "s_no": int(s_no) if s_no.isdigit() else None,
                })

            # Even semester (IV & VI)
            even_raw = row[3]
            even_dates = parse_date_range(even_raw)
            if even_dates:
                event_type = classify_event_type(title)
                events.append({
                    "title": title,
                    "event_type": event_type,
                    "academic_session": "2026-27-EVEN",
                    "semesters": [4, 6],
                    "start_date": even_dates[0],
                    "end_date": even_dates[1],
                    "suppresses_timetable": should_suppress_timetable(title, event_type),
                    "description": f"Session 2026-27 Even Semester (Sem IV & VI) - Activity #{s_no}: {title}",
                    "s_no": int(s_no) if s_no.isdigit() else None,
                })

            # Summer semester (Optional)
            summer_raw = row[4]
            summer_dates = parse_date_range(summer_raw)
            if summer_dates:
                event_type = classify_event_type(title)
                events.append({
                    "title": title,
                    "event_type": event_type,
                    "academic_session": "2026-27-SUMMER",
                    "semesters": [3, 4, 5, 6],
                    "start_date": summer_dates[0],
                    "end_date": summer_dates[1],
                    "suppresses_timetable": False,
                    "description": f"Session 2026-27 Summer Semester (Optional) - Activity #{s_no}: {title}",
                    "s_no": int(s_no) if s_no.isdigit() else None,
                })

        # Page 2: Instructions and Policies
        page2 = pdf.pages[1]
        text2 = page2.extract_text()
        raw_instructions = []
        for line in text2.split("\n"):
            line = line.strip().replace("\ufffd", '"')
            # Match numbered instruction paragraphs
            if re.match(r"^\d+\.\s+", line):
                raw_instructions.append(line)
            elif raw_instructions and not line.startswith("Page ") and not line.startswith("(Academic Section)"):
                # Append continuation line to previous instruction
                raw_instructions[-1] += " " + line

        # Renumber and clean instructions
        for i, raw_inst in enumerate(raw_instructions, 1):
            clean_inst = re.sub(r"^\d+\.\s*", f"{i}. ", raw_inst)
            clean_inst = re.sub(r"\s+", " ", clean_inst).strip()
            instructions.append(clean_inst)

    logger.info("Extraction complete: %d timeline events, %d academic instructions", len(events), len(instructions))

    data = {
        "academic_year": "2026-2027",
        "target_audience": "All UG Second and Third Year Classes & PG Second Year Classes",
        "total_events": len(events),
        "events": events,
        "instructions": instructions,
    }

    OUTPUT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info("Saved extracted calendar to: %s", OUTPUT_JSON_PATH)
    return data


if __name__ == "__main__":
    extract_academic_calendar()
