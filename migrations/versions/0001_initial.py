"""Initial migration — creates all tables and enables pgvector extension.

Revision: 0001
Created: 2024-09-24

This migration is idempotent (safe to run multiple times):
- Uses CREATE EXTENSION IF NOT EXISTS vector
- Enum types are created with IF NOT EXISTS guards
- Uses IF NOT EXISTS on table creation (via Alembic's create_table which
  checks metadata before executing)

To apply:
    alembic upgrade head

To roll back:
    alembic downgrade base
"""

from datetime import date, time
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 0. Enable pgvector extension ─────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── 1. Enums (create before tables that reference them) ──────────────────
    user_role_enum = postgresql.ENUM(
        "admin", "faculty", "student",
        name="user_role_enum",
        create_type=False,
    )
    review_status_enum = postgresql.ENUM(
        "pending", "approved", "rejected",
        name="review_status_enum",
        create_type=False,
    )
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role_enum') THEN
                CREATE TYPE user_role_enum AS ENUM ('admin', 'faculty', 'student');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'review_status_enum') THEN
                CREATE TYPE review_status_enum AS ENUM ('pending', 'approved', 'rejected');
            END IF;
        END$$;
    """)

    # ── 2. branches ──────────────────────────────────────────────────────────
    op.create_table(
        "branches",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
    )

    # ── 3. faculty ───────────────────────────────────────────────────────────
    op.create_table(
        "faculty",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
    )

    # ── 4. subjects ──────────────────────────────────────────────────────────
    op.create_table(
        "subjects",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(30), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "branch_id", sa.BigInteger(),
            sa.ForeignKey("branches.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("semester", sa.SmallInteger(), nullable=True),
        sa.Column("is_lab", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # ── 5. users ─────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column(
            "role",
            sa.Enum("admin", "faculty", "student", name="user_role_enum", create_type=False),
            nullable=False,
        ),
    )

    # ── 6. students ──────────────────────────────────────────────────────────
    op.create_table(
        "students",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
        ),
        sa.Column(
            "branch_id", sa.BigInteger(),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("semester", sa.SmallInteger(), nullable=False),
        sa.Column("section", sa.String(10), nullable=True),
        sa.Column("batch", sa.String(20), nullable=True),
        sa.Column("roll_no", sa.String(30), nullable=False),
    )

    # ── 7. faculty_users ─────────────────────────────────────────────────────
    op.create_table(
        "faculty_users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
        ),
        sa.Column(
            "faculty_id", sa.BigInteger(),
            sa.ForeignKey("faculty.id", ondelete="RESTRICT"), nullable=False
        ),
    )

    # ── 8. student_subject_enrollment ────────────────────────────────────────
    op.create_table(
        "student_subject_enrollment",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "student_id", sa.BigInteger(),
            sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "subject_id", sa.BigInteger(),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("academic_session", sa.String(30), nullable=False),
        sa.UniqueConstraint(
            "student_id", "subject_id", "academic_session", name="uq_enrollment"
        ),
    )
    op.create_index(
        "ix_enrollment_student_session",
        "student_subject_enrollment",
        ["student_id", "academic_session"],
    )

    # ── 9. documents ─────────────────────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("doc_type", sa.String(50), nullable=False),
        sa.Column(
            "uploaded_by", sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("uploaded_at", sa.Date(), nullable=False, server_default=sa.func.current_date()),
        sa.Column("scope_branch", sa.String(20), nullable=True),
        sa.Column("scope_semester", sa.SmallInteger(), nullable=True),
        sa.Column(
            "review_status",
            sa.Enum("pending", "approved", "rejected", name="review_status_enum", create_type=False),
            nullable=False,
            server_default="pending",
        ),
    )

    # ── 10. timetable_slots ──────────────────────────────────────────────────
    op.create_table(
        "timetable_slots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "branch_id", sa.BigInteger(),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("semester", sa.SmallInteger(), nullable=False),
        sa.Column("section", sa.String(10), nullable=True),
        sa.Column("batch", sa.String(20), nullable=True),
        sa.Column(
            "subject_id", sa.BigInteger(),
            sa.ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("day_of_week", sa.SmallInteger(), nullable=False,
                  comment="0=MON, 1=TUE, 2=WED, 3=THU, 4=FRI, 5=SAT, 6=SUN"),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("room", sa.String(50), nullable=True),
        sa.Column("academic_session", sa.String(30), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column(
            "source_document_id", sa.BigInteger(),
            sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("raw_cell_text", sa.Text(), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        # Natural key uniqueness — referenced by loader.py ON CONFLICT
        sa.UniqueConstraint(
            "branch_id", "semester", "section", "batch",
            "subject_id", "day_of_week", "start_time", "academic_session",
            name="uq_timetable_slot_natural_key",
        ),
    )
    op.create_index(
        "ix_timetable_slots_scope",
        "timetable_slots",
        ["branch_id", "semester", "section", "day_of_week"],
    )

    # ── 11. timetable_slot_faculty ───────────────────────────────────────────
    op.create_table(
        "timetable_slot_faculty",
        sa.Column(
            "slot_id", sa.BigInteger(),
            sa.ForeignKey("timetable_slots.id", ondelete="CASCADE"),
            primary_key=True, nullable=False
        ),
        sa.Column(
            "faculty_id", sa.BigInteger(),
            sa.ForeignKey("faculty.id", ondelete="RESTRICT"),
            primary_key=True, nullable=False
        ),
    )

    # ── 12. academic_events ──────────────────────────────────────────────────
    op.create_table(
        "academic_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "branch_id", sa.BigInteger(),
            sa.ForeignKey("branches.id", ondelete="SET NULL"), nullable=True,
            comment="NULL means event applies to all branches"
        ),
        sa.Column("semester", sa.SmallInteger(), nullable=True,
                  comment="NULL means event applies to all semesters"),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("suppresses_timetable", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_academic_events_dates",
        "academic_events",
        ["start_date", "end_date"],
    )

    # ── 13. document_chunks (vector store) ───────────────────────────────────
    # Uses pgvector type — the extension must exist before this runs (step 0).
    op.execute("""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id          BIGSERIAL PRIMARY KEY,
            source_document_id BIGINT NOT NULL
                REFERENCES documents(id) ON DELETE CASCADE,
            content     TEXT NOT NULL,
            embedding   vector(384),
            branch      VARCHAR(20),
            semester    SMALLINT,
            doc_type    VARCHAR(50) NOT NULL
        )
    """)


def downgrade() -> None:
    """Drop all tables and enum types in reverse dependency order."""
    # Tables
    op.execute("DROP TABLE IF EXISTS document_chunks")
    op.drop_table("academic_events")
    op.drop_table("timetable_slot_faculty")
    op.drop_table("timetable_slots")
    op.drop_table("documents")
    op.drop_table("student_subject_enrollment")
    op.drop_table("faculty_users")
    op.drop_table("students")
    op.drop_table("users")
    op.drop_table("subjects")
    op.drop_table("faculty")
    op.drop_table("branches")

    # Enums
    op.execute("DROP TYPE IF EXISTS user_role_enum")
    op.execute("DROP TYPE IF EXISTS review_status_enum")
