"""Tests for POST /api/v1/chat and agent layer with mocked Gemini.

Tests verify:
- Admin gets 403 Forbidden
- Empty and 501-character messages return 422
- Gemini is never called directly (mocked with fake GenerateContentResponse)
- Student scope is strictly applied on the server
- Extra args from the model (branch, semester) are ignored
- A 429 error triggers the fallback (with RETRY_DELAYS=(0,0))
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import errors, types

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from api.agent import agent
from api.deps import ScopedIdentity, get_current_identity
from api.main import app


# ---------------------------------------------------------------------------
# Mock Gemini classes
# ---------------------------------------------------------------------------

class FakeAioModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if not self.responses:
            raise RuntimeError("No more mocked responses configured for Gemini")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


class FakeClient:
    def __init__(self, responses):
        self.aio = SimpleNamespace(models=FakeAioModels(responses))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def student_identity():
    return ScopedIdentity(
        user_id=1,
        role="student",
        student_id=1,
        branch_id=1,
        semester=5,
        section=None,
        batch=None,
    )


@pytest.fixture
def admin_identity():
    return ScopedIdentity(
        user_id=99,
        role="admin",
    )


@pytest.fixture(autouse=True)
def mock_gemini_client(monkeypatch):
    """Ensure Gemini is never called with a real network client in any test."""
    monkeypatch.setattr(agent, "RETRY_DELAYS", (0, 0))
    default_client = FakeClient([
        types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(text="Default mock response")],
                    )
                )
            ]
        )
    ])
    monkeypatch.setattr(agent, "_get_client", lambda: default_client)


# ---------------------------------------------------------------------------
# Tests: Validation & Access Control
# ---------------------------------------------------------------------------

class TestChatValidationAndAccess:
    def test_admin_gets_403(self, client, admin_identity):
        app.dependency_overrides[get_current_identity] = lambda: admin_identity
        try:
            resp = client.post(
                "/api/v1/chat",
                json={"message": "What classes do I have?"},
            )
            assert resp.status_code == 403
            assert "available to students and faculty" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_empty_message_gives_422(self, client, student_identity):
        app.dependency_overrides[get_current_identity] = lambda: student_identity
        try:
            resp = client.post(
                "/api/v1/chat",
                json={"message": ""},
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_501_char_message_gives_422(self, client, student_identity):
        app.dependency_overrides[get_current_identity] = lambda: student_identity
        try:
            long_msg = "x" * 501
            resp = client.post(
                "/api/v1/chat",
                json={"message": long_msg},
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.pop(get_current_identity, None)


# ---------------------------------------------------------------------------
# Tests: Mocked Gemini Interaction & Scoping
# ---------------------------------------------------------------------------

class TestChatMockedGemini:
    def test_student_scope_applied(self, client, student_identity, monkeypatch):
        """Student scope is applied on server: get_classes tool fetches student's timetable."""
        app.dependency_overrides[get_current_identity] = lambda: student_identity
        # 1st call: Gemini asks to call get_classes(query_type="today")
        fc = types.FunctionCall(name="get_classes", args={"query_type": "today"})
        resp1 = types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(function_call=fc)],
                    )
                )
            ]
        )
        # 2nd call: Gemini gives text response after receiving tool output
        resp2 = types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(text="You have Machine Learning at 10:00 AM.")],
                    )
                )
            ]
        )

        fake_client = FakeClient([resp1, resp2])
        monkeypatch.setattr(agent, "_get_client", lambda: fake_client)

        try:
            resp = client.post(
                "/api/v1/chat",
                json={"message": "What classes do I have today?"},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["reply"] == "You have Machine Learning at 10:00 AM."
            assert data["fallback"] is False
            assert len(data["tools_used"]) == 1
            assert data["tools_used"][0]["name"] == "get_classes"
            assert data["tools_used"][0]["args"]["query_type"] == "today"

            # Verify that the tool output sent back to Gemini in round 2 had the student's classes
            assert len(fake_client.aio.models.calls) == 2
            round2_contents = fake_client.aio.models.calls[1]["contents"]
            # The last content in round 2 is user role containing function response
            func_resp_part = round2_contents[-1].parts[0]
            tool_result = func_resp_part.function_response.response["result"]
            assert "classes" in tool_result
            assert "query" in tool_result
            assert tool_result["query"] == "today"
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_extra_args_from_model_ignored(self, client, student_identity, monkeypatch):
        """Model tries to inject branch_id, semester, etc.; server ignores them and uses student scope."""
        app.dependency_overrides[get_current_identity] = lambda: student_identity
        fc = types.FunctionCall(
            name="get_classes",
            args={
                "query_type": "today",
                "branch_id": 999,
                "branch": "CS",
                "semester": 1,
            },
        )
        resp1 = types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(function_call=fc)],
                    )
                )
            ]
        )
        resp2 = types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(text="Here is your timetable.")],
                    )
                )
            ]
        )

        fake_client = FakeClient([resp1, resp2])
        monkeypatch.setattr(agent, "_get_client", lambda: fake_client)

        try:
            resp = client.post(
                "/api/v1/chat",
                json={"message": "Show classes"},
            )
            assert resp.status_code == 200
            # Check tool result in round 2: branch_id=999 was ignored, so no error occurred
            round2_contents = fake_client.aio.models.calls[1]["contents"]
            func_resp_part = round2_contents[-1].parts[0]
            tool_result = func_resp_part.function_response.response["result"]
            assert "classes" in tool_result
            assert "error" not in tool_result
        finally:
            app.dependency_overrides.pop(get_current_identity, None)

    def test_429_triggers_fallback(self, client, student_identity, monkeypatch):
        """A 429 rate-limit error from Gemini immediately triggers the fallback with RETRY_DELAYS=(0,0)."""
        app.dependency_overrides[get_current_identity] = lambda: student_identity
        monkeypatch.setattr(agent, "RETRY_DELAYS", (0, 0))

        rate_limit_err = errors.APIError(429, {"error": {"message": "Resource exhausted"}})
        fake_client = FakeClient([rate_limit_err, rate_limit_err, rate_limit_err])
        monkeypatch.setattr(agent, "_get_client", lambda: fake_client)

        try:
            resp = client.post(
                "/api/v1/chat",
                json={"message": "What is my next class?"},
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["fallback"] is True
            assert "The AI service is busy" in data["reply"]
            assert len(data["tools_used"]) == 1
            assert data["tools_used"][0]["name"] == "get_classes"
            assert data["tools_used"][0]["args"] == {"query_type": "next"}
        finally:
            app.dependency_overrides.pop(get_current_identity, None)
