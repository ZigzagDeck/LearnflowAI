"""Tests for the AI Mock Interview feature (service and HTTP API)."""

import json
import pytest
from fastapi.testclient import TestClient

import backend.main as backend_main
from backend.auth import create_session, hash_password
from backend.interview_service import (
    InterviewStateError,
    InterviewUnavailableError,
    MockInterviewService,
)
from backend.resource_store import ResourceStore


class FakeInterviewModelProvider:
    """Deterministic mock provider simulating an AI interviewer and evaluator."""

    def __init__(self):
        self.turns_called = 0
        self.reports_called = 0

    async def interview_turn(
        self,
        system: str,
        history: list[dict],
        user_message: str,
        max_tokens: int = 600,
    ) -> str:
        self.turns_called += 1
        if user_message == "[START_INTERVIEW]":
            return (
                "Hello! Welcome to your mock interview for this position. "
                "Let's get started with Question 1: Can you describe your experience "
                "with distributed systems and asynchronous workflows?"
            )
        return (
            f"Thank you for that response. Moving on to Question {self.turns_called}: "
            "How do you handle edge cases and data consistency in production environments?"
        )

    async def generate_report(
        self,
        system: str,
        history: list[dict],
        max_tokens: int = 2000,
    ) -> str:
        self.reports_called += 1
        return json.dumps({
            "overall_score": 8,
            "summary": "Strong candidate demonstration of software engineering principles and clear communication.",
            "strengths": [
                "Clear architectural explanation",
                "Strong grasp of concurrency and race condition prevention",
            ],
            "areas_for_improvement": [
                "Could provide more concrete latency metrics",
                "Elaborate more on automated test coverage",
            ],
            "recommendations": [
                "Practice using the STAR method for behavioral anecdotes",
                "Review distributed transaction patterns",
            ],
            "questions": [
                {
                    "question": "Can you describe your experience with distributed systems?",
                    "user_answer": "I built microservices using message queues and idempotent handlers.",
                    "score": 8,
                    "feedback": "Well-structured response covering key decoupling principles.",
                    "ideal_answer_hint": "Mention specific partition tolerance and queue dead-lettering.",
                }
            ],
        })


@pytest.fixture
def test_user(tmp_path):
    store = ResourceStore(tmp_path / "test.db")
    p_hash, p_salt = hash_password("Secret123!")
    user = store.create_user(
        email="candidate@example.com",
        display_name="Test Candidate",
        password_hash=p_hash,
        password_salt=p_salt,
        role="user",
    )
    token, _ = create_session(store, user)
    return store, user, token


@pytest.mark.anyio
async def test_interview_service_lifecycle(tmp_path):
    store = ResourceStore(tmp_path / "test.db")
    provider = FakeInterviewModelProvider()
    service = MockInterviewService(provider=provider, store=store)

    # 1. Start interview
    start_res = await service.start(
        session_id="session-1",
        user_id="user-1",
        job_role="Senior Backend Engineer",
        job_description="Python, FastAPI, distributed databases",
        resume_text="5 years experience in backend engineering",
        material_context="",
        question_count=3,
        interview_type="technical",
    )
    assert start_res["status"] == "active"
    assert "Question 1" in start_res["message"]
    interview_id = start_res["interview_id"]

    # 2. Respond to question 1
    reply_1 = await service.respond(
        interview_id=interview_id,
        user_id="user-1",
        user_message="I have worked with distributed queues and event sourcing.",
    )
    assert reply_1["status"] in ("active", "completed")
    assert "Moving on" in reply_1["message"]

    # 3. Retrieve session details
    session = service.get_session(interview_id, "user-1")
    assert session is not None
    assert session["job_role"] == "Senior Backend Engineer"
    assert len(session["history"]) >= 3

    # 4. Generate report
    report = await service.get_report(interview_id, "user-1")
    assert report["overall_score"] == 8
    assert len(report["strengths"]) == 2
    assert len(report["questions"]) == 1

    # 5. List sessions
    sessions = service.list_sessions("user-1")
    assert len(sessions) == 1
    assert sessions[0]["interview_id"] == interview_id

    # 6. Delete session
    service.delete_session(interview_id, "user-1")
    assert service.get_session(interview_id, "user-1") is None


def test_interview_api_routes(test_user, monkeypatch):
    store, user, token = test_user
    provider = FakeInterviewModelProvider()
    service = MockInterviewService(provider=provider, store=store)

    # Wire into backend_main app state
    monkeypatch.setattr(backend_main, "get_resource_store", lambda: store)
    backend_main.app.state.resource_store = store
    backend_main.app.state.interview_service = service

    with TestClient(backend_main.app) as client:
        headers = {"Authorization": f"Bearer {token}"}

        # Unauthorized check
        anon_res = client.post("/interview/start", json={
            "session_id": "test-session",
            "job_role": "Data Scientist",
            "question_count": 3,
        })
        assert anon_res.status_code == 401

        # Authorized start
        start_res = client.post(
            "/interview/start",
            headers=headers,
            json={
                "session_id": "test-session",
                "job_role": "Data Scientist",
                "question_count": 3,
                "interview_type": "technical",
            },
        )
        assert start_res.status_code == 200
        data = start_res.json()
        interview_id = data["interview_id"]
        assert "Question 1" in data["message"]

        # Respond
        resp_res = client.post(
            f"/interview/{interview_id}/respond",
            headers=headers,
            json={"message": "I develop models using PyTorch and scikit-learn."},
        )
        assert resp_res.status_code == 200
        assert "message" in resp_res.json()

        # Get details
        detail_res = client.get(f"/interview/{interview_id}", headers=headers)
        assert detail_res.status_code == 200
        assert detail_res.json()["job_role"] == "Data Scientist"

        # Conclude and get report
        report_res = client.post(f"/interview/{interview_id}/report", headers=headers)
        assert report_res.status_code == 200
        assert "report" in report_res.json()
        assert report_res.json()["report"]["overall_score"] == 8

        # List history
        hist_res = client.get("/interview/history", headers=headers)
        assert hist_res.status_code == 200
        assert len(hist_res.json()["sessions"]) == 1

        # Delete
        del_res = client.delete(f"/interview/{interview_id}", headers=headers)
        assert del_res.status_code == 200
        assert del_res.json()["deleted"] is True
