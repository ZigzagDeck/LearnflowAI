export type PublicPage = 'landing' | 'login' | 'register' | 'forgot-password' | 'reset-password' | 'verify-email'
const WORKSPACE_HASHES = new Set(['materials', 'chat', 'summary', 'quiz', 'interview', 'history'])

// Protected deep links retain their workspace destination through authentication.
export function publicPageForHash(hash: string): PublicPage {
  const destination = hash.replace(/^#/, '').split('?')[0]
  if (destination === 'forgot-password' || destination === 'reset-password' || destination === 'verify-email') return destination
  if (destination === 'register') return 'register'
  if (destination === 'login' || WORKSPACE_HASHES.has(destination)) return 'login'
  return 'landing'
}

export function accountActionToken(hash: string): string {
  return new URLSearchParams(hash.split('?')[1] || '').get('token') || ''
}
