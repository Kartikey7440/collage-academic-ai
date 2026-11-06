"""Extract the 3rd semester timetable (grid, subjects, faculty) using Gemini Vision."""

import json
import os
import re
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv()

key = os.environ.get("GEMINI_API_KEY")
if not key:
    sys.exit("GEMINI_API_KEY is not set.")

client = genai.Client(api_key=key)
MODEL = "gemini-3.5-flash-lite"


def strip_json_fences(text: str) -> str:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    first_b = text.find("{")
    first_arr = text.find("[")
    if first_b != -1 and (first_arr == -1 or first_b < first_arr):
        last_b = text.rfind("}")
        if last_b > first_b:
            return text[first_b : last_b + 1].strip()
    elif first_arr != -1:
        last_arr = text.rfind("]")
        if last_arr > first_arr:
            return text[first_arr : last_arr + 1].strip()
    return text


def generate_with_retry(prompt: str, image_paths: list[str]) -> str:
    contents = []
    for p in image_paths:
        contents.append(Image.open(p))
    contents.append(prompt)

    for attempt in range(4):
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=contents,
            )
            return resp.text
        except Exception as e:
            print(f"  Attempt {attempt + 1} error: {e}")
            time.sleep(4 * (attempt + 1))
    raise RuntimeError("Failed after 4 attempts")


def extract_subjects():
    print("Extracting subjects from Page 2 and Page 3...")
    prompt = """Analyze these two pages of Course/Subject lookup tables.
Extract all subject courses listed across all tables into a single JSON array of objects.
Each object must have:
- "branch": The branch code (e.g. "AI", "AIR", "AIDS", "AIML", etc.)
- "code": The subject course code (e.g. "31261101", "24243103"). Strip any asterisks.
- "name": Full course name (e.g. "Digital Logic Design", "Robot Operating System")
- "is_lab": boolean (true if the course name contains 'Lab', 'Laboratory', or 'Practical', else false)

Return ONLY valid JSON:
[
  {"branch": "AI", "code": "31261101", "name": "Digital Logic Design", "is_lab": false}
]
"""
    raw = generate_with_retry(prompt, ["scripts/page_2.png", "scripts/page_3.png"])
    clean = strip_json_fences(raw)
    data = json.loads(clean)
    print(f"  Extracted {len(data)} subjects.")
    return data


def extract_faculty():
    print("Extracting faculty from Page 4...")
    prompt = """Analyze this Faculty Lookup Table page.
Extract all faculty members listed with their name and assigned short code.
Return ONLY valid JSON as an array of objects:
[
  {"name": "Dr. Rajni Ranjan Singh", "code": "RRS"},
  {"name": "Dr. Satyam Omar", "code": "SO"}
]
"""
    raw = generate_with_retry(prompt, ["scripts/page_4.png"])
    clean = strip_json_fences(raw)
    data = json.loads(clean)
    print(f"  Extracted {len(data)} faculty members.")
    return data


def extract_grid():
    print("Extracting master timetable grid from Page 1...")
    prompt = """Analyze this master timetable grid image (Semester III, Session July-Dec 2026).
Extract every active class schedule cell across all branches, sections, and days into JSON.

Rules:
1. Identify the Branch and Section from the row labels on the left:
   - "AI" (Sec 1 / S1) -> branch="AI", section="1"
   - "AI" (Sec 2 / S2) -> branch="AI", section="2"
   - "AIR" -> branch="AIR", section=null
   - "AI&DS" or "AIDS" -> branch="AIDS", section=null
   - "AIML" -> branch="AIML", section=null
2. Days: "MON", "TUE", "WED", "THU", "FRI", "SAT".
3. Time slots: Convert to 24-hour HH:MM format:
   - 10:00 to 11:00 -> start_time="10:00", end_time="11:00"
   - 11:00 to 12:00 -> start_time="11:00", end_time="12:00"
   - 12:00 to 01:00 -> start_time="12:00", end_time="13:00"
   - 01:00 to 02:00 -> Break (SKIP)
   - 02:00 to 03:00 -> start_time="14:00", end_time="15:00"
   - 03:00 to 04:00 -> start_time="15:00", end_time="16:00"
   - 04:00 to 05:00 -> start_time="16:00", end_time="17:00"
   - 05:00 to 06:00 -> start_time="17:00", end_time="18:00"
   - Multi-hour slots (e.g. 04:00 - 06:00): start_time="16:00", end_time="18:00".
4. For each cell:
   - "raw_cell_text": exact text in cell (e.g. "31252105 RS M202", "31252109 Batch (A+B) (BSR+SS) M301")
   - "subject_code": the course code (e.g. "31252105", "31252109")
   - "faculty_codes": list of faculty initials/codes in the cell (e.g. ["RS"], ["BSR", "SS"])
   - "room": room name (e.g. "M202", "M301", "Lab-1"), or null
   - "batch": batch if lab split (e.g. "A+B", "A", "B"), or null
   - "semester": 3

Return ONLY valid JSON:
{
  "entries": [
    {
      "branch": "AI",
      "semester": 3,
      "section": "1",
      "day": "TUE",
      "start_time": "10:00",
      "end_time": "11:00",
      "subject_code": "31252105",
      "faculty_codes": ["RS"],
      "batch": null,
      "room": "M202",
      "raw_cell_text": "31252105 RS M202"
    }
  ]
}
"""
    raw = generate_with_retry(prompt, ["scripts/page_1.png"])
    clean = strip_json_fences(raw)
    parsed = json.loads(clean)
    entries = parsed.get("entries", parsed if isinstance(parsed, list) else [])
    print(f"  Extracted {len(entries)} timetable grid entries.")
    return entries


def main():
    subjects = extract_subjects()
    time.sleep(2)
    faculty = extract_faculty()
    time.sleep(2)
    grid_entries = extract_grid()

    # Build lookup maps
    subj_map = {}
    for s in subjects:
        subj_map[s["code"].strip()] = s["name"].strip()
    fac_map = {}
    for f in faculty:
        fac_map[f["code"].strip().upper()] = f["name"].strip()

    # Resolve entries into standard Phase 1 schema
    resolved = []
    for e in grid_entries:
        s_code = (e.get("subject_code") or "").strip()
        s_name = subj_map.get(s_code)
        
        fac_codes = [(c or "").strip().upper() for c in e.get("faculty_codes", []) if (c or "").strip()]
        fac_names = [fac_map.get(c) for c in fac_codes]

        needs_review = False
        reasons = []

        if not s_name:
            needs_review = True
            reasons.append(f"Subject code '{s_code}' not found in lookup table")

        for c, n in zip(fac_codes, fac_names):
            if not n:
                needs_review = True
                reasons.append(f"Faculty code '{c}' not found in lookup table")

        item = {
            "type": "timetable_entry",
            "branch": (e.get("branch") or "AI").strip().upper(),
            "semester": 3,
            "section": (e.get("section") or None),
            "day": (e.get("day") or "MON").strip().upper(),
            "start_time": e.get("start_time"),
            "end_time": e.get("end_time"),
            "subject_code": s_code,
            "subject_name": s_name,
            "faculty_codes": fac_codes,
            "faculty_names": fac_names,
            "batch": e.get("batch"),
            "room": e.get("room"),
            "raw_cell_text": e.get("raw_cell_text") or "",
            "needs_review": needs_review,
            "review_reason": "; ".join(reasons) if reasons else None,
        }
        resolved.append(item)

    out_file = "out_sem3.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(resolved, f, indent=2, ensure_ascii=False)

    # Also save subjects and faculty reference files
    with open("college data/sem3_subjects.json", "w", encoding="utf-8") as f:
        json.dump(subjects, f, indent=2, ensure_ascii=False)
    with open("college data/sem3_faculty.json", "w", encoding="utf-8") as f:
        json.dump(faculty, f, indent=2, ensure_ascii=False)

    flagged = sum(1 for r in resolved if r["needs_review"])
    print(f"\nFinished! Saved {len(resolved)} slots to {out_file}.")
    print(f"  Flagged for review: {flagged}")
    print(f"  Confirmed slots: {len(resolved) - flagged}")


if __name__ == "__main__":
    main()

