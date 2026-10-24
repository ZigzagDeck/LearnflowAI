"""Revision uses submitted server-side answers and their authorized source passages."""
from dataclasses import dataclass
from difflib import SequenceMatcher
import uuid

from .chat_service import AuthorizationError
from .config import CHUNKING_PIPELINE_VERSION
from .contracts import (Citation, QuizQuestion, RevisionPassage, RevisionPlan, RevisionRequest,
                        RevisionTarget, RevisionQuizResponse)
from .llm_provider import ProviderError
from .quiz_service import (GroundedQuizService, QuizAttemptError, QuizUnavailableError,
                           _normalize_short_answer, _short_answer_matches, _parse_generated_quiz)
from .resource_store import ResourceStoreError


def _was_correct(question, answer):
    selected = set(answer.get("selected_option_indices", []))
    if question["question_type"] == "short_answer":
        return _short_answer_matches(answer.get("text_answer", ""), question.get("accepted_answers", []))
    return selected == set(question.get("correct_option_indices", []))


@dataclass
class RevisionService:
    quiz: GroundedQuizService

    async def plan(self, quiz_id: str, user_id: str) -> RevisionPlan:
        try:
            attempt = self.quiz.store.get_quiz_attempt(quiz_id, user_id)
            if attempt is None or attempt.status != "submitted":
                raise QuizAttemptError("A submitted quiz belonging to you is required.")
            await self.quiz.authorizer.ensure_allowed(user_id, attempt.source_ids)
            answers = {a["question_id"]: a for a in (attempt.answers or [])}
            missed = [q for q in attempt.questions if not _was_correct(q, answers.get(q["question_id"], {}))]
            targets = []
            for question in missed:
                passages = []
                for raw in question.get("citations", []):
                    citation = Citation.model_validate(raw)
                    if citation.source_id not in attempt.source_ids:
                        continue
                    chunks = self.quiz.store.list_chunks(citation.source_id, CHUNKING_PIPELINE_VERSION)
                    chunk = next((c for c in chunks if c.chunk_id == citation.chunk_id), None)
                    if chunk and chunk.text.strip():
                        passages.append(RevisionPassage(text=chunk.text[:3000], citation=citation))
                targets.append(RevisionTarget(question_id=question["question_id"], question=question["question"],
                                              explanation=question["explanation"], passages=passages))
            return RevisionPlan(quiz_id=quiz_id, missed_count=len(missed), targets=targets)
        except (AuthorizationError, QuizAttemptError):
            raise
        except ResourceStoreError as exc:
            raise QuizUnavailableError("Revision material is temporarily unavailable.") from exc

    async def generate(self, quiz_id: str, request: RevisionRequest, user_id: str) -> RevisionQuizResponse:
        plan = await self.plan(quiz_id, user_id)
        ids = request.question_ids
        if len(set(ids)) != len(ids):
            raise QuizAttemptError("Choose each revision question only once.")
        targets = {t.question_id: t for t in plan.targets}
        if any(qid not in targets or not targets[qid].passages for qid in ids):
            raise QuizAttemptError("Choose missed questions with available reading material.")
        # Read only this owner's attempt; never accept answer keys or source IDs from the client.
        attempt = self.quiz.store.get_quiz_attempt(quiz_id, user_id)
        if attempt is None:
            raise QuizAttemptError("The original quiz is no longer available.")
        excluded = [q["question"] for q in attempt.questions]
        public, stored, source_ids = [], [], []
        for qid in ids:
            target = targets[qid]
            generated = None
            for _ in range(2):
                try:
                    raw = await self.quiz.provider.generate_revision_quiz(
                        [p.text for p in target.passages], target.question, excluded
                    )
                except (ProviderError, AttributeError) as exc:
                    raise QuizUnavailableError("Practice generation is unavailable. Your original result is saved.") from exc
                try:
                    item = _parse_generated_quiz(raw, 1).questions[0]
                    normalized = _normalize_short_answer(item.question)
                    if item.question_type != "single_answer" or any(
                        i < 1 or i > len(target.passages) for i in item.evidence_indices
                    ) or any(SequenceMatcher(None, normalized, _normalize_short_answer(old)).ratio() > .9 for old in excluded):
                        raise QuizUnavailableError("Practice needs a new question supported by your reading.")
                    generated = item
                    break
                except QuizUnavailableError:
                    continue
            if generated is None:
                raise QuizUnavailableError("Could not create a fresh practice question. Please try again.")
            item = generated
            citations = [target.passages[i - 1].citation for i in dict.fromkeys(item.evidence_indices)]
            question_id = uuid.uuid4().hex
            options = [o.strip() for o in item.options]
            public.append(QuizQuestion(question_id=question_id, question=item.question.strip(),
                                       question_type="single_answer", options=options, max_selections=1))
            stored.append({"question_id": question_id, "question": item.question.strip(),
                           "question_type": "single_answer", "options": options,
                           "correct_option_indices": item.correct_option_indices, "accepted_answers": [],
                           "explanation": item.explanation.strip(),
                           "citations": [c.model_dump(mode="json") for c in citations],
                           "revision_of": quiz_id, "revision_question_id": qid})
            source_ids.extend(c.source_id for c in citations)
            excluded.append(item.question)
        # Check source access once more after generation before persisting a practice quiz.
        await self.quiz.authorizer.ensure_allowed(user_id, list(dict.fromkeys(source_ids)))
        quiz_id_new = uuid.uuid4().hex
        try:
            self.quiz.store.create_quiz_attempt(quiz_id_new, user_id, request.session_id,
                                              list(dict.fromkeys(source_ids)), stored)
        except ResourceStoreError as exc:
            raise QuizUnavailableError("Practice quiz could not be saved.") from exc
        return RevisionQuizResponse(quiz_id=quiz_id_new, session_id=request.session_id,
                                    questions=public, parent_quiz_id=quiz_id, revised_question_ids=ids)
