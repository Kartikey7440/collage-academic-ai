"""Main pipeline orchestrating page classification, table extraction, vision extraction, resolution, and output generation."""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from ingestion.classify import classify_pages
from ingestion.extract_lookup_tables import extract_lookup_tables
from ingestion.extract_timetable import extract_timetable
from ingestion.models import TimetableEntry
from ingestion.resolve import resolve_timetable_entries

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pipeline")


def run_pipeline(
    input_pdf_path: str,
    output_json_path: str,
    fixture_path: Optional[str] = None,
    anthropic_model: Optional[str] = None,
) -> list[TimetableEntry]:
    """Execute the full timetable extraction pipeline on a PDF file."""
    if not os.path.exists(input_pdf_path):
        raise FileNotFoundError(f"Input PDF not found: {input_pdf_path}")

    logger.info("Stage 1: Classifying pages in %s", input_pdf_path)
    classification = classify_pages(input_pdf_path)
    logger.info(
        "Page classification completed: timetable=%s, subjects=%s, faculty=%s",
        classification.timetable_pages,
        classification.subject_lookup_pages,
        classification.faculty_lookup_pages,
    )

    logger.info("Stage 2: Extracting lookup tables with pdfplumber")
    lookup_tables = extract_lookup_tables(
        input_pdf_path,
        subject_pages=classification.subject_lookup_pages,
        faculty_pages=classification.faculty_lookup_pages,
    )
    logger.info(
        "Lookup tables extracted: %d subjects, %d faculty members",
        len(lookup_tables.subjects),
        len(lookup_tables.faculty),
    )

    logger.info("Stage 3: Extracting timetable grid via PyMuPDF + Anthropic Vision")
    raw_entries = extract_timetable(
        input_pdf_path,
        grid_pages=classification.timetable_pages,
        model=anthropic_model,
        fixture_path=fixture_path,
    )
    logger.info("Timetable grid extracted: %d schedule cells", len(raw_entries))

    logger.info("Stage 4: Resolving codes and flagging discrepancies")
    resolved_entries = resolve_timetable_entries(raw_entries, lookup_tables)

    needs_review_count = sum(1 for e in resolved_entries if e.needs_review)
    logger.info(
        "Resolution completed: %d total entries, %d flagged for review",
        len(resolved_entries),
        needs_review_count,
    )

    logger.info("Stage 5: Writing output JSON to %s", output_json_path)
    output_data = [entry.model_dump() for entry in resolved_entries]
    out_path = Path(output_json_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    logger.info("Successfully wrote %d entries to %s", len(output_data), output_json_path)
    return resolved_entries


def parse_args(args: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract structured college timetable data from a PDF document."
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to input timetable PDF file",
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Path to output JSON file",
    )
    parser.add_argument(
        "--fixture",
        default=None,
        help="Optional path to vision extraction fixture JSON (for testing or offline execution)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Anthropic Claude model for vision extraction (default: claude-3-5-sonnet-20241022)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args(args)


def main():
    args = parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        run_pipeline(
            input_pdf_path=args.input,
            output_json_path=args.output,
            fixture_path=args.fixture,
            anthropic_model=args.model,
        )
    except Exception as exc:
        logger.error("Pipeline failed: %s", exc, exc_info=args.verbose)
        sys.exit(1)


if __name__ == "__main__":
    main()
