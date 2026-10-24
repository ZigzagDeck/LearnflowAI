import assert from 'node:assert/strict'
import test from 'node:test'
import { isQuizAnswered, unansweredQuizIndices, toggleQuizOption, quizOptionLabel, quizReviewSummary } from '../src/quiz-flow.ts'

const single = { question_id: 'q1', question_type: 'single_answer', question: 'Single', options: ['A', 'B', 'C'], max_selections: 1 }
const multi = { ...single, question_id: 'q2', question_type: 'multiple_answer', options: ['A', 'B', 'C', 'D'], max_selections: 2 }
const short = { ...single, question_id: 'q3', question_type: 'short_answer', options: [], max_selections: 0 }

test('single-answer changes replace the choice; other saved answers stay independent', () => {
  const previous = { indices: [0], text: '' }
  assert.deepEqual(toggleQuizOption(single, previous, 2), { indices: [2], text: '' })
  assert.deepEqual(previous.indices, [0])
})

test('multiple-answer selections are not capped by hidden correct-answer count', () => {
  let answer = { indices: [], text: '' }
  for (const index of [0, 1, 2, 3]) answer = toggleQuizOption(multi, answer, index)
  assert.deepEqual(answer.indices, [0, 1, 2, 3])
  assert.deepEqual(toggleQuizOption(multi, answer, 1).indices, [0, 2, 3])
  assert.deepEqual(toggleQuizOption(multi, answer, 8).indices, [0, 1, 2, 3])
})

test('submission review detects unanswered choices and blank written responses', () => {
  const answers = { q1: { indices: [1], text: '' }, q3: { indices: [], text: '   ' } }
  assert.deepEqual(unansweredQuizIndices([single, multi, short], answers), [1, 2])
  answers.q3.text = 'A written answer'
  assert.deepEqual(unansweredQuizIndices([single, multi, short], answers), [1])
  assert.equal(isQuizAnswered(short, answers.q3), true)
})

test('result labels distinguish selected correct, missed, and wrong answers', () => {
  const result = { question_id: 'q2', question_type: 'multiple_answer', selected_option_indices: [0, 3], correct_option_indices: [0, 2], submitted_text: '', accepted_answers: [], correct: false }
  assert.equal(quizOptionLabel(result, 0), 'Your answer · Correct')
  assert.equal(quizOptionLabel(result, 2), 'Correct answer · Missed')
  assert.equal(quizOptionLabel(result, 3), 'Your answer · Incorrect')
  assert.equal(quizOptionLabel(result, 1), '')
  assert.equal(quizReviewSummary(result), '1 of 2 correct answers selected · 1 missed · 1 incorrect choice.')
})

test('multi-answer summary reflects exact, incomplete, and excessive selections', () => {
  const base = { question_id: 'q2', question_type: 'multiple_answer', selected_option_indices: [0], correct_option_indices: [0, 1, 2], submitted_text: '', accepted_answers: [], correct: false }
  assert.equal(quizReviewSummary(base), '1 of 3 correct answers selected · 2 missed.')
  assert.equal(quizReviewSummary({ ...base, selected_option_indices: [0, 1, 2], correct: true }), 'All 3 correct answers selected.')
  assert.equal(quizReviewSummary({ ...base, selected_option_indices: [0, 1, 2, 3] }), '3 of 3 correct answers selected · 1 incorrect choice.')
})
