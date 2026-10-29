# Project Technical Handoff Report

**Project**: MITS Academic Intelligence & Timetable AI Assistant  
**Date**: October 29, 2026  
**Audience**: AI Coding Agents / Developers Continuing This Workspace  

---

## 1. Executive Overview

This system is an end-to-end college academic assistant platform. It extracts schedule data from raw timetable PDFs, persists normalized relational schedules in PostgreSQL + pgvector, enforces role-scoped access control (Student, Faculty, Admin) via FastAPI, and powers a Gemini conversational agent for students along with a web dashboard for administrative OCR review.

### Architecture Pipeline
```
[PDF Timetable]
       │
       ▼ Ingestion (ingestion/classify, extract_lookup_tables, extract_timetable, resolve)
   [out.json] (77 structured slots)
       │
       ▼ Loader (db/loader.py idempotent upsert)
[PostgreSQL + pgvector] (11 normalized tables, Alembic migrations)
       │
       ▼ Scoped Queries & Business Rules (db/queries.py, api/timetable_service.py)
[FastAPI REST API] (api/routers/{auth, timetable, chat, admin})
       ├──► [Gemini AI Chat Agent] (api/agent/) ──► Student Web App (/app/)
       └──► [Admin Review Queue] (api/routers/admin.py) ──► Admin Web Dashboard (/app/admin.html)
```

---

## 2. Directory Structure & Key Files

```
├── ingestion/                  # Phase 1: PDF extraction pipeline
│   ├── classify.py             # Page classification (grid, lookup, faculty tables)
│   ├── extract_lookup_tables.py# Subject & faculty table OCR/regex parser
│   ├── extract_timetable.py    # Timetable grid parser
│   ├── resolve.py              # Entity resolution & review flagging
│   └── models.py               # Pydantic extraction schemas
├── db/                         # Phase 2: Database layer
│   ├── models.py               # SQLAlchemy 2.x ORM models (11 tables)
│   ├── session.py              # Async engine & sessionmaker (NullPool for tests)
│   ├── queries.py              # Scoped async queries & slot_scope_conditions()
│   ├── loader.py               # JSON -> DB loader
│   └── seed.py                 # Deterministic seed data generator
├── api/                        # Phase 3 & 4: REST API, Service, & Agent
│   ├── main.py                 # FastAPI application factory & /app static mount
│   ├── deps.py                 # JWT extraction & ScopedIdentity dependency
│   ├── security.py             # Password hashing (bcrypt) & JWT encode/decode
│   ├── clock.py                # Virtual clock (honors DEMO_NOW override)
│   ├── timetable_service.py    # Role access rules & upcoming_class wrap-around
│   ├── agent/
│   │   ├── agent.py            # Gemini conversational agent, tool loop, 429 fallback
│   │   └── tools.py            # Timetable tools exposed to LLM
│   └── routers/
│       ├── auth.py             # /auth/signup, /auth/login, /auth/refresh, /auth/me
│       ├── timetable.py        # /timetable/today, /next-class, /day/{d}, /suppressed
│       ├── chat.py             # POST /api/v1/chat (conversational endpoint)
│       └── admin.py            # GET /admin/review-queue, /admin/faculty, PATCH /admin/slots/{id}
├── static/                     # Web Frontends (Pure HTML/JS, zero build tools)
│   ├── index.html              # Student chat interface with suggestions & JWT auth
│   └── admin.html              # Admin review dashboard (resolving needs_review slots)
├── scripts/                    # Developer test scripts
│   ├── llm_check_basic.py      # Gemini API key & model connectivity check
│   └── llm_check_tools.py      # Mock function-calling verification
└── tests/                      # Automated Test Suite (106 total tests)
    ├── test_pipeline.py        # Phase 1 PDF extraction & resolution (10 tests)
    ├── test_db_guard.py        # Safety check: ensures tests only touch test DB (4 tests)
    ├── test_queries.py         # DB query scoping, batch, section, day=None (32 tests)
    ├── test_auth.py            # User registration & JWT auth (19 tests)
    ├── test_timetable_api.py   # REST API endpoint scoping & needs_review (22 tests)
    ├── test_timetable_service.py # Service layer & virtual clock logic (13 tests)
    ├── test_chat.py            # Mocked Gemini agent, 403 admin, 429 retry (6 tests)
    └── test_admin_review.py    # Admin review queue API, RBAC, PATCH (15 tests)
```

---

## 3. Database Safety & Guard Rails (CRITICAL)

- **Development/Production DB Guard**: `tests/conftest.py` strictly enforces that `TEST_DATABASE_URL` contains `"test"` in its name and does not point to the development database (`neondb`).
- **NEVER** run migrations, loaders, or raw drop commands against `neondb`. All automated tests operate against the isolated test database `test_college_ai`.
- **Secrets Policy**: Never print, log, or commit database connection URIs, JWT secret keys, or Google Gemini API keys.

---

## 4. Key Business Logic & Rules Implemented

1. **Timetable Slot Scoping (`db/queries.py` -> `slot_scope_conditions`)**:
   - `NULL` batch: Visible to all students in that branch/semester.
   - Joint `"A+B"` batch: Visible to students in Batch A, Batch B, or students with no assigned batch.
   - Single batch (`"A"`, `"B"`, `"C"`): Visible **only** to that specific batch.
   - `NULL` section: Visible to all sections.
   - Label normalization: Inputs are trimmed and uppercase; `""`, `"null"`, `"none"` are treated as `None`.
2. **Student Visibility for Unconfirmed Slots**:
   - Slots with `needs_review = true` are **not hidden** from students; they are returned with `needs_review: true` so the client can display them with an "unconfirmed / to be confirmed" badge rather than hiding scheduled classes.
3. **Admin Review Queue (`api/routers/admin.py`)**:
   - `GET /api/v1/admin/review-queue`: Lists all slots with `needs_review = true`.
   - `GET /api/v1/admin/faculty`: Dropdown list of valid `{code, name}` pairs.
   - `PATCH /api/v1/admin/slots/{id}`: Replaces assigned faculty, updates room, sets `needs_review = false` when `mark_reviewed = true`. If an invalid faculty code is submitted, rejects with `422` and leaves slot untouched.
4. **Conversational Agent (`api/agent/agent.py`)**:
   - Role-Gated: Students and faculty only (Admins receive `403 Forbidden`).
   - Tenant Containment: Server ignores any injected model arguments attempting to query other branches or semesters.
   - Resilience: Handles HTTP 429 rate limits via backoff; falls back to deterministic rule-based output if Gemini quota is exhausted.

---

## 5. Test Suite Status

- **Full Suite**: 106 automated tests passing cleanly across all files.
- **Admin Review + Core Endpoints**: 43 tests passing in `tests/test_admin_review.py`, `tests/test_timetable_api.py`, and `tests/test_chat.py`.
- **Running tests**:
  ```powershell
  # Focused check:
  python -m pytest tests/test_admin_review.py tests/test_timetable_api.py tests/test_chat.py
  # Full suite:
  python -m pytest
  ```
- **Note on Network Execution**: When running pytest inside an agent sandbox, remote queries to AWS Neon can experience socket delays or timeouts. Run with direct host networking or in host PowerShell for fastest execution.

---

## 6. How to Run Locally

```powershell
# 1. Start development server
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# 2. Access Web Pages:
# Student Chat Assistant: http://localhost:8000/app/
# Admin Review Dashboard: http://localhost:8000/app/admin.html
# OpenAPI Documentation:  http://localhost:8000/docs
```

---

## 7. Next Recommended Work (Immediate Roadmap)

1. **Commit Current Changes**: Commit `api/routers/admin.py`, `static/`, `tests/test_admin_review.py`, and `README.md`.
2. **Phase 5 (RAG Document Ingestion)**: Ingest academic syllabi and circulars into `document_chunks` using `vector(384)` embeddings and connect a `search_academic_documents` tool to `api/agent/tools.py`.
3. **Production Containerization**: Add a multi-stage production `Dockerfile` and `docker-compose.yml` for unified deployment.

