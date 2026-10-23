function detailMessage(detail: unknown): string {
  if (typeof detail === 'string') return detail.trim()
  if (!Array.isArray(detail)) return ''

  return detail.flatMap((issue: unknown) => {
    if (!issue || typeof issue !== 'object' || !('msg' in issue) || typeof issue.msg !== 'string') return []
    const field = 'loc' in issue && Array.isArray(issue.loc) ? issue.loc[1] : undefined
    const label = field === 'email' ? 'Email' : field === 'password' ? 'Password' : field === 'display_name' ? 'Display name' : ''
    return [`${label ? `${label}: ` : ''}${issue.msg}`]
  }).join(' ')
}

export function authErrorMessage(status: number, payload: unknown): string {
  if (status === 401) return 'Incorrect email or password. Please try again.'
  if (status === 409) return 'An account with this email already exists. Try signing in.'
  if (status === 429) return 'Too many attempts. Please wait a moment and try again.'

  return apiErrorMessage(payload, status === 422
    ? 'Please check your email, password, and account details.'
    : 'Something went wrong. Please try again.')
}

export function apiErrorMessage(payload: unknown, fallback: string): string {
  const detail = payload && typeof payload === 'object' && 'detail' in payload ? payload.detail : undefined
  return detailMessage(detail) || fallback
}
