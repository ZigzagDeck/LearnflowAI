import { useState, type FormEvent } from 'react'
import { apiErrorMessage } from './auth-errors'
import { accountActionToken } from './navigation'

export type AccountAction = 'forgot-password' | 'reset-password' | 'verify-email'

export default function AccountActionScreen({ mode, apiBase, onComplete }: {
  mode: AccountAction
  apiBase: string
  onComplete: (mode: AccountAction) => void
}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [complete, setComplete] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<'email' | 'password' | 'confirmation', string>>>({})
  const token = accountActionToken(window.location.hash)
  const needsToken = mode !== 'forgot-password'
  const title = mode === 'forgot-password' ? 'Forgot your password?' : mode === 'reset-password' ? 'Choose a new password' : 'Verify your email'

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy || complete) return
    setError('')
    const nextFieldErrors: typeof fieldErrors = {}
    if (mode === 'forgot-password' && !email.trim()) nextFieldErrors.email = 'Enter your email address.'
    if (mode === 'reset-password' && !password) nextFieldErrors.password = 'Enter your new password.'
    if (mode === 'reset-password' && !confirmation) nextFieldErrors.confirmation = 'Confirm your new password.'
    setFieldErrors(nextFieldErrors)
    if (Object.keys(nextFieldErrors).length > 0) return
    if (mode === 'reset-password' && password !== confirmation) {
      setFieldErrors({ confirmation: 'Passwords do not match.' })
      return
    }
    setBusy(true)
    try {
      const body = mode === 'forgot-password' ? { email } : mode === 'reset-password' ? { token, password } : { token }
      const response = await fetch(`${apiBase}/auth/${mode}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      })
      const result = await response.json()
      if (!response.ok) throw new Error(apiErrorMessage(result, 'Unable to complete this request. Please try again.'))
      setMessage(result.message)
      setComplete(true)
      setPassword('')
      setConfirmation('')
      if (needsToken) {
        window.history.replaceState(null, '', `#${mode}`)
        onComplete(mode)
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Unable to connect. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return <main className="auth-shell">
    <a className="auth-home-link" href="#home">← Back to LearnFlow</a>
    <section className="auth-card">
      <p className="eyebrow">YOUR ACCOUNT</p>
      <h1>{title}</h1>
      <p className="auth-tagline">{mode === 'forgot-password' ? 'Enter your account email to request a password reset link.' : mode === 'reset-password' ? 'Use 8–128 characters, including an uppercase letter and a number. You will need to sign in again on all devices.' : 'Confirm your email address to finish verifying your account.'}</p>
      {message && <p role="status">{message}</p>}
      {!complete && (needsToken && !token ? <p role="alert">This link is incomplete. Request a new email.</p> : <form noValidate onSubmit={(event) => void submit(event)}>
        {mode !== 'verify-email' && <p className="required-note"><span className="required-marker" aria-hidden="true">*</span> Required fields</p>}
        {mode === 'forgot-password' && <label><span>Email address <span className="required-marker" aria-hidden="true">*</span><span className="sr-only"> required</span></span><input type="email" autoComplete="email" value={email} onChange={(event) => { setEmail(event.target.value); setFieldErrors((current) => ({ ...current, email: undefined })) }} required aria-invalid={Boolean(fieldErrors.email)} aria-describedby={fieldErrors.email ? 'account-email-error' : undefined} />{fieldErrors.email && <small className="field-error" id="account-email-error" role="alert">{fieldErrors.email}</small>}</label>}
        {mode === 'reset-password' && <>
          <label><span>New password <span className="required-marker" aria-hidden="true">*</span><span className="sr-only"> required</span></span><input type="password" autoComplete="new-password" minLength={8} maxLength={128} value={password} onChange={(event) => { setPassword(event.target.value); setFieldErrors((current) => ({ ...current, password: undefined })) }} required aria-invalid={Boolean(fieldErrors.password)} aria-describedby={fieldErrors.password ? 'account-password-error' : undefined} />{fieldErrors.password && <small className="field-error" id="account-password-error" role="alert">{fieldErrors.password}</small>}</label>
          <label><span>Confirm new password <span className="required-marker" aria-hidden="true">*</span><span className="sr-only"> required</span></span><input type="password" autoComplete="new-password" minLength={8} maxLength={128} value={confirmation} onChange={(event) => { setConfirmation(event.target.value); setFieldErrors((current) => ({ ...current, confirmation: undefined })) }} required aria-invalid={Boolean(fieldErrors.confirmation)} aria-describedby={fieldErrors.confirmation ? 'account-confirmation-error' : undefined} />{fieldErrors.confirmation && <small className="field-error" id="account-confirmation-error" role="alert">{fieldErrors.confirmation}</small>}</label>
        </>}
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="auth-submit" disabled={busy} type="submit">{busy ? 'Please wait…' : mode === 'forgot-password' ? 'Send reset link' : mode === 'reset-password' ? 'Save new password' : 'Verify email'}</button>
      </form>)}
      <a className="auth-switch" href="#login">Back to sign in</a>
      {mode === 'reset-password' && !complete && <a className="auth-switch" href="#forgot-password">Request a new reset link</a>}
    </section>
  </main>
}
