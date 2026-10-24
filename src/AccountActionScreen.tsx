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
  const token = accountActionToken(window.location.hash)
  const needsToken = mode !== 'forgot-password'
  const title = mode === 'forgot-password' ? 'Forgot your password?' : mode === 'reset-password' ? 'Choose a new password' : 'Verify your email'

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy || complete) return
    setError('')
    if (mode === 'reset-password' && password !== confirmation) {
      setError('Passwords do not match.')
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
      {!complete && (needsToken && !token ? <p role="alert">This link is incomplete. Request a new email.</p> : <form onSubmit={(event) => void submit(event)}>
        {mode === 'forgot-password' && <label><span>Email address</span><input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>}
        {mode === 'reset-password' && <>
          <label><span>New password</span><input type="password" autoComplete="new-password" minLength={8} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
          <label><span>Confirm new password</span><input type="password" autoComplete="new-password" minLength={8} maxLength={128} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} required /></label>
        </>}
        {error && <p className="form-error" role="alert">{error}</p>}
        <button className="auth-submit" disabled={busy} type="submit">{busy ? 'Please wait…' : mode === 'forgot-password' ? 'Send reset link' : mode === 'reset-password' ? 'Save new password' : 'Verify email'}</button>
      </form>)}
      <a className="auth-switch" href="#login">Back to sign in</a>
      {mode === 'reset-password' && !complete && <a className="auth-switch" href="#forgot-password">Request a new reset link</a>}
    </section>
  </main>
}
