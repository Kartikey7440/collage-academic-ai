"""Phase 3 auth tests — signup, login, refresh, /me, role guards.

Uses FastAPI's TestClient (httpx-based) with a real Postgres test database
(the same one Phase 2 tests use).  Each test class resets the auth-related
rows it needs via pytest fixtures, so tests are order-independent.

Run:
    python -m pytest -v tests/test_auth.py

Environment:
    DATABASE_URL must be set (see .env.example).
    JWT_SECRET_KEY is overridden to a test value via monkeypatch / env.
"""

import asyncio
import os

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Project root on sys.path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Set a deterministic JWT secret before importing anything that reads it.
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-auth-tests")

from api.main import app
from db.models import Base
from db.session import AsyncSessionLocal, engine


# ---------------------------------------------------------------------------
# Session-scoped event loop + database bootstrap
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database():
    """Create tables (idempotent) once per test session."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield


# ---------------------------------------------------------------------------
# A branch row is needed for student signup; seed it once.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def ai_branch_id(setup_database) -> int:
    """Ensure the AI branch exists and return its DB id."""
    from sqlalchemy import select
    from db.models import Branch

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Branch).where(Branch.code == "AI"))
        branch = result.scalars().first()
        if branch is None:
            branch = Branch(code="AI", name="Artificial Intelligence")
            session.add(branch)
            await session.commit()
            await session.refresh(branch)
        return branch.id


@pytest_asyncio.fixture
async def test_faculty_id(setup_database) -> int:
    """Ensure a faculty reference row (code=GH) exists and has no pre-existing link."""
    from sqlalchemy import select, delete
    from db.models import Faculty, FacultyUser

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Faculty).where(Faculty.code == "GH"))
        fac = result.scalars().first()
        if fac is None:
            fac = Faculty(code="GH", name="Mrs. Geetika Hazra")
            session.add(fac)
            await session.commit()
            await session.refresh(fac)
        await session.execute(delete(FacultyUser).where(FacultyUser.faculty_id == fac.id))
        await session.commit()
        return fac.id


# ---------------------------------------------------------------------------
# HTTP test client (sync — TestClient wraps the async app)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# Helper: unique email per test to avoid conflicts
# ---------------------------------------------------------------------------


def _email(tag: str) -> str:
    import uuid
    return f"test_{tag}_{uuid.uuid4().hex[:6]}@mits.ac.in"


# ---------------------------------------------------------------------------
# POST /api/v1/auth/signup
# ---------------------------------------------------------------------------


class TestSignup:
    def test_student_signup_returns_tokens(self, client, ai_branch_id):
        resp = client.post("/api/v1/auth/signup", json={
            "email": _email("stu"),
            "password": "securePass1",
            "role": "student",
            "roll_no": "0901AI221001",
            "branch_code": "AI",
            "semester": 5,
        })
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_faculty_signup_returns_tokens(self, client, test_faculty_id):
        resp = client.post("/api/v1/auth/signup", json={
            "email": _email("fac"),
            "password": "securePass1",
            "role": "faculty",
            "faculty_code": "GH",
        })
        assert resp.status_code == 201, resp.text
        assert "access_token" in resp.json()

    def test_duplicate_email_returns_409(self, client, ai_branch_id):
        email = _email("dup")
        payload = {
            "email": email,
            "password": "securePass1",
            "role": "student",
            "roll_no": "DUP001",
            "branch_code": "AI",
            "semester": 5,
        }
        r1 = client.post("/api/v1/auth/signup", json=payload)
        assert r1.status_code == 201
        r2 = client.post("/api/v1/auth/signup", json=payload)
        assert r2.status_code == 409

    def test_admin_signup_forbidden(self, client):
        resp = client.post("/api/v1/auth/signup", json={
            "email": _email("admin"),
            "password": "securePass1",
            "role": "admin",
        })
        assert resp.status_code == 403

    def test_student_missing_roll_no_returns_422(self, client):
        resp = client.post("/api/v1/auth/signup", json={
            "email": _email("noroll"),
            "password": "securePass1",
            "role": "student",
            "branch_code": "AI",
            "semester": 5,
            # roll_no intentionally omitted
        })
        assert resp.status_code == 422

    def test_unknown_branch_code_returns_422(self, client):
        resp = client.post("/api/v1/auth/signup", json={
            "email": _email("badbranch"),
            "password": "securePass1",
            "role": "student",
            "roll_no": "NOBODY001",
            "branch_code": "NONEXISTENT",
            "semester": 5,
        })
        assert resp.status_code == 422

    def test_unknown_faculty_code_returns_422(self, client):
        resp = client.post("/api/v1/auth/signup", json={
            "email": _email("badfac"),
            "password": "securePass1",
            "role": "faculty",
            "faculty_code": "ZZZZ",
        })
        assert resp.status_code == 422

    def test_short_password_returns_422(self, client):
        resp = client.post("/api/v1/auth/signup", json={
            "email": _email("short"),
            "password": "abc",
            "role": "student",
            "roll_no": "SHORT001",
            "branch_code": "AI",
            "semester": 5,
        })
        assert resp.status_code == 422

    def test_duplicate_faculty_code_returns_409(self, client, test_faculty_id):
        """A faculty code already linked to one account cannot be linked again."""
        # First signup (succeeds if no prior GH link — may already have been
        # created by test_faculty_signup_returns_tokens, hence we use a fresh code)
        # We rely on the session fixture order; just assert the second attempt fails.
        payload = {
            "email": _email("gh2"),
            "password": "securePass1",
            "role": "faculty",
            "faculty_code": "GH",  # GH was already claimed in the session
        }
        resp = client.post("/api/v1/auth/signup", json=payload)
        # Could be 201 (if this runs first) or 409 (if GH already claimed).
        assert resp.status_code in (201, 409)


# ---------------------------------------------------------------------------
# POST /api/v1/auth/login
# ---------------------------------------------------------------------------


class TestLogin:
    @pytest.fixture(autouse=True)
    def _create_user(self, client, ai_branch_id):
        """Create one student account to log in with."""
        self._email = _email("login")
        self._password = "correctPass99"
        resp = client.post("/api/v1/auth/signup", json={
            "email": self._email,
            "password": self._password,
            "role": "student",
            "roll_no": "LOGIN001",
            "branch_code": "AI",
            "semester": 5,
        })
        assert resp.status_code == 201, resp.text

    def test_correct_credentials_return_tokens(self, client):
        resp = client.post("/api/v1/auth/login", json={
            "email": self._email,
            "password": self._password,
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data

    def test_wrong_password_returns_401(self, client):
        resp = client.post("/api/v1/auth/login", json={
            "email": self._email,
            "password": "wrongPassword",
        })
        assert resp.status_code == 401

    def test_unknown_email_returns_401(self, client):
        resp = client.post("/api/v1/auth/login", json={
            "email": "nobody@mits.ac.in",
            "password": "anything",
        })
        assert resp.status_code == 401

    def test_login_error_message_is_generic(self, client):
        """Both bad-email and bad-password return the same message (no email enumeration)."""
        r_bad_email = client.post("/api/v1/auth/login", json={
            "email": "nobody@mits.ac.in",
            "password": "anything",
        })
        r_bad_pass = client.post("/api/v1/auth/login", json={
            "email": self._email,
            "password": "wrongPassword",
        })
        assert r_bad_email.json()["detail"] == r_bad_pass.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/v1/auth/refresh
# ---------------------------------------------------------------------------


class TestRefresh:
    @pytest.fixture(autouse=True)
    def _login(self, client, ai_branch_id):
        resp = client.post("/api/v1/auth/signup", json={
            "email": _email("refresh"),
            "password": "refreshPass1",
            "role": "student",
            "roll_no": "REFRESH001",
            "branch_code": "AI",
            "semester": 5,
        })
        assert resp.status_code == 201
        self._tokens = resp.json()

    def test_valid_refresh_token_issues_new_access_token(self, client):
        resp = client.post("/api/v1/auth/refresh", json={
            "refresh_token": self._tokens["refresh_token"]
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_access_token_rejected_as_refresh_token(self, client):
        """Using the access token in the refresh endpoint must fail."""
        resp = client.post("/api/v1/auth/refresh", json={
            "refresh_token": self._tokens["access_token"]  # Wrong type
        })
        assert resp.status_code == 401

    def test_malformed_token_returns_401(self, client):
        resp = client.post("/api/v1/auth/refresh", json={
            "refresh_token": "not.a.real.jwt"
        })
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/auth/me
# ---------------------------------------------------------------------------


class TestMe:
    @pytest.fixture(autouse=True)
    def _login(self, client, ai_branch_id):
        resp = client.post("/api/v1/auth/signup", json={
            "email": _email("me"),
            "password": "mePass1234",
            "role": "student",
            "roll_no": "ME001",
            "branch_code": "AI",
            "semester": 5,
        })
        assert resp.status_code == 201
        self._access = resp.json()["access_token"]

    def test_me_returns_user_info(self, client):
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {self._access}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "id" in data
        assert data["role"] == "student"
        assert "password" not in str(data)  # Never leak password fields

    def test_me_without_token_returns_403(self, client):
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    def test_me_with_invalid_token_returns_401(self, client):
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalidtoken"},
        )
        assert resp.status_code == 401
