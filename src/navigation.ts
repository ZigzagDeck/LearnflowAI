export type PublicPage = 'landing' | 'login' | 'register'
const WORKSPACE_HASHES = new Set(['materials', 'chat', 'summary', 'quiz', 'interview', 'history'])

// Protected deep links retain their workspace destination through authentication.
export function publicPageForHash(hash: string): PublicPage {
  const destination = hash.replace(/^#/, '')
  if (destination === 'register') return 'register'
  if (destination === 'login' || WORKSPACE_HASHES.has(destination)) return 'login'
  return 'landing'
}
