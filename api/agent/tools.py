"""Tools the AI model may call.

Security rule: the model chooses WHICH tool to call and a couple of harmless
arguments (the kind of question, a weekday). Who the user is (branch, semester,
section, batch, faculty) always comes from the logged-in identity on the server.
Nothing the model sends can widen that scope; there is simply no argument for it.
"""

from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import HTTPException
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession

from api import timetable_service as service
from api.config import DAY_INT_TO_NAME
from api.deps import ScopedIdentity

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


# ---------------------------------------------------------------------------
# What the model is told about the tool
# ---------------------------------------------------------------------------

GET_CLASSES = types.FunctionDeclaration(
    name="get_classes",
    description=(
        "Look up the logged-in user's own timetable. The user's identity is applied "
        "automatically on the server: never ask for or pass a branch, semester, batch "
        "or person. query_type: 'next' = next class (today, or the next day that has "
        "one), 'today', 'tomorrow', 'day' = a named weekday (set 'day'), 'week' = the "
        "whole week."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "query_type": types.Schema(
                type=types.Type.STRING,
                enum=["next", "today", "tomorrow", "day", "week"],
            ),
            "day": types.Schema(
                type=types.Type.STRING,
                description="Weekday name such as 'Tuesday'. Only when query_type is 'day'.",
            ),
        },
        required=["query_type"],
    ),
)

GET_ACADEMIC_CALENDAR = types.FunctionDeclaration(
    name="get_academic_calendar",
    description=(
        "Look up college academic calendar dates, events, exams, breaks, holidays, "
        "and regulations/rules (e.g., minor/major exam dates, semester breaks, "
        "attendance requirements, NEC courses, make-up exam rules, summer semester). "
        "query_type: 'upcoming' = upcoming events from today; 'search' = search by keyword "
        "(e.g. 'exam', 'break', 'minor', 'attendance', 'nec', 'nptel')."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "query_type": types.Schema(
                type=types.Type.STRING,
                enum=["upcoming", "search"],
            ),
            "search_term": types.Schema(
                type=types.Type.STRING,
                description="Keyword to search in calendar events and regulations (e.g. 'break', 'exam', 'nec', 'attendance').",
            ),
        },
        required=["query_type"],
    ),
)

TOOLS = [types.Tool(function_declarations=[GET_CLASSES, GET_ACADEMIC_CALENDAR])]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def parse_weekday(text: Optional[str]) -> Optional[int]:
    """'Tuesday', 'tues', 'TUE' -> 1. Returns None if it is not a weekday."""
    t = (text or "").strip().lower()
    if len(t) < 3:
        return None
    for index, name in enumerate(_WEEKDAYS):
        if t[:3] == name[:3]:
            return index
    return None


def fmt_time(t) -> str:
    """datetime.time -> '2:00 PM'."""
    hour = t.hour % 12 or 12
    return f"{hour}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def slot_to_dict(slot, identity: ScopedIdentity) -> dict[str, Any]:
    faculty = [
        link.faculty.name
        for link in (slot.faculty_assignments or [])
        if link.faculty is not None
    ]
    item: dict[str, Any] = {
        "day": DAY_INT_TO_NAME.get(slot.day_of_week, "Unknown"),
        "start": fmt_time(slot.start_time),
        "end": fmt_time(slot.end_time),
        "subject": slot.subject.name if slot.subject else None,
        "subject_code": slot.subject.code if slot.subject else None,
        "room": slot.room,
        "faculty": faculty,
        "is_lab": bool(slot.subject and slot.subject.is_lab),
        "batch": slot.batch,
    }
    if slot.needs_review:
        item["unconfirmed"] = True
        item["note"] = (
            "Not yet confirmed by the department (for example the teacher or room may "
            "still be to be confirmed). Tell the user this."
        )
    # Only the faculty queries load the branch; touching it for students would
    # trigger a lazy load, which is not allowed in async code.
    if identity.is_faculty() and getattr(slot, "branch", None) is not None:
        item["branch"] = slot.branch.code
    return item


def _when(ahead: int, today: int) -> str:
    if ahead == 0:
        return "later today"
    if ahead == 1:
        return "tomorrow"
    name = DAY_INT_TO_NAME.get((today + ahead) % 7, "")
    return f"next {name}" if ahead == 7 else f"on {name}"


# ---------------------------------------------------------------------------
# The tool itself
# ---------------------------------------------------------------------------

async def get_classes(
    db: AsyncSession,
    identity: ScopedIdentity,
    now: datetime,
    query_type: str,
    day: Optional[str] = None,
) -> dict[str, Any]:
    query_type = (query_type or "").strip().lower()
    today = now.weekday()
    out: dict[str, Any] = {
        "query": query_type,
        "now": f"{DAY_INT_TO_NAME[today]} {fmt_time(now.time())} (college time)",
    }

    if query_type == "next":
        slot, ahead = await service.upcoming_class(db, identity, now)
        if await service.is_suppressed(db, identity, now.date()):
            out["holiday_or_event_today"] = True
        if slot is None:
            out["next_class"] = None
            out["message"] = "No upcoming classes were found in the timetable."
        else:
            out["next_class"] = slot_to_dict(slot, identity)
            out["when"] = _when(ahead, today)
        return out

    if query_type in ("today", "tomorrow"):
        offset = 0 if query_type == "today" else 1
        target_day = (today + offset) % 7
        target_date = now.date() + timedelta(days=offset)
        suppressed = await service.is_suppressed(db, identity, target_date)
        slots = [] if suppressed else await service.classes(db, identity, target_day)
        out.update(
            day=DAY_INT_TO_NAME[target_day],
            date=target_date.isoformat(),
            classes=[slot_to_dict(s, identity) for s in slots],
        )
        if suppressed:
            out["holiday_or_event"] = True
            out["message"] = "No classes: a holiday or event covers this date."
        elif not slots:
            out["message"] = f"No classes are scheduled on {DAY_INT_TO_NAME[target_day]}."
        return out

    if query_type == "day":
        weekday = parse_weekday(day)
        if weekday is None:
            return {"error": f"I could not understand the day '{day}'. Use Monday to Sunday."}
        slots = await service.classes(db, identity, weekday)
        out.update(day=DAY_INT_TO_NAME[weekday], classes=[slot_to_dict(s, identity) for s in slots])
        if not slots:
            out["message"] = f"No classes are scheduled on {DAY_INT_TO_NAME[weekday]}."
        return out

    if query_type == "week":
        slots = await service.classes(db, identity, None)
        week: dict[str, list] = {}
        for s in slots:
            week.setdefault(DAY_INT_TO_NAME.get(s.day_of_week, "Unknown"), []).append(
                slot_to_dict(s, identity)
            )
        out["week"] = week
        out["days_without_classes"] = [
            DAY_INT_TO_NAME[i] for i in range(7) if DAY_INT_TO_NAME[i] not in week
        ]
        return out

    return {"error": f"Unknown query_type '{query_type}'."}


async def query_academic_calendar(
    db: AsyncSession,
    identity: ScopedIdentity,
    now: datetime,
    *,
    query_type: str,
    search_term: Optional[str] = None,
) -> dict[str, Any]:
    """Query academic events and regulation guidelines from the database."""
    from db.models import AcademicEvent, DocumentChunk
    from sqlalchemy import or_, select

    today = now.date()
    term = (search_term or "").strip().lower()

    if query_type == "upcoming":
        stmt = (
            select(AcademicEvent)
            .where(
                AcademicEvent.end_date >= today,
                or_(
                    AcademicEvent.branch_id.is_(None),
                    AcademicEvent.branch_id == identity.branch_id,
                ),
                or_(
                    AcademicEvent.semester.is_(None),
                    AcademicEvent.semester == identity.semester,
                ),
            )
            .order_by(AcademicEvent.start_date)
            .limit(10)
        )
        res = await db.execute(stmt)
        events = res.scalars().all()
        return {
            "query_type": "upcoming",
            "from_date": today.isoformat(),
            "events": [
                {
                    "title": e.title,
                    "type": e.event_type,
                    "start_date": e.start_date.isoformat(),
                    "end_date": e.end_date.isoformat(),
                    "suppresses_classes": e.suppresses_timetable,
                    "description": e.description,
                }
                for e in events
            ],
        }

    # query_type == "search"
    event_stmt = (
        select(AcademicEvent)
        .where(
            or_(
                AcademicEvent.title.ilike(f"%{term}%"),
                AcademicEvent.description.ilike(f"%{term}%"),
                AcademicEvent.event_type.ilike(f"%{term}%"),
            )
        )
        .order_by(AcademicEvent.start_date)
        .limit(10)
    )
    event_res = await db.execute(event_stmt)
    matched_events = event_res.scalars().all()

    chunk_stmt = (
        select(DocumentChunk.content)
        .where(DocumentChunk.content.ilike(f"%{term}%"))
        .limit(5)
    )
    chunk_res = await db.execute(chunk_stmt)
    matched_chunks = chunk_res.scalars().all()

    return {
        "query_type": "search",
        "search_term": term,
        "matched_events": [
            {
                "title": e.title,
                "type": e.event_type,
                "start_date": e.start_date.isoformat(),
                "end_date": e.end_date.isoformat(),
                "suppresses_classes": e.suppresses_timetable,
                "description": e.description,
            }
            for e in matched_events
        ],
        "relevant_guidelines": list(matched_chunks),
    }


async def run_tool(
    name: str,
    args: dict[str, Any],
    *,
    db: AsyncSession,
    identity: ScopedIdentity,
    now: datetime,
) -> dict[str, Any]:
    """Run a tool the model asked for. Never raises for expected problems."""
    if name == "get_classes":
        try:
            return await get_classes(
                db,
                identity,
                now,
                query_type=str(args.get("query_type", "")),
                day=args.get("day"),
            )
        except HTTPException as exc:
            return {"error": str(exc.detail)}
    elif name == "get_academic_calendar":
        try:
            return await query_academic_calendar(
                db,
                identity,
                now,
                query_type=str(args.get("query_type", "upcoming")),
                search_term=args.get("search_term"),
            )
        except HTTPException as exc:
            return {"error": str(exc.detail)}
        except Exception as exc:
            return {"error": str(exc)}
    return {"error": f"Unknown tool '{name}'."}


# ---------------------------------------------------------------------------
# Plain-text rendering (used only when the AI service is unavailable)
# ---------------------------------------------------------------------------

def _line(item: dict) -> str:
    bits = [b for b in (item.get("room"), ", ".join(item.get("faculty") or [])) if b]
    text = f"{item['start']} - {item['end']}: {item['subject']}"
    if bits:
        text += f" ({'; '.join(bits)})"
    if item.get("batch"):
        text += f" [batch {item['batch']}]"
    if item.get("unconfirmed"):
        text += " - not yet confirmed by the department"
    return text


def format_result(result: dict[str, Any]) -> str:
    """Turn a tool result into a short plain-text answer, without any AI."""
    if "error" in result:
        return result["error"]
    if "events" in result:
        if not result["events"]:
            return "No upcoming academic events found."
        lines = ["Upcoming Academic Events:"]
        for ev in result["events"]:
            dates = ev["start_date"] if ev["start_date"] == ev["end_date"] else f"{ev['start_date']} to {ev['end_date']}"
            lines.append(f"• {dates}: {ev['title']}")
        return "\n".join(lines)
    if "matched_events" in result:
        lines = []
        if result["matched_events"]:
            lines.append(f"Events matching '{result.get('search_term', '')}':")
            for ev in result["matched_events"]:
                dates = ev["start_date"] if ev["start_date"] == ev["end_date"] else f"{ev['start_date']} to {ev['end_date']}"
                lines.append(f"• {dates}: {ev['title']}")
        if result.get("relevant_guidelines"):
            lines.append("Academic Guidelines:")
            lines.extend(f"• {g}" for g in result["relevant_guidelines"])
        return "\n".join(lines) or "No matching academic events or guidelines found."
    if "next_class" in result:
        if result["next_class"] is None:
            return result.get("message", "No upcoming classes.")
        return f"Your next class ({result['when']}): {_line(result['next_class'])}"
    if "week" in result:
        lines = []
        for day_name, items in result["week"].items():
            lines.append(f"{day_name}:")
            lines.extend(f"  {_line(i)}" for i in items)
        return "\n".join(lines) or "No classes found."
    if "classes" in result:
        if not result["classes"]:
            return result.get("message", "No classes.")
        header = f"{result.get('day', '')}:"
        return "\n".join([header] + [f"  {_line(i)}" for i in result["classes"]])
    return "No classes found."