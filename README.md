# Document Extraction & Academic AI Agent System

A Python system that extracts structured timetable data from college PDFs (Phase 1), stores it in a
PostgreSQL + pgvector database (Phase 2), and exposes it through a scoped REST API (Phase 3).


---

## Architecture Overview

```
Phase 1: PDF Ingestion            Phase 2: Database Layer          Phase 3: REST API (done)
┌─────────────────────┐          ┌───────────────────────────────┐  ┌───────────────────────────┐
│  Input PDF          │          │  PostgreSQL + pgvector        │  │  FastAPI                  │
│  ↓ classify         │          │  ┌─────────────────────────┐  │  │  POST /auth/signup        │
│  ↓ extract_lookups  │──out.json→│  │  11 normalized tables   │  │  │  POST /auth/login         │
│  ↓ vision (Claude)  │          │  │  + VECTOR(384) embeddings│  │  │  GET  /timetable/today    │
│  ↓ resolve          │          │  └─────────────────────────┘  │  │  GET  /timetable/next-class│
│  out.json           │          │  db/loader.py (upsert)        │  │  GET  /timetable/day/{d}  │
└─────────────────────┘          │  db/queries.py (scoped reads) │  │  GET  /timetable/suppressed│
                                 └───────────────────────────────┘  │  GET  /events/upcoming    │
                                              ↓                     └───────────────────────────┘
                                 Phase 4: AI Agent (LangChain) [TODO]
```

---

## Phase 2 Setup

### Prerequisites

- **Python 3.11+**
- **Docker** (for the Postgres database) or a local Postgres 16+ install with pgvector

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Start Postgres with pgvector

```bash
# Start a Postgres container with pgvector pre-installed
docker compose up -d

# Verify it's healthy
docker compose ps
```

The Docker service uses these defaults:
- Host: `localhost:5432`
- Database: `college_ai`
- Username: `college_ai`
- Password: `college_ai_secret`

### 3. Configure Environment Variables

```bash
# Copy the template
copy .env.example .env

# .env already has the right DATABASE_URL for the Docker setup above.
# Edit if you're using a different Postgres instance.
```

On PowerShell (if not using .env file):
```powershell
$env:DATABASE_URL="postgresql+asyncpg://college_ai:college_ai_secret@localhost:5432/college_ai"
```

### 4. Run Database Migrations

```bash
alembic upgrade head
```

This creates all 11 tables and enables the `pgvector` extension. Safe to re-run (idempotent).

To roll back everything:
```bash
alembic downgrade base
```

### 5. Seed Test Data

```bash
python -m db.seed
```

Inserts deterministic test data (2 branches, 4 subjects, 3 faculty, 2 students, 4 slots, 1 holiday). Idempotent — safe to run multiple times.

### 6. Load Phase 1 Output

```bash
python -m db.loader --json out.json --session 2024-25-ODD
```

Optional flags:
- `--doc <filename>` — override the document filename stored in the `documents` table
- `--verbose` — enable debug SQL logging

Re-running this command is safe — existing rows are updated in-place, `needs_review` is never silently cleared.

---

## Running Tests

### Phase 1 tests (PDF extraction, no DB required)

```bash
python -m pytest -v tests/test_pipeline.py
```

### Phase 3 tests (requires running Postgres)

```bash
# Ensure DATABASE_URL is set and Postgres is running
docker compose up -d
python -m pytest -v tests/test_auth.py
python -m pytest -v tests/test_timetable_api.py
```

Test coverage in `test_timetable_api.py`:
- Student scoping: only sees their own branch/semester slots
- Faculty scoping: sees their assigned slots via `get_classes_by_faculty`
- Admin scoping: must pass explicit `branch_id` + `semester` params
- `GET /timetable/day/{day}`: valid/invalid day, unauthenticated 403
- `GET /timetable/next-class`: returns null or a slot; faculty get 400
- `GET /timetable/suppressed`: far-future holiday returns `suppressed=true`
- `GET /events/upcoming`: limit enforcement, shape, institution-wide events

### All tests

```bash
python -m pytest -v tests/
```

---

## Database Schema

| Table | Purpose |
|---|---|
| `branches` | Academic branches (AI, CS, EC, …) |
| `faculty` | Faculty code → name reference |
| `subjects` | Subject code → name, branch, semester |
| `users` | System users (admin / faculty / student) |
| `students` | Student profile (branch, semester, batch) |
| `faculty_users` | Links user → faculty reference row |
| `student_subject_enrollment` | Which students are enrolled in which subjects |
| `timetable_slots` | Individual scheduled class slots |
| `timetable_slot_faculty` | Junction: slot ↔ faculty (many-to-many) |
| `academic_events` | Holidays, exams — can suppress timetable |
| `documents` | Source document audit trail |
| `document_chunks` | Text chunks + `vector(384)` embeddings for RAG |

---

## Project Structure

```
.
├── ingestion/               ← Phase 1: PDF extraction pipeline
│   ├── classify.py
│   ├── extract_lookup_tables.py
│   ├── extract_timetable.py
│   ├── resolve.py
│   ├── pipeline.py
│   └── models.py
├── db/                      ← Phase 2: Database layer
│   ├── models.py            ← SQLAlchemy 2.x ORM models
│   ├── session.py           ← Async engine + session factory
│   ├── loader.py            ← Phase 1 JSON → DB loader (idempotent)
│   ├── queries.py           ← Scoped async query functions
│   └── seed.py              ← Test data seeder
├── migrations/              ← Alembic migrations
│   ├── env.py
│   └── versions/
│       └── 0001_initial.py
├── api/                     ← Phase 3: REST API
│   ├── main.py              ← FastAPI app factory
│   ├── deps.py              ← Auth + ScopedIdentity dependency
│   ├── security.py          ← JWT helpers (sign/verify)
│   ├── schemas.py           ← Pydantic request/response models
│   └── routers/
│       ├── auth.py          ← POST /auth/{signup,login,refresh}, GET /auth/me
│       └── timetable.py     ← GET /timetable/* and GET /events/upcoming
├── tests/
│   ├── test_pipeline.py     ← Phase 1 tests
│   ├── test_queries.py      ← Phase 2 query isolation tests
│   └── test_timetable_api.py ← Phase 3 REST endpoint tests
├── docker-compose.yml       ← Postgres + pgvector service
├── alembic.ini
├── requirements.txt
├── .env.example             ← Environment variable template
└── out.json                 ← Sample Phase 1 output
```

---

## Known Limitations & Extensibility

### Phase 1
1. **Scanned / Image-Only PDFs**: The pipeline relies on an embedded text layer for `pdfplumber`. Pair with an OCR pre-processor for scanned documents.
2. **Generic Electives** (`DE-1`): Flagged with `needs_review: true` for downstream mapping.
3. **No Hardcoded Values**: Dynamic column detection works across departments without hardcoding branch names or course codes.

### Phase 2
1. **`document_chunks.embedding`** uses `VECTOR(384)` (sized for `all-MiniLM-L6-v2`). Change the dimension in the model and create a new migration if switching embedding models.
2. **`section` field** in `timetable_slots`: Phase 1 JSON does not carry section data. The field is nullable and will be back-filled by a future pipeline update or admin tool.
3. **Auth tokens**: Password hashing is wired up; JWT/session handling is Phase 3.
