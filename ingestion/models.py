"""Pydantic data models for the college document extraction pipeline."""

from typing import Literal, Optional
from pydantic import BaseModel, Field


class PageClassification(BaseModel):
    """Classification of pages within the academic timetable PDF."""
    timetable_pages: list[int] = Field(
        default_factory=list,
        description="1-based page numbers containing timetable grids"
    )
    subject_lookup_pages: list[int] = Field(
        default_factory=list,
        description="1-based page numbers containing subject code lookup tables"
    )
    faculty_lookup_pages: list[int] = Field(
        default_factory=list,
        description="1-based page numbers containing faculty code lookup tables"
    )


class SubjectLookupEntry(BaseModel):
    """Subject code to subject name mapping."""
    code: str
    name: str
    branch: Optional[str] = None


class FacultyLookupEntry(BaseModel):
    """Faculty code to faculty full name mapping."""
    code: str
    name: str


class LookupTables(BaseModel):
    """Aggregated lookup tables parsed from the document."""
    subjects: list[SubjectLookupEntry] = Field(default_factory=list)
    faculty: list[FacultyLookupEntry] = Field(default_factory=list)


class RawTimetableEntry(BaseModel):
    """Raw cell entry extracted from the timetable grid prior to resolution."""
    branch: str
    semester: int
    day: str
    start_time: str
    end_time: str
    subject_code: str
    faculty_codes: list[str] = Field(default_factory=list)
    batch: Optional[str] = None
    room: Optional[str] = None
    raw_cell_text: str


class VisionTimetableResponse(BaseModel):
    """Container model used for Anthropic Vision API schema validation."""
    entries: list[RawTimetableEntry] = Field(
        default_factory=list,
        description="List of extracted timetable cells"
    )


class TimetableEntry(BaseModel):
    """Final resolved timetable entry ready for database insertion."""
    type: Literal["timetable_entry"] = "timetable_entry"
    branch: str
    semester: int
    day: str
    start_time: str
    end_time: str
    subject_code: str
    subject_name: Optional[str] = None
    faculty_codes: list[str] = Field(default_factory=list)
    faculty_names: list[Optional[str]] = Field(default_factory=list)
    batch: Optional[str] = None
    room: Optional[str] = None
    raw_cell_text: str
    needs_review: bool = False
    review_reason: Optional[str] = None
