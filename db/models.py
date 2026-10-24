"""SQLAlchemy 2.x ORM models for the college academic AI agent system.

All models use the DeclarativeBase pattern from SQLAlchemy 2.x.
Relationships are defined with Mapped[] type annotations for full
IDE support and type safety.
"""

import enum
from datetime import date, time
from typing import List, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import expression


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, enum.Enum):
    admin = "admin"
    faculty = "faculty"
    student = "student"


class ReviewStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# ---------------------------------------------------------------------------
# Reference tables
# ---------------------------------------------------------------------------

class Branch(Base):
    """Academic branch / department (e.g. AI, CS, EC)."""
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    # Relationships
    subjects: Mapped[List["Subject"]] = relationship("Subject", back_populates="branch")
    students: Mapped[List["Student"]] = relationship("Student", back_populates="branch")
    timetable_slots: Mapped[List["TimetableSlot"]] = relationship(
        "TimetableSlot", back_populates="branch"
    )
    academic_events: Mapped[List["AcademicEvent"]] = relationship(
        "AcademicEvent", back_populates="branch"
    )

    def __repr__(self) -> str:
        return f"<Branch code={self.code!r}>"


class Faculty(Base):
    """Faculty member reference (code → name)."""
    __tablename__ = "faculty"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Relationships
    faculty_user: Mapped[Optional["FacultyUser"]] = relationship(
        "FacultyUser", back_populates="faculty", uselist=False
    )
    slot_assignments: Mapped[List["TimetableSlotFaculty"]] = relationship(
        "TimetableSlotFaculty", back_populates="faculty"
    )

    def __repr__(self) -> str:
        return f"<Faculty code={self.code!r} name={self.name!r}>"


class Subject(Base):
    """Subject / course reference table."""
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    branch_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True
    )
    semester: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    is_lab: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=expression.false()
    )

    # Relationships
    branch: Mapped[Optional[Branch]] = relationship("Branch", back_populates="subjects")
    timetable_slots: Mapped[List["TimetableSlot"]] = relationship(
        "TimetableSlot", back_populates="subject"
    )
    enrollments: Mapped[List["StudentSubjectEnrollment"]] = relationship(
        "StudentSubjectEnrollment", back_populates="subject"
    )

    def __repr__(self) -> str:
        return f"<Subject code={self.code!r} name={self.name!r}>"


# ---------------------------------------------------------------------------
# Identity tables
# ---------------------------------------------------------------------------

class User(Base):
    """System user — shared across admin / faculty / student roles."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role_enum"), nullable=False
    )

    # Relationships
    student_profile: Mapped[Optional["Student"]] = relationship(
        "Student", back_populates="user", uselist=False
    )
    faculty_profile: Mapped[Optional["FacultyUser"]] = relationship(
        "FacultyUser", back_populates="user", uselist=False
    )
    uploaded_documents: Mapped[List["Document"]] = relationship(
        "Document", back_populates="uploaded_by_user"
    )

    def __repr__(self) -> str:
        return f"<User email={self.email!r} role={self.role}>"


class Student(Base):
    """Student profile — one-to-one with User."""
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    branch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    semester: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    section: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    batch: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    roll_no: Mapped[str] = mapped_column(String(30), nullable=False)

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="student_profile")
    branch: Mapped[Branch] = relationship("Branch", back_populates="students")
    enrollments: Mapped[List["StudentSubjectEnrollment"]] = relationship(
        "StudentSubjectEnrollment", back_populates="student"
    )

    def __repr__(self) -> str:
        return f"<Student roll_no={self.roll_no!r} branch={self.branch_id}>"


class FacultyUser(Base):
    """Faculty profile — one-to-one with User, links to the Faculty reference row."""
    __tablename__ = "faculty_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    faculty_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("faculty.id", ondelete="RESTRICT"), nullable=False
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="faculty_profile")
    faculty: Mapped[Faculty] = relationship("Faculty", back_populates="faculty_user")

    def __repr__(self) -> str:
        return f"<FacultyUser user_id={self.user_id} faculty_id={self.faculty_id}>"


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------

class StudentSubjectEnrollment(Base):
    """Student ↔ Subject enrollment for a given academic session."""
    __tablename__ = "student_subject_enrollment"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    subject_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    academic_session: Mapped[str] = mapped_column(String(30), nullable=False)

    __table_args__ = (
        UniqueConstraint("student_id", "subject_id", "academic_session", name="uq_enrollment"),
        Index("ix_enrollment_student_session", "student_id", "academic_session"),
    )

    # Relationships
    student: Mapped[Student] = relationship("Student", back_populates="enrollments")
    subject: Mapped[Subject] = relationship("Subject", back_populates="enrollments")

    def __repr__(self) -> str:
        return (
            f"<StudentSubjectEnrollment student={self.student_id} "
            f"subject={self.subject_id} session={self.academic_session!r}>"
        )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class Document(Base):
    """Tracks ingested source documents (e.g. timetable PDFs)."""
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    uploaded_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_at: Mapped[Optional[date]] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )
    scope_branch: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    scope_semester: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status_enum"),
        nullable=False,
        server_default="pending",
    )

    # Relationships
    uploaded_by_user: Mapped[Optional[User]] = relationship(
        "User", back_populates="uploaded_documents"
    )
    timetable_slots: Mapped[List["TimetableSlot"]] = relationship(
        "TimetableSlot", back_populates="source_document"
    )
    chunks: Mapped[List["DocumentChunk"]] = relationship(
        "DocumentChunk", back_populates="source_document"
    )

    def __repr__(self) -> str:
        return f"<Document filename={self.filename!r} type={self.doc_type!r}>"


# ---------------------------------------------------------------------------
# Timetable
# ---------------------------------------------------------------------------

class TimetableSlot(Base):
    """A single scheduled class slot, resolved from the timetable grid."""
    __tablename__ = "timetable_slots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
    )
    semester: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    section: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    batch: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    subject_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
    )
    day_of_week: Mapped[int] = mapped_column(
        SmallInteger, nullable=False,
        comment="0=MON, 1=TUE, 2=WED, 3=THU, 4=FRI, 5=SAT, 6=SUN"
    )
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    room: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    academic_session: Mapped[str] = mapped_column(String(30), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source_document_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=expression.false()
    )
    raw_cell_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    review_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "ix_timetable_slots_scope",
            "branch_id", "semester", "section", "day_of_week"
        ),
    )

    # Relationships
    branch: Mapped[Branch] = relationship("Branch", back_populates="timetable_slots")
    subject: Mapped[Subject] = relationship("Subject", back_populates="timetable_slots")
    source_document: Mapped[Optional[Document]] = relationship(
        "Document", back_populates="timetable_slots"
    )
    faculty_assignments: Mapped[List["TimetableSlotFaculty"]] = relationship(
        "TimetableSlotFaculty", back_populates="slot", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<TimetableSlot branch={self.branch_id} sem={self.semester} "
            f"day={self.day_of_week} {self.start_time}-{self.end_time}>"
        )


class TimetableSlotFaculty(Base):
    """Junction table: many faculty can teach one slot (e.g. lab splits)."""
    __tablename__ = "timetable_slot_faculty"

    slot_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("timetable_slots.id", ondelete="CASCADE"),
        primary_key=True, nullable=False
    )
    faculty_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("faculty.id", ondelete="RESTRICT"),
        primary_key=True, nullable=False
    )

    # Relationships
    slot: Mapped[TimetableSlot] = relationship(
        "TimetableSlot", back_populates="faculty_assignments"
    )
    faculty: Mapped[Faculty] = relationship("Faculty", back_populates="slot_assignments")

    def __repr__(self) -> str:
        return f"<TimetableSlotFaculty slot={self.slot_id} faculty={self.faculty_id}>"


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

class AcademicEvent(Base):
    """College calendar events — holidays, exams, special days."""
    __tablename__ = "academic_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    branch_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("branches.id", ondelete="SET NULL"), nullable=True,
        comment="NULL means event applies to all branches"
    )
    semester: Mapped[Optional[int]] = mapped_column(
        SmallInteger, nullable=True,
        comment="NULL means event applies to all semesters"
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suppresses_timetable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=expression.false()
    )

    __table_args__ = (
        Index("ix_academic_events_dates", "start_date", "end_date"),
    )

    # Relationships
    branch: Mapped[Optional[Branch]] = relationship(
        "Branch", back_populates="academic_events"
    )

    def __repr__(self) -> str:
        return f"<AcademicEvent title={self.title!r} {self.start_date}–{self.end_date}>"


# ---------------------------------------------------------------------------
# Vector store
# ---------------------------------------------------------------------------

class DocumentChunk(Base):
    """Chunked text + embedding for RAG retrieval."""
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # VECTOR(384) — sized for all-MiniLM-L6-v2 (local SentenceTransformers model).
    # Change dimension here + in migration if switching to a different model.
    embedding: Mapped[Optional[object]] = mapped_column(Vector(384), nullable=True)
    branch: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    semester: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Relationships
    source_document: Mapped[Document] = relationship(
        "Document", back_populates="chunks"
    )

    def __repr__(self) -> str:
        return f"<DocumentChunk id={self.id} doc={self.source_document_id}>"
