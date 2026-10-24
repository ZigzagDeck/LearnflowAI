# Local Revision Coach

A submitted quiz can open a compact revision card. Reading uses saved citations and current authorized chunks without model calls. Students can select up to three missed questions, read the excerpt and open its source, then explicitly request one new single-answer question per selected target.

The server loads the original attempt for the current owner, recomputes missed answers using existing grading rules, and rechecks source access. No answer keys or source IDs for generation come from the client. Practice uses only the missed questions' exact cited chunks (up to 3,000 characters per passage), asks for a different application/reasoning question and rejects invalid references, wrong question types and near-identical stems. Invalid output is regenerated once; provider failures are not retried. The existing provider quota applies; generation can use up to six provider calls for three selected targets including retries.

Practice stores parent and target question IDs in the existing questions JSON; no schema migration is needed. Existing submit/scoring endpoints grade the new practice. The original result remains intact, with a return button. The fresh score is shown separately from the original full-quiz score. Neither score establishes mastery or semantic understanding.

Endpoints:
- GET /quiz/{id}/revision: owned submitted quiz's missed questions and reading passages.
- POST /quiz/{id}/revision: session_id and 1-3 distinct missed question_ids; returns a new quiz with parent_quiz_id and revised_question_ids. Standard authentication applies.

Limitations: this is question-level revision, not an inferred diagnostic topic model. Correct source references do not prove model-generated facts are correct. Existing short-answer matching limitations still affect which questions are considered missed. Deleted or inaccessible sources cannot be used. Current quiz/player UI state is not restored after a browser refresh, matching the existing quiz behavior; attempts and revision links remain stored in SQLite. Provider usage is not guaranteed free.

