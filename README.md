# Document Extraction & Academic AI Agent System

A complete academic intelligence platform for colleges: extracts structured timetable schedules from PDF documents, loads and indexes them in a PostgreSQL + pgvector database, serves role-scoped schedules via a FastAPI REST API, and powers a Gemini conversational agent for students alongside a dedicated admin review dashboard for resolving unconfirmed or ambiguous OCR slots.

---

## Architecture Overview

```
┌─────────────────────────┐
│       Input PDF         │
│  (Timetable Document)   │
└────────────┬────────────┘
             │ Ingestion (classify, extract OCR tables, resolve)
             ▼
┌─────────────────────────┐
│        out.json         │
└────────────┬────────────┘
             │ Loader (db.loader upsert)
             ▼
┌─────────────────────────┐
│  PostgreSQL + pgvector  │
│  (11 normalized tables) │
└────────────┬────────────┘
             │ Scoped Queries & Timetable Service
             ▼
┌─────────────────────────┐
│     FastAPI REST API    │
│    (/api/v1 endpoints)  │
└──────┬────────────┬─────┘
       │            │
       ▼            ▼
┌─────────────┐  ┌────────────────────────────────────────┐
│ Admin Review│  │ Gemini AI Agent (Tools & RBAC Contain) │
│ Dashboard   │  └───────────────────┬────────────────────┘
│(/app/admin) │                      │
└─────────────┘                      ▼
                         ┌───────────────────────┐
                         │   Student Chat Page   │
                         │      (/app/)          │
                         └───────────────────────┘
```

---

## Environment Variables

Configure the following environment variable names in your `.env` file (do not commit secrets):

- `DATABASE_URL`: Connection string for PostgreSQL (pooled).
- `DATABASE_URL_UNPOOLED`: Direct PostgreSQL connection string for migrations.
- `TEST_DATABASE_URL`: Dedicated test database (must have `test` in name).
- `JWT_SECRET_KEY`: Secret key used to sign and verify JWT authentication tokens.
- `COLLEGE_TIMEZONE`: Timezone for class schedules (e.g. `Asia/Kolkata`).
- `GEMINI_API_KEY`: Google Gemini API key for the conversational AI agent.
- `LLM_MODEL`: Gemini model identifier (e.g. `gemini-2.5-flash` or `gemini-1.5-flash`).
- `LLM_THINKING`: Optional thinking level configuration (`low`, `medium`, `high`).
- `LLM_PAUSE`: Seconds to pause between requests to respect rate limits.
- `DEMO_NOW`: Optional ISO timestamp string to freeze virtual clock for demos/testing.

---

## How to Run

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Run Database Migrations & Seeds

```bash
alembic upgrade head
python -m db.seed
python -m db.loader --json out.json --session 2024-25-ODD
```

### 3. Start the Application Server

```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Open Web Interfaces

- **Student Chat Interface**: `http://localhost:8000/app/`
- **Admin Review Queue**: `http://localhost:8000/app/admin.html`
- **Interactive API Docs (Swagger UI)**: `http://localhost:8000/docs`

---

## How to Run Tests

The test suite runs against the dedicated test database defined in `TEST_DATABASE_URL`.

### Run Affected / Focused Suites

```bash
python -m pytest tests/test_admin_review.py tests/test_timetable_api.py tests/test_chat.py
```

### Run All Suites

```bash
python -m pytest
```

---

## 6-Step End-to-End Demo Script

1. **Sign in as Student**:
   - Navigate to `http://localhost:8000/app/`.
   - Sign in using student credentials (`student1@college.edu` / `password1234`).
2. **Ask Next Class**:
   - Send: *"What is my next class?"*
   - Assistant executes the `get_classes` tool and responds with the upcoming subject, room number, scheduled time, and faculty.
3. **Ask Tomorrow's Classes**:
   - Send: *"What about tomorrow?"*
   - Assistant retrieves tomorrow's scoped schedule and details the day's timetable.
4. **Ask for Another Branch's Timetable**:
   - Send: *"Show me the AIDS branch timetable"*
   - Assistant refuses the cross-branch access or only displays the student's own enrolled branch schedule due to strict server-side scoping.
5. **Admin Review Queue (Fix Flagged Lab)**:
   - Navigate to `http://localhost:8000/app/admin.html` in an admin session.
   - View unconfirmed slots flagged with `needs_review: true` (e.g. ambiguous faculty codes such as `RES`).
   - Fill in the verified faculty code(s) from the dropdown list, click **"Save & confirm"**.
   - The slot is updated, `needs_review` is set to `false`, and the item clears from the queue.
6. **Verify Confirmed Slot as Student**:
   - Return to the student chat interface at `http://localhost:8000/app/`.
   - Ask for Tuesday's classes; the fixed slot now appears confirmed with the newly assigned faculty.

---

## Known Limitations

- **Loader Duplicate Rows**: The loader inserts duplicate rows if run twice with different `--doc` arguments.
- **Effective Dates & Sessions**: Slot queries currently return active records without enforcing date range filters on `effective_from` / `effective_to` or comparing `academic_session`.
- **Loaded Timetable**: Only the July–Dec 2026 timetable is loaded.
- **Academic Data Scope**: No syllabus, exam, or attendance tracking data is ingested yet.
