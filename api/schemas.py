"""Pydantic request / response schemas for the API layer.

Schemas are grouped by domain:
  - Auth      — signup, login, token pair, token refresh
  - User      — public user representation (no password)
  - Timetable — slot, faculty, subject output shapes
  - Events    — academic event output shape

All schemas use snake_case field names; FastAPI will serialise them to
camelCase only if explicitly configured, which we do *not* do here —
the frontend should speak snake_case.
"""

from datetime import date, time
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


# ---------------------------------------------------------------------------
# Auth — request bodies
# ---------------------------------------------------------------------------


class SignupRequest(BaseModel):
    """Body for POST /auth/signup.

    A student or faculty member can self-register.  Admin accounts are
    created directly in the database by a super-admin; they are not exposed
    through the public signup endpoint.
    """

    email: EmailStr
    password: str = Field(min_length=8, description="Minimum 8 characters")
    role: str = Field(
        pattern="^(student|faculty|admin)$",
        description="Must be 'student' or 'faculty' ('admin' is rejected with HTTP 403)",
    )

    # Student-specific (required when role == "student")
    roll_no: Optional[str] = None
    branch_code: Optional[str] = None
    semester: Optional[int] = Field(None, ge=1, le=8)
    section: Optional[str] = None
    batch: Optional[str] = None

    # Faculty-specific (required when role == "faculty")
    faculty_code: Optional[str] = None


class LoginRequest(BaseModel):
    """Body for POST /auth/login."""

    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """Body for POST /auth/refresh."""

    refresh_token: str


# ---------------------------------------------------------------------------
# Auth — response bodies
# ---------------------------------------------------------------------------


class TokenPair(BaseModel):
    """Returned on successful login or signup."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AccessTokenResponse(BaseModel):
    """Returned on successful token refresh."""

    access_token: str
    token_type: str = "bearer"


# ---------------------------------------------------------------------------
# User — public representation
# ---------------------------------------------------------------------------


class UserOut(BaseModel):
    """Safe user record — password hash is never included."""

    id: int
    email: str
    role: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Timetable — nested sub-schemas
# ---------------------------------------------------------------------------


class FacultyOut(BaseModel):
    """Minimal faculty info embedded inside a slot."""

    id: int
    code: str
    name: str

    model_config = {"from_attributes": True}


class SubjectOut(BaseModel):
    """Minimal subject info embedded inside a slot."""

    id: int
    code: str
    name: str
    is_lab: bool

    model_config = {"from_attributes": True}


class TimetableSlotOut(BaseModel):
    """A single timetable slot as returned by the API."""

    id: int
    day_of_week: int
    day_name: str  # "Monday" … "Sunday" — eliminates client-side int→name mapping
    start_time: time
    end_time: time
    room: Optional[str] = None
    section: Optional[str] = None
    batch: Optional[str] = None
    needs_review: bool
    subject: SubjectOut
    faculty: List[FacultyOut]

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Academic events
# ---------------------------------------------------------------------------


class AcademicEventOut(BaseModel):
    """An academic calendar event (holiday, exam, special day)."""

    id: int
    event_type: str
    title: str
    start_date: date
    end_date: date
    description: Optional[str] = None
    suppresses_timetable: bool

    model_config = {"from_attributes": True}


class SuppressedResponse(BaseModel):
    """Returned by the /timetable/suppressed endpoint."""

    suppressed: bool
    check_date: date
    branch_id: Optional[int] = None
    semester: Optional[int] = None
