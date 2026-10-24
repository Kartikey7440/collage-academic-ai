"""Unit and integration tests for the timetable extraction pipeline."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from ingestion.classify import classify_pages
from ingestion.extract_lookup_tables import extract_lookup_tables
from ingestion.extract_timetable import extract_timetable, extract_timetable_from_page
from ingestion.models import (
    FacultyLookupEntry,
    LookupTables,
    RawTimetableEntry,
    SubjectLookupEntry,
    VisionTimetableResponse,
)
from ingestion.pipeline import run_pipeline
from ingestion.resolve import normalize_day, normalize_time, resolve_timetable_entries

SAMPLE_PDF = Path(__file__).parent.parent / "sample_timetable.pdf"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_timetable_vision_fixture.json"


@pytest.fixture
def sample_pdf_path() -> str:
    assert SAMPLE_PDF.exists(), f"sample_timetable.pdf not found at {SAMPLE_PDF}"
    return str(SAMPLE_PDF)


@pytest.fixture
def lookup_tables(sample_pdf_path) -> LookupTables:
    classification = classify_pages(sample_pdf_path)
    return extract_lookup_tables(
        sample_pdf_path,
        subject_pages=classification.subject_lookup_pages,
        faculty_pages=classification.faculty_lookup_pages,
    )


class TestPageClassification:
    def test_page_classification(self, sample_pdf_path):
        """Page classification accurately identifies timetable grid, subject tables, and faculty table."""
        res = classify_pages(sample_pdf_path)
        assert res.timetable_pages == [1]
        assert res.subject_lookup_pages == [2, 3]
        assert res.faculty_lookup_pages == [4]


class TestLookupTableExtraction:
    def test_subject_lookup_extraction(self, lookup_tables):
        """Subject lookup tables extract known codes and names across branches."""
        subjects_by_code = {s.code: s.name for s in lookup_tables.subjects}

        # Check known subject codes from the sample PDF
        assert "31243101" in subjects_by_code
        assert subjects_by_code["31243101"] == "Machine Learning"

        assert "31243102" in subjects_by_code
        assert subjects_by_code["31243102"] == "Cloud Computing & Virtualization"

        assert "31243104" in subjects_by_code
        assert subjects_by_code["31243104"] == "Statistical Computing"

        assert "31243108" in subjects_by_code
        assert subjects_by_code["31243108"] == "Statistical Computing Lab"

        assert "24243101" in subjects_by_code
        assert subjects_by_code["24243101"] == "Theory of Computation"

        assert "27243101" in subjects_by_code
        assert subjects_by_code["27243101"] == "Data Mining and Warehousing"

        assert "28243101" in subjects_by_code
        assert subjects_by_code["28243101"] == "Deep Learning"

    def test_faculty_lookup_extraction(self, lookup_tables):
        """Faculty lookup table extracts faculty codes and names, and omits the ambiguous RES code."""
        faculty_map = {f.code: f.name for f in lookup_tables.faculty}

        # Assert known faculty codes resolve correctly
        assert faculty_map.get("NA") == "Dr. Neelam Arya"
        assert faculty_map.get("GH") == "Mrs. Geetika Hazra"
        assert faculty_map.get("MC") == "Dr. Mausam Chouksey"
        assert faculty_map.get("HSP") == "Dr. Hardev Singh Pal"
        assert faculty_map.get("PD") == "Dr. Pawan Dubey"
        assert faculty_map.get("TS") == "Dr. Tej Singh"

        # Assert that 'RES' is deliberately NOT in the faculty lookup table
        assert "RES" not in faculty_map


class TestVisionTimetableExtraction:
    def test_fixture_loading(self, sample_pdf_path):
        """Timetable extraction can load structured raw entries matching the target schema."""
        entries = extract_timetable(sample_pdf_path, [1], fixture_path=str(FIXTURE_PATH))
        assert len(entries) > 0
        assert all(isinstance(e, RawTimetableEntry) for e in entries)

        # Check lab entry with batch and multiple faculty
        lab_entries = [e for e in entries if "RES" in e.faculty_codes]
        assert len(lab_entries) == 1
        lab = lab_entries[0]
        assert lab.branch == "AI"
        assert lab.subject_code == "31243108"
        assert lab.batch == "A+B"
        assert "NA" in lab.faculty_codes
        assert "RES" in lab.faculty_codes
        assert lab.room == "M104"
        assert lab.raw_cell_text == "31243108 Batch A+B (NA+RES) M104"

    def test_vision_validation_retry_logic(self, sample_pdf_path):
        """Test that invalid JSON triggers retry and re-validation."""
        mock_client = MagicMock()

        # First call returns invalid JSON, second call returns valid JSON
        bad_response = MagicMock()
        bad_response.content = [MagicMock(text="INVALID JSON CONTENT")]

        good_json = json.dumps({
            "entries": [
                {
                    "branch": "AI",
                    "semester": 5,
                    "day": "TUE",
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "subject_code": "31243102",
                    "faculty_codes": ["GH"],
                    "batch": None,
                    "room": "SH2",
                    "raw_cell_text": "31243102 GH SH2",
                }
            ]
        })
        good_response = MagicMock()
        good_response.content = [MagicMock(text=good_json)]

        mock_client.messages.create.side_effect = [bad_response, good_response]

        entries = extract_timetable_from_page(
            sample_pdf_path,
            page_number=1,
            client=mock_client,
            model="test-model",
        )
        assert len(entries) == 1
        assert entries[0].subject_code == "31243102"
        assert mock_client.messages.create.call_count == 2


class TestResolutionAndReviewFlagging:
    def test_known_codes_resolve_cleanly(self, lookup_tables):
        """Known subject and faculty codes resolve to names with needs_review=False."""
        raw_entries = [
            RawTimetableEntry(
                branch="AI",
                semester=5,
                day="TUE",
                start_time="10:00",
                end_time="11:00",
                subject_code="31243102",
                faculty_codes=["GH"],
                batch=None,
                room="SH2",
                raw_cell_text="31243102 GH SH2",
            )
        ]
        resolved = resolve_timetable_entries(raw_entries, lookup_tables)
        assert len(resolved) == 1
        entry = resolved[0]
        assert entry.subject_name == "Cloud Computing & Virtualization"
        assert entry.faculty_names == ["Mrs. Geetika Hazra"]
        assert entry.needs_review is False
        assert entry.review_reason is None

    def test_deliberate_ambiguous_res_flagged_for_review(self, lookup_tables):
        """Faculty code 'RES' must be flagged for review rather than silently matched."""
        raw_entries = [
            RawTimetableEntry(
                branch="AI",
                semester=5,
                day="TUE",
                start_time="14:00",
                end_time="16:00",
                subject_code="31243108",
                faculty_codes=["NA", "RES"],
                batch="A+B",
                room="M104",
                raw_cell_text="31243108 Batch A+B (NA+RES) M104",
            )
        ]
        resolved = resolve_timetable_entries(raw_entries, lookup_tables)
        assert len(resolved) == 1
        entry = resolved[0]

        # Subject and NA should resolve
        assert entry.subject_name == "Statistical Computing Lab"
        assert entry.faculty_names[0] == "Dr. Neelam Arya"
        # RES should be unresolved
        assert entry.faculty_names[1] is None

        # Must be flagged for human review
        assert entry.needs_review is True
        assert entry.review_reason is not None
        assert "faculty code 'RES' not found in lookup table" in entry.review_reason

    def test_unknown_subject_code_flagged(self, lookup_tables):
        """Unrecognized subject codes (like non-standard online mentoring) are flagged for review."""
        raw_entries = [
            RawTimetableEntry(
                branch="AI",
                semester=5,
                day="MON",
                start_time="14:00",
                end_time="16:00",
                subject_code="UNKNOWN_999",
                faculty_codes=[],
                batch=None,
                room="Online",
                raw_cell_text="UNKNOWN_999 Mentoring",
            )
        ]
        resolved = resolve_timetable_entries(raw_entries, lookup_tables)
        assert len(resolved) == 1
        entry = resolved[0]
        assert entry.subject_name is None
        assert entry.needs_review is True
        assert "subject code 'UNKNOWN_999' not found in lookup table" in entry.review_reason

    def test_normalizations(self):
        """Day and time values are normalized to target conventions."""
        assert normalize_day("tuesday") == "TUE"
        assert normalize_day("FRI") == "FRI"
        assert normalize_time("9:00") == "09:00"
        assert normalize_time("14:00") == "14:00"


class TestFullPipeline:
    def test_end_to_end_pipeline(self, sample_pdf_path, tmp_path):
        """Full pipeline execution writes conforming JSON output."""
        output_file = tmp_path / "output.json"
        entries = run_pipeline(
            input_pdf_path=sample_pdf_path,
            output_json_path=str(output_file),
            fixture_path=str(FIXTURE_PATH),
        )

        assert len(entries) > 0
        assert output_file.exists()

        with open(output_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert isinstance(data, list)
        assert len(data) == len(entries)

        # Validate required JSON schema fields for all entries
        required_keys = {
            "type", "branch", "semester", "day", "start_time", "end_time",
            "subject_code", "subject_name", "faculty_codes", "faculty_names",
            "batch", "room", "raw_cell_text", "needs_review", "review_reason"
        }
        for item in data:
            assert required_keys.issubset(item.keys())
            assert item["type"] == "timetable_entry"
            assert item["day"] in {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
            assert isinstance(item["needs_review"], bool)

        # Check that the RES entry is present and flagged
        res_entries = [e for e in data if "RES" in e["faculty_codes"]]
        assert len(res_entries) == 1
        assert res_entries[0]["needs_review"] is True
        assert "RES" in res_entries[0]["review_reason"]
