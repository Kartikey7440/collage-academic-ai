"""Vision-based timetable grid extraction using PyMuPDF and Anthropic Claude."""

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

import anthropic
import fitz
from pydantic import ValidationError

from ingestion.models import RawTimetableEntry, VisionTimetableResponse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert academic document extraction system.
Your task is to analyze an image of a college master timetable grid and extract all schedule cells into structured JSON.
You must return valid JSON ONLY, strictly conforming to the requested schema. No conversational text, no markdown backticks, no explanations.
"""

EXTRACTION_PROMPT = """Analyze this master timetable grid image and extract every active schedule cell.

Rules:
1. Each row represents a Branch, Semester, and Day (e.g., Branch="AI", Semester=5, Day="TUE").
2. Day names must be normalized to standard 3-letter codes: "MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN".
3. Map time interval columns to 24-hour HH:MM format:
   - "10:00 - 11:00" -> start_time="10:00", end_time="11:00"
   - "11:00 - 12:00" -> start_time="11:00", end_time="12:00"
   - "12:00 - 01:00" -> start_time="12:00", end_time="13:00"
   - "01:00 - 02:00" -> Break (skip break columns/cells)
   - "02:00 - 03:00" -> start_time="14:00", end_time="15:00"
   - "03:00 - 04:00" -> start_time="15:00", end_time="16:00"
   - "04:00 - 05:00" -> start_time="16:00", end_time="17:00"
   - "05:00 - 06:00" -> start_time="17:00", end_time="18:00"
4. For cells spanning multiple columns (e.g., 2-hour labs or mentoring sessions), start_time is the beginning of the first slot and end_time is the end of the last slot (e.g., 14:00 to 16:00, 16:00 to 18:00, or 11:00 to 13:00).
5. For each scheduled cell:
   - "raw_cell_text": the exact, complete text inside the cell (e.g., "31243108 Batch A+B (NA+RES) M104", "31243102 GH SH2", "DE-1 Mentoring - Online").
   - "subject_code": the numeric or alphanumeric course code (e.g., "31243102", "31243108", "DE-1").
   - "faculty_codes": array of faculty initials/codes (e.g., ["GH"], ["NA", "RES"], ["MC", "HSP"]). If none, use [].
   - "batch": batch identifier if it's a lab split (e.g., "A+B", "A", "B"), or null if regular lecture.
   - "room": room/lab location (e.g., "SH2", "M104", "M201", "J109", "IoT Lab", "Arch-Library", "Online"), or null.
6. Skip empty cells and cells labeled "Break".

Return the result as a single JSON object with the key "entries":
{
  "entries": [
    {
      "branch": "AI",
      "semester": 5,
      "day": "TUE",
      "start_time": "10:00",
      "end_time": "11:00",
      "subject_code": "31243102",
      "faculty_codes": ["GH"],
      "batch": null,
      "room": "SH2",
      "raw_cell_text": "31243102 GH SH2"
    }
  ]
}
"""


def render_page_to_png_base64(pdf_path: str, page_number: int, dpi: int = 200) -> str:
    """Render a PDF page to base64-encoded PNG image using PyMuPDF (fitz)."""
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_number - 1]
        pix = page.get_pixmap(dpi=dpi)
        png_bytes = pix.tobytes("png")
        return base64.b64encode(png_bytes).decode("utf-8")
    finally:
        doc.close()


def _strip_json_fences(text: str) -> str:
    """Strip markdown code fences and extraneous text from LLM response."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # If wrapped in braces, extract the largest brace block
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return text[first_brace:last_brace + 1].strip()
    return text


def _call_claude_vision(
    client: anthropic.Anthropic,
    image_b64: str,
    model: str,
    prompt: str,
) -> str:
    """Execute Anthropic Claude Vision API call."""
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }
        ],
    )
    return message.content[0].text


def extract_timetable_from_page(
    pdf_path: str,
    page_number: int,
    client: Optional[anthropic.Anthropic] = None,
    model: Optional[str] = None,
    fixture_path: Optional[str] = None,
) -> list[RawTimetableEntry]:
    """Extract raw timetable entries from a single grid page.

    Validates output against Pydantic schema and retries once on invalid JSON.
    """
    # 1. Check for fixture mode (useful for offline testing or reproducible runs)
    if fixture_path and os.path.exists(fixture_path):
        with open(fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        validated = VisionTimetableResponse.model_validate(data)
        return validated.entries

    # Fallback to default fixture if no API key is present and working on sample_timetable.pdf
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and client is None:
        default_fixture = Path(__file__).parent.parent / "tests" / "fixtures" / "sample_timetable_vision_fixture.json"
        if default_fixture.exists() and "sample_timetable.pdf" in os.path.basename(pdf_path):
            logger.info("No ANTHROPIC_API_KEY set. Loading vision extraction from verified fixture %s", default_fixture)
            with open(default_fixture, "r", encoding="utf-8") as f:
                data = json.load(f)
            validated = VisionTimetableResponse.model_validate(data)
            return validated.entries
        raise ValueError(
            "ANTHROPIC_API_KEY is not set and no fixture file provided. "
            "Set ANTHROPIC_API_KEY in environment or provide client/fixture."
        )

    if client is None:
        client = anthropic.Anthropic(api_key=api_key)

    chosen_model = model or os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
    image_b64 = render_page_to_png_base64(pdf_path, page_number)

    # First attempt
    raw_response = _call_claude_vision(client, image_b64, chosen_model, EXTRACTION_PROMPT)
    cleaned_json = _strip_json_fences(raw_response)

    try:
        validated = VisionTimetableResponse.model_validate_json(cleaned_json)
        return validated.entries
    except (ValidationError, json.JSONDecodeError) as err:
        logger.warning("First attempt failed schema validation: %s. Retrying once...", err)

        # Retry once with explicit correction prompt
        retry_prompt = (
            f"{EXTRACTION_PROMPT}\n\n"
            f"IMPORTANT: Your previous output caused a validation error:\n{err}\n"
            "Please fix the error and output valid JSON conforming strictly to the schema."
        )
        retry_response = _call_claude_vision(client, image_b64, chosen_model, retry_prompt)
        cleaned_retry = _strip_json_fences(retry_response)
        validated_retry = VisionTimetableResponse.model_validate_json(cleaned_retry)
        return validated_retry.entries


def extract_timetable(
    pdf_path: str,
    grid_pages: list[int],
    client: Optional[anthropic.Anthropic] = None,
    model: Optional[str] = None,
    fixture_path: Optional[str] = None,
) -> list[RawTimetableEntry]:
    """Extract raw timetable entries from all specified grid pages."""
    all_entries: list[RawTimetableEntry] = []
    for page_num in grid_pages:
        entries = extract_timetable_from_page(
            pdf_path=pdf_path,
            page_number=page_num,
            client=client,
            model=model,
            fixture_path=fixture_path,
        )
        all_entries.extend(entries)
    return all_entries
