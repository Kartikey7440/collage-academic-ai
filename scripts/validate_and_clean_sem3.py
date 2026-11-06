"""Validate and clean out_sem3.json entries."""

import json

with open("out_sem3.json", "r", encoding="utf-8") as f:
    entries = json.load(f)

valid_branches = {"AI", "AIR", "AIDS", "AIML"}
valid_days = {"MON", "TUE", "WED", "THU", "FRI", "SAT"}

cleaned = []
for idx, e in enumerate(entries):
    # Ensure branch
    branch = (e.get("branch") or "AI").strip().upper()
    if branch not in valid_branches:
        if "ROBOT" in branch or "AIR" in branch:
            branch = "AIR"
        elif "DATA" in branch or "DS" in branch or "AIDS" in branch:
            branch = "AIDS"
        elif "ML" in branch:
            branch = "AIML"
        else:
            branch = "AI"

    # Ensure section
    sec = e.get("section")
    if sec not in ("1", "2"):
        sec = None

    # Ensure day
    day = (e.get("day") or "MON").strip().upper()
    if day not in valid_days:
        day = "MON"

    # Clean times
    st = e.get("start_time")
    et = e.get("end_time")

    cleaned.append({
        "type": "timetable_entry",
        "branch": branch,
        "semester": 3,
        "section": sec,
        "day": day,
        "start_time": st,
        "end_time": et,
        "subject_code": e.get("subject_code"),
        "subject_name": e.get("subject_name"),
        "faculty_codes": e.get("faculty_codes", []),
        "faculty_names": e.get("faculty_names", []),
        "batch": e.get("batch"),
        "room": e.get("room"),
        "raw_cell_text": e.get("raw_cell_text", ""),
        "needs_review": bool(e.get("needs_review")),
        "review_reason": e.get("review_reason"),
    })

with open("out_sem3.json", "w", encoding="utf-8") as f:
    json.dump(cleaned, f, indent=2, ensure_ascii=False)

print(f"Cleaned and saved {len(cleaned)} entries to out_sem3.json")
by_branch = {}
for c in cleaned:
    by_branch[c["branch"]] = by_branch.get(c["branch"], 0) + 1
print("Entries per branch:", by_branch)

