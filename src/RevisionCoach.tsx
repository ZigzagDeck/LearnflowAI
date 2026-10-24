import { useState, type ReactNode } from 'react'

type Citation = { source_id: string; source_type: 'pdf' | 'pptx' | 'image' | 'video'; chunk_id?: string; page?: number | null; slide?: number | null; image?: number | null; start_seconds?: number | null; end_seconds?: number | null }
export type RevisionPlan = {
  quiz_id: string
  missed_count: number
  targets: { question_id: string; question: string; explanation: string; passages: { text: string; citation: Citation }[] }[]
}

export default function RevisionCoach({ missedCount, busy, loadPlan, onPractice, renderSources }: {
  missedCount: number
  busy: boolean
  loadPlan: () => Promise<RevisionPlan>
  onPractice: (ids: string[]) => void
  renderSources: (citations: Citation[]) => ReactNode
}) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [plan, setPlan] = useState<RevisionPlan | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [error, setError] = useState('')
  if (!missedCount) return null

  const expand = async () => {
    setOpen(true)
    if (plan || loading) return
    setLoading(true)
    setError('')
    try {
      const next = await loadPlan()
      setPlan(next)
      setSelected(next.targets.filter(t => t.passages.length).slice(0, 3).map(t => t.question_id))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Revision could not be opened. Please try again.')
    } finally { setLoading(false) }
  }
  return <section className="revision-coach" aria-label="Personal revision coach">
    <div className="quiz-step-top"><div><p className="eyebrow">YOUR NEXT STEP</p><h3>Turn mistakes into progress</h3></div>
      <button type="button" className="secondary-button" disabled={busy || loading} aria-expanded={open}
        onClick={() => open ? setOpen(false) : void expand()}>{open ? 'Hide revision' : 'Revise missed questions'}</button></div>
    {!open && <p>{missedCount} {missedCount === 1 ? 'question to revisit' : 'questions to revisit'}. Read the source, then try a fresh check.</p>}
    {open && <div>
      {loading && <p role="status">Finding your reading…</p>}
      {error && <><p role="alert">{error}</p><button type="button" className="secondary-button" onClick={() => void expand()}>Try again</button></>}
      {plan && <>
        <p>Choose up to 3 questions to revisit.</p>
        <div className="revision-targets">{plan.targets.map((target, index) => <div className="revision-target" key={target.question_id}>
          <label className="revision-select"><input type="checkbox" checked={selected.includes(target.question_id)}
            disabled={busy || !target.passages.length || (!selected.includes(target.question_id) && selected.length >= 3)}
            onChange={() => setSelected(current => current.includes(target.question_id) ? current.filter(id => id !== target.question_id) : [...current, target.question_id])} />
            <span>{index + 1}. {target.question}</span></label>
          {target.passages.length ? <details><summary>Read &amp; revise</summary>
            <p>{target.explanation}</p>
            {target.passages.map((passage, n) => <div key={n} className="revision-reading"><blockquote>{passage.text}</blockquote>{renderSources([passage.citation])}</div>)}
          </details> : <p>Source text is no longer available for this question.</p>}
        </div>)}</div>
        <div className="quiz-step-actions"><button type="button" className="quiz-submit" disabled={busy || !selected.length}
          onClick={() => onPractice(selected)}>{busy ? 'Preparing practice…' : `Check understanding · ${selected.length} ${selected.length === 1 ? 'question' : 'questions'}`}</button></div>
        <small>New questions use your selected reading and the existing AI provider.</small>
      </>}
    </div>}
  </section>
}
