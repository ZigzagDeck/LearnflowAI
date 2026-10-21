"""AI Mock Interview service with conversational interviewer and final report.

The interviewer is aware of: (1) a job role / job description, (2) optional
resume text, and (3) optionally selected learning materials from the user's
library. It asks one question at a time, waits for the user's response, then
continues. When the session ends the evaluator agent produces a structured
report with per-question scores, feedback, and overall recommendations.
"""

from dataclasses import dataclass
import asyncio
import json
import uuid
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .llm_provider import BedrockProvider, ProviderError
from .resource_store import ResourceStore, ResourceStoreError


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------

class InterviewUnavailableError(RuntimeError):
    """A required interview dependency is unavailable."""


class InterviewStateError(ValueError):
    """The interview request is invalid for its current state."""


class _QuestionFeedback(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question: str
    user_answer: str
    score: int = Field(ge=0, le=10)
    feedback: str
    ideal_answer_hint: str = ""


class _InterviewReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    overall_score: int = Field(ge=0, le=10)
    summary: str
    strengths: list[str] = Field(default_factory=list)
    areas_for_improvement: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    questions: list[_QuestionFeedback] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

class InterviewModelProvider(Protocol):
    async def interview_turn(
        self,
        system: str,
        history: list[dict],
        user_message: str,
        max_tokens: int,
    ) -> str: ...

    async def generate_report(
        self,
        system: str,
        history: list[dict],
        max_tokens: int,
    ) -> str: ...


# ---------------------------------------------------------------------------
# Bedrock adapter implementing InterviewModelProvider
# ---------------------------------------------------------------------------

@dataclass
class BedrockInterviewProvider:
    """Thin adapter that routes interview requests through BedrockProvider."""

    bedrock: BedrockProvider

    async def interview_turn(
        self,
        system: str,
        history: list[dict],
        user_message: str,
        max_tokens: int = 600,
    ) -> str:
        """Send one conversational turn and return the assistant reply."""
        messages = history + [{"role": "user", "content": user_message}]
        return await asyncio.to_thread(
            self.bedrock._complete_sync, system, _format_history(messages), max_tokens
        )

    async def generate_report(
        self,
        system: str,
        history: list[dict],
        max_tokens: int = 2000,
    ) -> str:
        return await asyncio.to_thread(
            self.bedrock._complete_sync, system, _format_history(history), max_tokens
        )


def _format_history(messages: list[dict]) -> str:
    """Flatten message history into a single prompt block."""
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        label = "Interviewer" if role == "assistant" else "Candidate"
        parts.append(f"{label}: {content}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

@dataclass
class MockInterviewService:
    provider: InterviewModelProvider
    store: ResourceStore

    def _build_system_prompt(
        self,
        job_role: str,
        job_description: str,
        resume_text: str,
        material_context: str,
        question_count: int,
        interview_type: str,
    ) -> str:
        parts = [
            f"You are an expert technical interviewer for the role of '{job_role}'.",
            "Your goal is to assess the candidate's skills through a focused interview.",
            f"You will ask exactly {question_count} questions, one at a time.",
            "After each candidate response, acknowledge briefly and ask the next question.",
            "Do NOT reveal scores or evaluation during the interview.",
            "Keep questions relevant to the role and the candidate's background.",
        ]
        if interview_type == "technical":
            parts.append("Focus on technical skills, problem-solving, and domain expertise.")
        elif interview_type == "behavioral":
            parts.append("Focus on behavioral questions using the STAR method (Situation, Task, Action, Result).")
        elif interview_type == "hr":
            parts.append("Focus on motivation, culture fit, teamwork, and career goals.")
        else:
            parts.append("Mix technical, behavioral, and motivational questions.")

        if job_description:
            parts.append(f"\nJob Description:\n{job_description[:2000]}")
        if resume_text:
            parts.append(f"\nCandidate Resume/Background:\n{resume_text[:2000]}")
        if material_context:
            parts.append(f"\nAdditional context from the candidate's learning materials:\n{material_context[:1500]}")

        parts.append(
            "\nIMPORTANT: Start by introducing yourself warmly, then ask question 1. "
            "Number each question clearly (e.g., 'Question 1:')."
        )
        return "\n".join(parts)

    def _build_report_system(
        self,
        job_role: str,
        question_count: int,
    ) -> str:
        return (
            f"You are an expert interview evaluator for the role of '{job_role}'. "
            "Analyze the complete interview transcript below and produce a detailed evaluation report. "
            "Return ONLY valid JSON (no markdown fences, no commentary) in this exact shape:\n"
            '{"overall_score": <0-10>, "summary": "...", '
            '"strengths": ["...", ...], "areas_for_improvement": ["...", ...], '
            '"recommendations": ["...", ...], '
            '"questions": [{"question": "...", "user_answer": "...", '
            '"score": <0-10>, "feedback": "...", "ideal_answer_hint": "..."}, ...]}\n'
            f"The questions array must have exactly {question_count} entries, one per interview question asked."
        )

    async def start(
        self,
        session_id: str,
        user_id: str,
        job_role: str,
        job_description: str,
        resume_text: str,
        material_context: str,
        question_count: int,
        interview_type: str,
    ) -> dict:
        """Create a new interview session and get the opening message."""
        interview_id = uuid.uuid4().hex
        system = self._build_system_prompt(
            job_role, job_description, resume_text,
            material_context, question_count, interview_type,
        )
        # First message from the interviewer
        try:
            opening = await self.provider.interview_turn(
                system=system,
                history=[],
                user_message="[START_INTERVIEW]",
                max_tokens=500,
            )
        except ProviderError as exc:
            raise InterviewUnavailableError("The AI interviewer is currently unavailable.") from exc

        history = [
            {"role": "user", "content": "[START_INTERVIEW]"},
            {"role": "assistant", "content": opening},
        ]
        try:
            self.store.save_interview_session(
                interview_id=interview_id,
                user_id=user_id,
                session_id=session_id,
                job_role=job_role,
                job_description=job_description,
                resume_text=resume_text,
                material_context=material_context,
                question_count=question_count,
                interview_type=interview_type,
                system_prompt=system,
                history=history,
                status="active",
            )
        except ResourceStoreError as exc:
            raise InterviewUnavailableError("Interview session could not be saved.") from exc

        return {
            "interview_id": interview_id,
            "message": opening,
            "status": "active",
            "questions_asked": 0,
            "question_count": question_count,
        }

    async def respond(
        self,
        interview_id: str,
        user_id: str,
        user_message: str,
    ) -> dict:
        """Process the candidate's response and return the next interviewer message."""
        try:
            session = self.store.get_interview_session(interview_id, user_id)
        except ResourceStoreError as exc:
            raise InterviewUnavailableError("Interview data is unavailable.") from exc

        if session is None:
            raise InterviewStateError("Interview session not found.")
        if session["status"] != "active":
            raise InterviewStateError("This interview has already ended.")

        history: list[dict] = session["history"]
        system: str = session["system_prompt"]
        question_count: int = session["question_count"]

        # Count how many questions the interviewer has asked so far
        import re
        questions_asked = sum(
            1 for msg in history
            if msg["role"] == "assistant" and re.search(r"\bquestion\s*\d+\b", msg["content"], re.IGNORECASE)
        )
        if questions_asked == 0:
            # Fallback: count assistant turns
            questions_asked = max(1, sum(1 for msg in history if msg["role"] == "assistant"))

        # Determine if we should wrap up
        should_end = questions_asked >= question_count
        if should_end:
            end_note = (
                " Please wrap up the interview now with a brief, warm closing statement thanking the candidate. "
                "Do NOT ask any more questions."
            )
        else:
            end_note = ""

        try:
            reply = await self.provider.interview_turn(
                system=system + end_note,
                history=history,
                user_message=user_message,
                max_tokens=450,
            )
        except ProviderError as exc:
            raise InterviewUnavailableError("The AI interviewer is currently unavailable.") from exc

        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": reply})

        new_questions_asked = sum(
            1 for msg in history
            if msg["role"] == "assistant" and re.search(r"\bquestion\s*\d+\b", msg["content"], re.IGNORECASE)
        )
        if new_questions_asked == 0:
            new_questions_asked = max(1, sum(1 for msg in history if msg["role"] == "assistant"))
        new_status = "completed" if should_end else "active"

        try:
            self.store.update_interview_session(
                interview_id=interview_id,
                user_id=user_id,
                history=history,
                status=new_status,
            )
        except ResourceStoreError as exc:
            raise InterviewUnavailableError("Interview update could not be saved.") from exc

        return {
            "interview_id": interview_id,
            "message": reply,
            "status": new_status,
            "questions_asked": new_questions_asked,
            "question_count": question_count,
        }

    async def get_report(self, interview_id: str, user_id: str) -> dict:
        """Generate and return a structured evaluation report."""
        try:
            session = self.store.get_interview_session(interview_id, user_id)
        except ResourceStoreError as exc:
            raise InterviewUnavailableError("Interview data is unavailable.") from exc

        if session is None:
            raise InterviewStateError("Interview session not found.")
        # Allow concluding active sessions as long as there is conversation history
        history: list[dict] = session["history"]
        has_answers = any(m.get("role") == "user" and m.get("content") != "[START_INTERVIEW]" for m in history)
        if not has_answers and session["status"] == "active":
            raise InterviewStateError("Please answer at least one question before concluding the interview.")

        # Return cached report if already generated
        if session.get("report"):
            return session["report"]

        report_system = self._build_report_system(
            session["job_role"], session["question_count"]
        )

        try:
            raw = await self.provider.generate_report(
                system=report_system,
                history=history,
                max_tokens=2500,
            )
        except ProviderError as exc:
            raise InterviewUnavailableError("Report generation is currently unavailable.") from exc

        # Parse the JSON report
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise InterviewUnavailableError("Report generation returned invalid data.")
        try:
            report_obj = _InterviewReport.model_validate(json.loads(raw[start: end + 1]))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise InterviewUnavailableError("Report generation returned an invalid structure.") from exc

        report = report_obj.model_dump()
        try:
            self.store.update_interview_session(
                interview_id=interview_id,
                user_id=user_id,
                history=history,
                status="reported",
                report=report,
            )
        except ResourceStoreError as exc:
            raise InterviewUnavailableError("Report could not be saved.") from exc

        return report

    def get_session(self, interview_id: str, user_id: str) -> dict | None:
        """Fetch full interview session details for a user."""
        try:
            return self.store.get_interview_session(interview_id, user_id)
        except ResourceStoreError as exc:
            raise InterviewUnavailableError("Interview session could not be fetched.") from exc

    def list_sessions(self, user_id: str) -> list[dict]:
        """Return all interview sessions for this user."""
        try:
            return self.store.list_interview_sessions(user_id)
        except ResourceStoreError as exc:
            raise InterviewUnavailableError("Interview history is unavailable.") from exc

    def delete_session(self, interview_id: str, user_id: str) -> None:
        """Delete an interview session."""
        try:
            self.store.delete_interview_session(interview_id, user_id)
        except ResourceStoreError as exc:
            raise InterviewUnavailableError("Interview session could not be deleted.") from exc

