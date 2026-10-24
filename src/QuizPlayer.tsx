import { useEffect, useRef, useState, type ReactNode } from 'react'
import { isQuizAnswered, quizOptionLabel, quizReviewSummary, toggleQuizOption, unansweredQuizIndices } from './quiz-flow'
import type { QuizAnswers, QuizQuestion, QuizReview } from './quiz-flow'

type Result = { score: number; total: number; questions: QuizReview[] }

export default function QuizPlayer({ questions, answers, result, busy, onAnswer, onSubmit, renderExplanation, resultFooter }: {
  questions: QuizQuestion[]
  answers: QuizAnswers
  result: Result | null
  busy: boolean
  onAnswer: (questionId: string, answer: QuizAnswers[string]) => void
  onSubmit: () => void
  resultFooter?: ReactNode
  renderExplanation: (questionId: string) => ReactNode
}) {
  const [activeIndex, setActiveIndex] = useState(0)
  const [confirming, setConfirming] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const heading = useRef<HTMLHeadingElement>(null)
  const question = questions[activeIndex]
  const missing = unansweredQuizIndices(questions, answers)
  const answeredCount = questions.length - missing.length
  const review = result?.questions.find((item) => item.question_id === question?.question_id)

  useEffect(() => {
    heading.current?.focus({ preventScroll: true })
    heading.current?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex, confirming, reviewing, result])

  const goTo = (index: number) => {
    if (busy || index < 0 || index >= questions.length) return
    setActiveIndex(index)
    setConfirming(false)
  }

  if (!question) return <p role="alert">This quiz has no questions. Please create a new quiz.</p>

  if (result && !reviewing) return <section className="quiz-step-result">
    <div className="quiz-score"><strong>{result.score}/{result.total}</strong><span>{result.score === result.total ? 'Perfect score' : 'Quiz complete'}</span></div>
    <h3 ref={heading} tabIndex={-1}>Your result</h3>
    <p>{result.score} of {result.total} questions correct.</p>
    <button className="quiz-submit" type="button" onClick={() => { setActiveIndex(0); setConfirming(false); setReviewing(true) }}>Review answers</button>
    {resultFooter}
  </section>

  return <section className="quiz-step-player" aria-busy={busy}>
    <div className="quiz-step-top">
      <p className="quiz-number">{confirming && !result ? `${answeredCount} OF ${questions.length} ANSWERED` : <>{result ? 'REVIEW' : 'QUESTION'} {activeIndex + 1} OF {questions.length}{!result && ` · ${answeredCount} answered`}</>}</p>
      {result && <button className="secondary-button" type="button" onClick={() => setReviewing(false)}>Back to result</button>}
    </div>
    <nav className="quiz-step-navigator" aria-label={result ? 'Review questions' : 'Quiz questions'}>
      {questions.map((item, index) => {
        const itemResult = result?.questions.find((entry) => entry.question_id === item.question_id)
        const answered = isQuizAnswered(item, answers[item.question_id])
        const status = result ? itemResult?.correct ? 'correct' : 'incorrect' : answered ? 'answered' : 'not answered'
        return <button className="secondary-button quiz-step-number" key={item.question_id} type="button"
          aria-current={!confirming && index === activeIndex ? 'step' : undefined}
          aria-label={`Question ${index + 1}, ${status}`} disabled={busy} onClick={() => goTo(index)}>
          {index + 1}{result ? itemResult?.correct ? ' ✓' : ' ×' : answered ? ' ✓' : ''}
        </button>
      })}
    </nav>
    {confirming && !result ? <section className="quiz-question quiz-submit-check">
      <h3 ref={heading} tabIndex={-1}>Review &amp; submit</h3>
      <p role="status">{missing.length ? `${missing.length} ${missing.length === 1 ? 'question needs' : 'questions need'} an answer. Select a number above to finish.` : `All ${questions.length} ${questions.length === 1 ? 'question' : 'questions'} answered.`}</p>
      <div className="quiz-step-actions">
        <button className="secondary-button" type="button" disabled={busy} onClick={() => goTo(missing[0] ?? activeIndex)}>{missing.length ? 'Go to unanswered' : 'Back to questions'}</button>
        <button className="quiz-submit" type="button" disabled={busy || missing.length > 0} onClick={onSubmit}>{busy ? 'Submitting…' : 'Submit quiz'}</button>
      </div>
    </section> : <>
      <article className="quiz-question" key={question.question_id}>
        <h3 ref={heading} tabIndex={-1}>{question.question}</h3>
        <p className="question-type">{question.question_type === 'single_answer' ? 'Choose one' : question.question_type === 'multiple_answer' ? 'Select all correct answers' : 'Write a short answer'}</p>
        {question.question_type === 'short_answer' ? <>
          {result ? <div className="quiz-answer-text"><span>Your answer</span><p>{review?.submitted_text || 'No answer'}</p></div> : <textarea className="short-answer" aria-label="Your answer" value={answers[question.question_id]?.text || ''}
            onChange={(event) => onAnswer(question.question_id, { indices: [], text: event.target.value })}
            placeholder="Type your answer…" maxLength={2000} disabled={busy} />}
        </> : <div className="quiz-options">{question.options.map((option, optionIndex) => {
          const selected = review ? review.selected_option_indices.includes(optionIndex) : answers[question.question_id]?.indices.includes(optionIndex) || false
          const optionState = review ? review.correct_option_indices.includes(optionIndex) ? 'correct' : selected ? 'incorrect' : '' : ''
          const label = review ? quizOptionLabel(review, optionIndex) : ''
          return <label className={`quiz-option ${optionState}`} key={optionIndex}>
            <input type={question.question_type === 'single_answer' ? 'radio' : 'checkbox'} name={question.question_id}
              checked={selected} disabled={Boolean(result) || busy}
              onChange={() => onAnswer(question.question_id, toggleQuizOption(question, answers[question.question_id], optionIndex))} />
            <span className="quiz-option-copy"><span>{option}</span>{label && <small className="quiz-answer-label">{label}</small>}</span>
          </label>
        })}</div>}
        {review && <div className={`quiz-explanation ${review.correct ? 'correct' : 'incorrect'}`}>
          <p>{quizReviewSummary(review)}</p>
          {renderExplanation(question.question_id)}
        </div>}
      </article>
      <div className="quiz-step-actions">
        <button className="secondary-button" type="button" disabled={busy || activeIndex === 0} onClick={() => goTo(activeIndex - 1)}>Previous</button>
        {activeIndex < questions.length - 1 ? <button className="quiz-submit" type="button" disabled={busy} onClick={() => goTo(activeIndex + 1)}>Next</button>
          : result ? <button className="quiz-submit" type="button" onClick={() => setReviewing(false)}>Back to result</button>
            : <button className="quiz-submit" type="button" disabled={busy} onClick={() => setConfirming(true)}>Review &amp; submit</button>}
      </div>
    </>}
  </section>
}
