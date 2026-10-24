export type QuizQuestion = {
  question_id: string
  question: string
  question_type: 'single_answer' | 'multiple_answer' | 'short_answer'
  options: string[]
  max_selections: number
}

export type QuizAnswer = { indices: number[]; text: string }
export type QuizAnswers = Record<string, QuizAnswer>
export type QuizReview = {
  question_id: string
  question_type: QuizQuestion['question_type']
  selected_option_indices: number[]
  correct_option_indices: number[]
  submitted_text: string
  accepted_answers: string[]
  correct: boolean
}

export function isQuizAnswered(question: QuizQuestion, answer?: QuizAnswer): boolean {
  return question.question_type === 'short_answer' ? Boolean(answer?.text.trim()) : Boolean(answer?.indices.length)
}

export function unansweredQuizIndices(questions: QuizQuestion[], answers: QuizAnswers): number[] {
  return questions.flatMap((question, index) => isQuizAnswered(question, answers[question.question_id]) ? [] : [index])
}

export function toggleQuizOption(question: QuizQuestion, answer: QuizAnswer | undefined, optionIndex: number): QuizAnswer {
  const previous = answer?.indices || []
  if (!Number.isInteger(optionIndex) || optionIndex < 0 || optionIndex >= question.options.length || question.question_type === 'short_answer') {
    return answer || { indices: [], text: '' }
  }
  const indices = question.question_type === 'single_answer' ? [optionIndex]
    : previous.includes(optionIndex) ? previous.filter((index) => index !== optionIndex) : [...previous, optionIndex]
  return { indices, text: '' }
}

export function quizOptionLabel(result: QuizReview, index: number): string {
  const selected = result.selected_option_indices.includes(index)
  const correct = result.correct_option_indices.includes(index)
  if (correct) return selected ? 'Your answer · Correct' : 'Correct answer · Missed'
  return selected ? 'Your answer · Incorrect' : ''
}

export function quizReviewSummary(result: QuizReview): string {
  if (result.question_type !== 'multiple_answer') return result.correct ? 'Correct' : 'Incorrect'
  const selectedCorrect = result.selected_option_indices.filter((index) => result.correct_option_indices.includes(index)).length
  const missed = result.correct_option_indices.length - selectedCorrect
  const incorrect = result.selected_option_indices.length - selectedCorrect
  if (result.correct) return `All ${result.correct_option_indices.length} correct answers selected.`
  const parts = [`${selectedCorrect} of ${result.correct_option_indices.length} correct answers selected`]
  if (missed) parts.push(`${missed} missed`)
  if (incorrect) parts.push(`${incorrect} incorrect ${incorrect === 1 ? 'choice' : 'choices'}`)
  return `${parts.join(' · ')}.`
}
