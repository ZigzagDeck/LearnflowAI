import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import type { DragEvent, FormEvent, KeyboardEvent, ReactNode } from 'react'
import { authErrorMessage } from './auth-errors'
import './App.css'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const MAX_FILE_SIZE = 100 * 1024 * 1024
const ACCEPTED_EXTENSIONS = ['.pdf', '.pptx', '.png', '.jpg', '.jpeg']
const ACCEPTED_FILE_TYPES = ACCEPTED_EXTENSIONS.join(',')
const AUTH_STORAGE_KEY = 'learnflow.auth.token'
const THEME_STORAGE_KEY = 'learnflow.theme'
const PALETTE_STORAGE_KEY = 'learnflow.palette'

type Theme = 'light' | 'dark'
type Palette = 'olive' | 'terminal' | 'daylight' | 'botanical' | 'blueprint' | 'legal' | 'academy' | 'atelier' | 'neon'
type WorkspaceView = 'materials' | 'chat' | 'summary' | 'quiz' | 'interview' | 'history'

const PALETTES: Array<{ id: Palette; name: string; note: string; swatch: string }> = [
  { id: 'olive', name: 'Olive Library', note: 'Calm and focused', swatch: '#747d43' },
  { id: 'terminal', name: 'Midnight Terminal', note: 'Precise and technical', swatch: '#63d9aa' },
  { id: 'daylight', name: 'Daylight Desk', note: 'Clean and minimal', swatch: '#6f7c72' },
  { id: 'botanical', name: 'Botanical Notes', note: 'Soft and playful', swatch: '#7fa467' },
  { id: 'blueprint', name: 'Blueprint Studio', note: 'Structured and analytical', swatch: '#477b9b' },
  { id: 'legal', name: 'Legal Archive', note: 'Formal and editorial', swatch: '#8d6540' },
  { id: 'academy', name: 'Classic Academy', note: 'Warm and scholarly', swatch: '#a65345' },
  { id: 'atelier', name: 'Creative Atelier', note: 'Airy and expressive', swatch: '#668a83' },
  { id: 'neon', name: 'Neon Quest', note: 'Energetic and immersive', swatch: '#a77cff' },
]

const WORKSPACE_VIEWS: Array<{ id: WorkspaceView; label: string }> = [
  { id: 'materials', label: 'Materials' },
  { id: 'chat', label: 'Ask AI' },
  { id: 'summary', label: 'Summary' },
  { id: 'quiz', label: 'Quiz' },
  { id: 'interview', label: 'Interview' },
  { id: 'history', label: 'History' },
]

function getInitialTheme(): Theme {
  const saved = window.localStorage.getItem(THEME_STORAGE_KEY)
  if (saved === 'light' || saved === 'dark') return saved
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function getInitialPalette(): Palette {
  const saved = window.localStorage.getItem(PALETTE_STORAGE_KEY)
  return PALETTES.some((item) => item.id === saved) ? saved as Palette : 'olive'
}

function getInitialView(): WorkspaceView {
  const hash = window.location.hash.slice(1)
  return WORKSPACE_VIEWS.some((item) => item.id === hash) ? hash as WorkspaceView : 'materials'
}

type UserProfile = {
  user_id: string
  email: string
  display_name: string
  role: 'user' | 'admin'
}

type AdminUserMetric = {
  user_id: string
  display_name: string
  email_hint: string
  role: 'user' | 'admin'
  created_at: string
  last_seen_at: string
  active_seconds: number
  storage_bytes: number
  material_count: number
  input_tokens: number
  output_tokens: number
  chat_requests: number
  quiz_requests: number
  summary_requests: number
  explored_domains: Array<{ label: string; count: number }>
}

type UploadStatus = 'idle' | 'ready' | 'uploading' | 'success' | 'error'
type ExtractionStatus = 'idle' | 'queued' | 'processing' | 'success' | 'error'

type OcrRuntime = {
  provider: string
  execution: 'google_cloud' | 'local'
  local_engine_enabled: boolean
  local_fallback_enabled: boolean
}

type BedrockRuntime = {
  enabled: boolean
  visual_understanding_enabled: boolean
  visual_max_units_per_material: number
  model: string
}

type ExtractedUnit = {
  reference_type: 'page' | 'slide' | 'image' | 'timestamp'
  reference_number: number
  text: string
  literal_text?: string
  has_text: boolean
  ocr_applied: boolean
  extraction_method: string
  visual_description?: string
  start_seconds?: number
  end_seconds?: number
}

type MaterialRecord = {
  resource_id: string
  original_filename: string
  source_type: string
  status: 'uploaded' | 'processing' | 'ready' | 'failed'
  error: string | null
  created_at: string
  updated_at: string
  source_url: string | null
  thumbnail_url: string | null
  processing_job: { status: string; error: string | null } | null
}

type ChatMessage = {
  message_id: string
  role: 'user' | 'assistant'
  content: string
  citations: Array<{ source_id: string; source_type: string; chunk_id?: string; page?: number; slide?: number; image?: number; start_seconds?: number; end_seconds?: number }>
  created_at: string
}

type ChatSession = {
  session_id: string
  title: string
  source_ids: string[]
  created_at: string
  updated_at: string
  message_count: number
}

type QuizQuestion = {
  question_id: string
  question: string
  question_type: 'single_answer' | 'multiple_answer' | 'short_answer'
  options: string[]
  max_selections: number
}

type QuizAttempt = {
  quiz_id: string
  session_id: string
  questions: QuizQuestion[]
}

type QuizQuestionResult = {
  question_id: string
  question_type: QuizQuestion['question_type']
  selected_option_indices: number[]
  correct_option_indices: number[]
  submitted_text: string
  accepted_answers: string[]
  correct: boolean
  explanation: string
  citations: ChatMessage['citations']
}

type QuizAnswerState = { indices: number[]; text: string }
type VideoScopeState = Record<string, { duration: number; playback: number }>

function BookLogo({ small = false }: { small?: boolean }) {
  return (
    <span className={`brand-mark${small ? ' small' : ''}`} aria-hidden="true">
      <svg viewBox="0 0 32 32" role="img">
        <path d="M5 7.5c4.3-.9 8 .1 11 2.5v15c-3-2.4-6.7-3.3-11-2.5z" />
        <path d="M27 7.5c-4.3-.9-8 .1-11 2.5v15c3-2.4 6.7-3.3 11-2.5z" />
        <path d="M16 10v15" />
      </svg>
    </span>
  )
}

function SectionGlyph({ kind }: { kind: WorkspaceView }) {
  const paths: Record<WorkspaceView, ReactNode> = {
    materials: <><path d="M4 7.5 12 4l8 3.5v10L12 21l-8-3.5z" /><path d="M12 4v17M4 7.5l8 3.5 8-3.5" /></>,
    chat: <><path d="M4 5.5h16v11H9l-5 4z" /><path d="M8 10h8M8 13h5" /></>,
    summary: <><path d="M6 3.5h9l3 3v14H6zM15 3.5v3h3M9 11h6M9 14h6M9 17h4" /></>,
    quiz: <><path d="M8.5 4h11v16h-15V8zM8.5 4v4h-4" /><path d="m8 13 2 2 4-4M15.5 14h1.5" /></>,
    interview: <><rect x="8" y="3" width="8" height="12" rx="4" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6" /></>,
    history: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7v5l3.5 2M3.5 5.5 2 7" /></>,
  }
  return <span className={`section-glyph ${kind}`} aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[kind]}</svg></span>
}

function ThemeToggle({ theme, onToggle }: { theme: Theme; onToggle: () => void }) {
  const nextTheme = theme === 'light' ? 'dark' : 'light'
  return (
    <button
      className="theme-toggle"
      type="button"
      onClick={onToggle}
      aria-label={`Switch to ${nextTheme} mode`}
      title={`Switch to ${nextTheme} mode`}
    >
      {theme === 'light' ? (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M20.2 15.4A8.5 8.5 0 0 1 8.6 3.8 8.7 8.7 0 1 0 20.2 15.4Z" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      )}
    </button>
  )
}

function PalettePicker({ palette, onChange }: { palette: Palette; onChange: (palette: Palette) => void }) {
  const selected = PALETTES.find((item) => item.id === palette) || PALETTES[0]
  return (
    <label className="palette-picker" title={selected.note}>
      <span className="palette-swatch" style={{ background: selected.swatch }} aria-hidden="true" />
      <span className="sr-only">Visual theme</span>
      <select value={palette} onChange={(event) => onChange(event.target.value as Palette)} aria-label="Visual theme">
        {PALETTES.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}
      </select>
    </label>
  )
}

function SelectionToolbar({ title, availableIds, selectedIds, totalCount, limit, onToggle, disabled = false }: {
  title: string
  availableIds: string[]
  selectedIds: string[]
  totalCount: number
  limit: number
  onToggle: (select: boolean) => void
  disabled?: boolean
}) {
  const allSelected = availableIds.length > 0 && availableIds.every((id) => selectedIds.includes(id))
  return (
    <div className="source-picker-header">
      <div>
        <h3>{title}</h3>
        <span>{selectedIds.length} selected · max {limit}</span>
      </div>
      <button type="button" className="source-toggle-all" onClick={() => onToggle(!allSelected)} disabled={disabled || availableIds.length === 0}>
        {allSelected ? 'Unselect all' : availableIds.length < totalCount ? `Select first ${availableIds.length}` : 'Select all'}
      </button>
    </div>
  )
}

const RichMarkdownAnswer = lazy(() => import('./MarkdownAnswer'))

function MarkdownAnswer({ children }: { children: string }) {
  return <Suspense fallback={<div className="markdown-answer">{children}</div>}><RichMarkdownAnswer>{children}</RichMarkdownAnswer></Suspense>
}

type QuizResult = {
  quiz_id: string
  score: number
  total: number
  questions: QuizQuestionResult[]
}

type SummaryResult = {
  summary: string
  citations: ChatMessage['citations']
}

type InterviewMessage = {
  role: 'interviewer' | 'candidate'
  content: string
  timestamp: string
}

type InterviewReport = {
  overall_score: number
  summary: string
  strengths: string[]
  areas_for_improvement: string[]
  recommendations: string[]
  questions: Array<{
    question: string
    user_answer: string
    score: number
    feedback: string
    ideal_answer_hint: string
  }>
}

type InterviewSession = {
  interview_id: string
  status: 'active' | 'completed' | 'reported'
  questions_asked: number
  question_count: number
  job_role: string
  interview_type: string
  created_at?: string
}

function formatFileSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function fileExtension(fileName: string) {
  return fileName.slice(fileName.lastIndexOf('.')).toLowerCase()
}

function formatTimestamp(seconds = 0) {
  const rounded = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(rounded / 3600)
  const minutes = Math.floor((rounded % 3600) / 60)
  const remainder = rounded % 60
  return hours
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
    : `${minutes}:${String(remainder).padStart(2, '0')}`
}

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function AuthScreen({
  onAuthenticated,
  theme,
  onToggleTheme,
  palette,
  onPaletteChange,
}: {
  onAuthenticated: (token: string, user: UserProfile) => void
  theme: Theme
  onToggleTheme: () => void
  palette: Palette
  onPaletteChange: (palette: Palette) => void
}) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const response = await fetch(`${API_BASE_URL}/auth/${mode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mode === 'login'
          ? { email, password }
          : { email, display_name: displayName, password }),
      })
      const payload = await response.json()
      if (!response.ok) {
        throw new Error(authErrorMessage(response.status, payload))
      }
      onAuthenticated(payload.token, payload.user)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Something went wrong. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="auth-shell">
      <div className="auth-theme-toggle">
        <PalettePicker palette={palette} onChange={onPaletteChange} />
        <ThemeToggle theme={theme} onToggle={onToggleTheme} />
      </div>
      <section className="auth-card">
        <div className="auth-logo-row">
          <BookLogo small />
          <div>
            <p className="eyebrow">YOUR PERSONAL STUDY SPACE</p>
            <h1>{mode === 'login' ? 'Welcome back' : 'Create your account'}</h1>
          </div>
        </div>
        <p className="auth-tagline">
          {mode === 'login'
            ? 'Sign in to access your materials, conversations, quizzes, and mock interviews.'
            : 'Join to upload study materials, ask questions, practice with quizzes, and prepare for interviews.'}
        </p>

        <div className="auth-mode-tabs" role="tablist">
          <button
            type="button"
            className={`auth-mode-tab ${mode === 'login' ? 'active' : ''}`}
            onClick={() => { setMode('login'); setError('') }}
          >
            Sign In
          </button>
          <button
            type="button"
            className={`auth-mode-tab ${mode === 'register' ? 'active' : ''}`}
            onClick={() => { setMode('register'); setError('') }}
          >
            Create Account
          </button>
        </div>

        <form onSubmit={(event) => void submit(event)}>
          {mode === 'register' && (
            <label>
              <span>Your name</span>
              <input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                autoComplete="name"
                placeholder="e.g. Alex Smith"
                required
              />
            </label>
          )}
          <label>
            <span>Email address</span>
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
              placeholder="you@example.com"
              required
            />
          </label>
          <label>
            <span>Password</span>
            <div className="password-input-wrap">
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                placeholder={mode === 'register' ? 'Min. 8 chars, 1 uppercase, 1 number' : '••••••••'}
                required
              />
              <button
                type="button"
                className="password-toggle-btn"
                onClick={() => setShowPassword(!showPassword)}
                tabIndex={-1}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                title={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? (
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                    <line x1="1" y1="1" x2="23" y2="23" />
                  </svg>
                ) : (
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
              </button>
            </div>
          </label>
          {error && <p className="form-error" role="alert">⚠ {error}</p>}
          <button type="submit" disabled={busy} className="auth-submit">
            {busy ? 'Please wait…' : mode === 'login' ? 'Sign in →' : 'Create account →'}
          </button>
        </form>
        <button
          className="auth-switch"
          type="button"
          onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError('') }}
        >
          {mode === 'login' ? "Don't have an account yet? Create one here" : 'Already have an account? Sign in here'}
        </button>
      </section>
    </main>
  )
}

function App() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme)
  const [palette, setPalette] = useState<Palette>(getInitialPalette)
  const [activeView, setActiveView] = useState<WorkspaceView>(getInitialView)
  const [authToken, setAuthToken] = useState(() => window.localStorage.getItem(AUTH_STORAGE_KEY) || '')
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(null)
  const [authReady, setAuthReady] = useState(() => !window.localStorage.getItem(AUTH_STORAGE_KEY))
  const [adminOpen, setAdminOpen] = useState(false)
  const [adminUsers, setAdminUsers] = useState<AdminUserMetric[]>([])
  const [adminBusy, setAdminBusy] = useState(false)
  const [adminError, setAdminError] = useState('')
  const [exportBusy, setExportBusy] = useState(false)
  const [videoPreview, setVideoPreview] = useState<{ title: string; embedUrl: string } | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [status, setStatus] = useState<UploadStatus>('idle')
  const [progress, setProgress] = useState(0)
  const [message, setMessage] = useState('')
  const [isDragging, setIsDragging] = useState(false)
  const [uploadedResourceId, setUploadedResourceId] = useState('')
  const [extractionStatus, setExtractionStatus] = useState<ExtractionStatus>('idle')
  const [processingProgress, setProcessingProgress] = useState(0)
  const [extractionMessage, setExtractionMessage] = useState('')
  const [extractedContent, setExtractedContent] = useState<ExtractedUnit[]>([])
  const [youtubeUrl, setYoutubeUrl] = useState('')
  const [activeYoutubeUrl, setActiveYoutubeUrl] = useState('')
  const [materials, setMaterials] = useState<MaterialRecord[]>([])
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([])
  const [chatSessionId, setChatSessionId] = useState(() => crypto.randomUUID().replaceAll('-', ''))
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [chatQuestion, setChatQuestion] = useState('')
  const [chatSourceIds, setChatSourceIds] = useState<string[]>([])
  const [chatVideoScopes, setChatVideoScopes] = useState<VideoScopeState>({})
  const [chatBusy, setChatBusy] = useState(false)
  const [chatError, setChatError] = useState('')
  const chatMessagesRef = useRef<HTMLDivElement>(null)
  const [quizSessionId, setQuizSessionId] = useState(() => crypto.randomUUID().replaceAll('-', ''))
  const [quizSourceIds, setQuizSourceIds] = useState<string[]>([])
  const [quizCount, setQuizCount] = useState(5)
  const [quizType, setQuizType] = useState<'single_answer' | 'multiple_answer' | 'short_answer' | 'mixed'>('mixed')
  const [quizBusy, setQuizBusy] = useState(false)
  const [quizError, setQuizError] = useState('')
  const [quiz, setQuiz] = useState<QuizAttempt | null>(null)
  const [quizAnswers, setQuizAnswers] = useState<Record<string, QuizAnswerState>>({})
  const [quizResult, setQuizResult] = useState<QuizResult | null>(null)
  const [summarySourceIds, setSummarySourceIds] = useState<string[]>([])
  const [summaryStyle, setSummaryStyle] = useState<'concise' | 'detailed' | 'study_guide'>('detailed')
  const [summaryResult, setSummaryResult] = useState<SummaryResult | null>(null)
  const [summaryBusy, setSummaryBusy] = useState(false)
  const [summaryError, setSummaryError] = useState('')
  const [historyTab, setHistoryTab] = useState<'processed' | 'chat' | 'interview'>('processed')
  const [historyMessage, setHistoryMessage] = useState('')
  const [historyBusy, setHistoryBusy] = useState(false)
  const [ocrRuntime, setOcrRuntime] = useState<OcrRuntime | null>(null)
  const [bedrockRuntime, setBedrockRuntime] = useState<BedrockRuntime | null>(null)
  // Interview state
  const [interviewJobRole, setInterviewJobRole] = useState('')
  const [interviewJobDesc, setInterviewJobDesc] = useState('')
  const [interviewResume, setInterviewResume] = useState('')
  const [interviewSourceIds, setInterviewSourceIds] = useState<string[]>([])
  const sourceDefaultsInitialized = useRef(false)
  const [interviewType, setInterviewType] = useState('mixed')
  const [interviewQuestionCount, setInterviewQuestionCount] = useState(5)
  const [interviewSession, setInterviewSession] = useState<InterviewSession | null>(null)
  const [interviewMessages, setInterviewMessages] = useState<InterviewMessage[]>([])
  const [interviewInput, setInterviewInput] = useState('')
  const [interviewBusy, setInterviewBusy] = useState(false)
  const [interviewError, setInterviewError] = useState('')
  const [interviewReport, setInterviewReport] = useState<InterviewReport | null>(null)
  const [interviewReportBusy, setInterviewReportBusy] = useState(false)
  const [interviewHistory, setInterviewHistory] = useState<InterviewSession[]>([])
  const interviewMessagesRef = useRef<HTMLDivElement>(null)

  const apiFetch = useCallback((url: string, options: RequestInit = {}) => {
    const headers = new Headers(options.headers)
    if (authToken) headers.set('Authorization', `Bearer ${authToken}`)
    return fetch(url, { ...options, headers })
  }, [authToken])

  const toggleTheme = () => setTheme((current) => current === 'light' ? 'dark' : 'light')

  const navigateTo = useCallback((view: WorkspaceView) => {
    setActiveView(view)
    if (window.location.hash !== `#${view}`) {
      window.history.pushState(null, '', `#${view}`)
    }
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.dataset.palette = palette
    document.documentElement.style.colorScheme = theme
    window.localStorage.setItem(THEME_STORAGE_KEY, theme)
    window.localStorage.setItem(PALETTE_STORAGE_KEY, palette)
  }, [palette, theme])

  useEffect(() => {
    const restoreView = () => setActiveView(getInitialView())
    window.addEventListener('popstate', restoreView)
    window.addEventListener('hashchange', restoreView)
    return () => {
      window.removeEventListener('popstate', restoreView)
      window.removeEventListener('hashchange', restoreView)
    }
  }, [])

  useEffect(() => {
    let active = true
    if (!authToken) {
      return () => { active = false }
    }
    const restoreSession = async () => {
      try {
        const response = await apiFetch(`${API_BASE_URL}/auth/me`)
        const payload = await response.json()
        if (!response.ok) throw new Error(payload.detail || 'Session expired.')
        if (active) setCurrentUser(payload)
      } catch {
        window.localStorage.removeItem(AUTH_STORAGE_KEY)
        if (active) {
          setAuthToken('')
          setCurrentUser(null)
        }
      } finally {
        if (active) setAuthReady(true)
      }
    }
    void restoreSession()
    return () => { active = false }
  }, [apiFetch, authToken])

  const clearPrivateWorkspace = () => {
    setMaterials([])
    setChatSessions([])
    setChatMessages([])
    setChatSourceIds([])
    setChatVideoScopes({})
    setQuizSourceIds([])
    setSummarySourceIds([])
    setInterviewSourceIds([])
    sourceDefaultsInitialized.current = false
    setQuiz(null)
    setQuizAnswers({})
    setQuizResult(null)
    setExtractedContent([])
    setUploadedResourceId('')
    setSelectedFile(null)
    setYoutubeUrl('')
    setActiveYoutubeUrl('')
    setStatus('idle')
    setExtractionStatus('idle')
    setChatSessionId(crypto.randomUUID().replaceAll('-', ''))
    setQuizSessionId(crypto.randomUUID().replaceAll('-', ''))
    setInterviewSession(null)
    setInterviewMessages([])
    setInterviewReport(null)
    setInterviewHistory([])
    setInterviewError('')
  }

  const authenticated = (token: string, user: UserProfile) => {
    clearPrivateWorkspace()
    window.localStorage.setItem(AUTH_STORAGE_KEY, token)
    setAuthToken(token)
    setCurrentUser(user)
    setAuthReady(true)
  }

  const logout = async () => {
    try { await apiFetch(`${API_BASE_URL}/auth/logout`, { method: 'POST' }) } catch { /* Local sign-out still succeeds. */ }
    window.localStorage.removeItem(AUTH_STORAGE_KEY)
    clearPrivateWorkspace()
    setAuthToken('')
    setCurrentUser(null)
    setAdminOpen(false)
  }

  const exportAccountData = async () => {
    setExportBusy(true)
    try {
      const response = await apiFetch(`${API_BASE_URL}/account/export`)
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(payload.detail || 'Your data export could not be created.')
      }
      const blob = await response.blob()
      const downloadUrl = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = downloadUrl
      link.download = `learnflow-export-${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(downloadUrl)
    } catch (error) {
      setHistoryMessage(error instanceof Error ? error.message : 'Your data export could not be created.')
    } finally {
      setExportBusy(false)
    }
  }

  const loadHistories = useCallback(async (silent = false) => {
    if (!silent) setHistoryBusy(true)
    try {
      const [materialsResponse, chatsResponse] = await Promise.all([
        apiFetch(`${API_BASE_URL}/materials`),
        apiFetch(`${API_BASE_URL}/chat/history`),
      ])
      const materialsPayload = await materialsResponse.json()
      const chatsPayload = await chatsResponse.json()
      if (!materialsResponse.ok) throw new Error(materialsPayload.detail || 'Your materials could not be loaded. Please refresh.')
      if (!chatsResponse.ok) throw new Error(chatsPayload.detail || 'Your chat history could not be loaded.')
      const nextMaterials: MaterialRecord[] = materialsPayload.materials || []
      setMaterials(nextMaterials)
      setChatSessions(chatsPayload.sessions || [])
      const ready = nextMaterials.filter((item) => item.status === 'ready')
      if (!sourceDefaultsInitialized.current) {
        setChatSourceIds(ready.filter((item) => item.source_type !== 'video').slice(0, 30).map((item) => item.resource_id))
        setQuizSourceIds(ready.slice(0, 12).map((item) => item.resource_id))
        setSummarySourceIds(ready.slice(0, 12).map((item) => item.resource_id))
        sourceDefaultsInitialized.current = ready.length > 0
      } else {
        const readyIds = new Set(ready.map((item) => item.resource_id))
        setChatSourceIds((current) => current.filter((id) => readyIds.has(id)))
        setQuizSourceIds((current) => current.filter((id) => readyIds.has(id)))
        setSummarySourceIds((current) => current.filter((id) => readyIds.has(id)))
        setInterviewSourceIds((current) => current.filter((id) => readyIds.has(id)))
      }
      setHistoryMessage('')
    } catch (error) {
      setHistoryMessage(error instanceof Error ? error.message : 'History could not be loaded. Please refresh.')
    } finally {
      if (!silent) setHistoryBusy(false)
    }
  }, [apiFetch])

  useEffect(() => {
    if (!currentUser) return
    const timer = window.setTimeout(() => void loadHistories(), 0)
    return () => window.clearTimeout(timer)
  }, [currentUser, loadHistories])

  useEffect(() => {
    if (!authToken || !currentUser) return
    let active = true
    const loadOcrRuntime = async () => {
      try {
        const [ocrResponse, bedrockResponse] = await Promise.all([
          apiFetch(`${API_BASE_URL}/usage/ocr`),
          apiFetch(`${API_BASE_URL}/usage/bedrock`),
        ])
        const [ocrPayload, bedrockPayload] = await Promise.all([ocrResponse.json(), bedrockResponse.json()])
        if (ocrResponse.ok && active) setOcrRuntime(ocrPayload)
        if (bedrockResponse.ok && active) setBedrockRuntime(bedrockPayload)
      } catch {
        // Processing errors still surface through the material status endpoint.
      }
    }
    void loadOcrRuntime()
    return () => { active = false }
  }, [apiFetch, authToken, currentUser])

  useEffect(() => {
    if (!materials.some((item) => item.status === 'uploaded' || item.status === 'processing')) return
    const timer = window.setInterval(() => void loadHistories(true), 1500)
    return () => window.clearInterval(timer)
  }, [materials, loadHistories])

  const loadVideoScope = useCallback(async (sourceId: string) => {
    try {
      const response = await apiFetch(`${API_BASE_URL}/materials/${sourceId}/content`)
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'The video transcript could not be loaded.')
      const duration = Math.max(0, ...(payload.content || []).map((unit: ExtractedUnit) => unit.end_seconds || 0))
      setChatVideoScopes((current) => ({
        ...current,
        [sourceId]: current[sourceId] || { duration, playback: duration },
      }))
    } catch (error) {
      setChatError(error instanceof Error ? error.message : 'The video transcript could not be loaded.')
      setChatSourceIds((current) => current.filter((id) => id !== sourceId))
    }
  }, [apiFetch])

  const updateChatSource = (material: MaterialRecord, checked: boolean) => {
    if (checked && chatSourceIds.length >= 30) {
      setChatError('You can use up to 30 materials in one chat.')
      return
    }
    const selectedVideoCount = materials.filter((item) => item.source_type === 'video' && chatSourceIds.includes(item.resource_id)).length
    if (checked && material.source_type === 'video' && selectedVideoCount >= 10) {
      setChatError('You can compare up to 10 videos in one chat.')
      return
    }
    setChatError('')
    setChatSourceIds((current) => checked
      ? [...new Set([...current, material.resource_id])]
      : current.filter((id) => id !== material.resource_id))
    if (material.source_type === 'video') {
      if (checked) void loadVideoScope(material.resource_id)
      else setChatVideoScopes((current) => {
        const next = { ...current }
        delete next[material.resource_id]
        return next
      })
    }
  }

  const readyMaterials = materials.filter((item) => item.status === 'ready')
  const chatBulkMaterials = readyMaterials.filter((item) => item.source_type !== 'video').slice(0, 30)
  const chatVideoSlots = Math.min(10, 30 - chatBulkMaterials.length)
  chatBulkMaterials.push(...readyMaterials.filter((item) => item.source_type === 'video').slice(0, chatVideoSlots))
  const summaryBulkIds = readyMaterials.slice(0, 12).map((item) => item.resource_id)
  const quizBulkIds = summaryBulkIds
  const interviewBulkIds = readyMaterials.slice(0, 5).map((item) => item.resource_id)

  const toggleAllChatSources = (select: boolean) => {
    if (!select) {
      setChatSourceIds([])
      setChatVideoScopes({})
    } else {
      const selectedIds = chatBulkMaterials.map((item) => item.resource_id)
      setChatSourceIds(selectedIds)
      chatBulkMaterials.filter((item) => item.source_type === 'video' && !chatSourceIds.includes(item.resource_id))
        .forEach((item) => void loadVideoScope(item.resource_id))
    }
    setChatError('')
  }

  const selectFile = (file: File) => {
    if (!ACCEPTED_EXTENSIONS.includes(fileExtension(file.name))) {
      setSelectedFile(null)
      setStatus('error')
      setMessage('That file type is not supported. Choose a PDF, PPTX, PNG, or JPEG file.')
      return
    }
    if (file.size > MAX_FILE_SIZE) {
      setSelectedFile(null)
      setStatus('error')
      setMessage('That file is too large. The maximum file size is 100 MB.')
      return
    }
    setSelectedFile(file)
    setStatus('ready')
    setProgress(0)
    setMessage('')
    setUploadedResourceId('')
    setExtractionStatus('idle')
    setProcessingProgress(0)
    setExtractionMessage('')
    setExtractedContent([])
    setActiveYoutubeUrl('')
  }

  const uploadFile = () => {
    if (!selectedFile || status === 'uploading') return

    const formData = new FormData()
    formData.append('file', selectedFile)
    const request = new XMLHttpRequest()

    request.open('POST', `${API_BASE_URL}/materials/upload`)
    request.setRequestHeader('Authorization', `Bearer ${authToken}`)
    request.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) setProgress(Math.round((event.loaded / event.total) * 100))
    })
    request.addEventListener('load', () => {
      if (request.status >= 200 && request.status < 300) {
        const response = JSON.parse(request.responseText)
        setStatus('success')
        setProgress(100)
        setUploadedResourceId(response.resource_id)
        setExtractionStatus(response.processing_job?.status === 'completed' ? 'queued' : (response.processing_job?.status || 'queued'))
        setMessage(response.deduplicated
          ? 'This material already exists in your workspace. Its saved processing result will be reused.'
          : 'File uploaded. Text extraction and AI processing have been queued automatically.')
        void loadHistories()
      } else {
        let detail = 'Upload failed. Please check your file and try again.'
        try {
          const parsed = JSON.parse(request.responseText)
          const raw = parsed.detail || ''
          if (request.status === 413) detail = 'That file is too large. The maximum size is 100 MB.'
          else if (request.status === 415) detail = 'That file type is not supported. Please use PDF, PPTX, PNG, or JPEG.'
          else if (request.status === 401) detail = 'Your session has expired. Please sign in again.'
          else if (raw) detail = raw
        } catch { /* Keep the fallback message. */ }
        setStatus('error')
        setMessage(detail)
      }
    })
    request.addEventListener('error', () => {
      setStatus('error')
      setMessage('The server could not be reached. Make sure the backend is running, then try again.')
    })
    setStatus('uploading')
    setProgress(0)
    setMessage('Uploading to your local workspace…')
    request.send(formData)
  }

  const loadExtractedContent = useCallback(async (resourceId: string) => {
    const response = await apiFetch(`${API_BASE_URL}/materials/${resourceId}/content`)
    const payload = await response.json()
    if (!response.ok) throw new Error(payload.detail || 'The processed content could not be loaded.')
    setExtractedContent(payload.content)
    setExtractionStatus('success')
    setProcessingProgress(100)
    const referenceType = payload.content[0]?.reference_type
    const units = referenceType === 'page' ? 'pages'
      : referenceType === 'slide' ? 'slides'
        : referenceType === 'timestamp' ? 'caption segments' : 'images'
    setExtractionMessage(referenceType === 'timestamp'
      ? `Indexed ${payload.content.length} timestamped caption segments.`
      : `Processed ${payload.content.length} ${units} successfully.`)
    void loadHistories()
  }, [apiFetch, loadHistories])

  const importYoutube = async () => {
    if (!youtubeUrl.trim() || status === 'uploading') return
    setSelectedFile(null)
    setStatus('uploading')
    setMessage('Validating the YouTube link…')
    setExtractedContent([])
    setExtractionStatus('idle')
    try {
      const response = await apiFetch(`${API_BASE_URL}/materials/youtube`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: youtubeUrl.trim() }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'The YouTube link could not be imported.')
      setActiveYoutubeUrl(payload.source_url)
      setUploadedResourceId(payload.resource_id)
      setExtractionStatus(payload.processing_job?.status || 'queued')
      setStatus('success')
      setMessage(payload.deduplicated
        ? 'This YouTube video already exists. Its saved transcript will be reused.'
        : 'YouTube link added. Timestamped captions are queued for processing.')
      void loadHistories()
    } catch (error) {
      setStatus('error')
      setMessage(error instanceof Error ? error.message : 'The YouTube link could not be imported.')
    }
  }

  useEffect(() => {
    if (!uploadedResourceId || !['queued', 'processing'].includes(extractionStatus)) return
    let active = true
    let polling = false

    const poll = async () => {
      if (polling) return
      polling = true
      try {
        const response = await apiFetch(`${API_BASE_URL}/materials/${uploadedResourceId}/status`)
        const payload = await response.json()
        if (!response.ok) throw new Error(payload.detail || 'Processing status is unavailable.')
        if (!active) return
        const job = payload.processing_job
        setProcessingProgress(job?.progress_percent || 0)
        if (payload.status === 'ready' || job?.status === 'completed') {
          await loadExtractedContent(uploadedResourceId)
        } else if (payload.status === 'failed' || job?.status === 'failed') {
          setExtractionStatus('error')
          setExtractionMessage(job?.error || payload.error || 'Material processing failed. You can retry it.')
          void loadHistories()
        } else if (job?.status === 'processing') {
          setExtractionStatus('processing')
          setExtractionMessage(job.progress_total
            ? `Analyzing and extracting text from material… ${job.progress_current} of ${job.progress_total}`
            : activeYoutubeUrl ? 'Retrieving timestamped video captions…' : 'Preparing intelligent document extraction…')
        } else {
          setExtractionStatus('queued')
          setExtractionMessage('Preparing document for processing…')
        }
      } catch (error) {
        if (active) {
          setExtractionStatus('error')
          setExtractionMessage(error instanceof Error ? error.message : 'Processing status is unavailable.')
        }
      } finally {
        polling = false
      }
    }

    void poll()
    const timer = window.setInterval(() => void poll(), 1000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [apiFetch, uploadedResourceId, extractionStatus, loadExtractedContent, loadHistories, activeYoutubeUrl, bedrockRuntime?.visual_understanding_enabled])

  const retryProcessing = async () => {
    if (!uploadedResourceId || extractionStatus !== 'error') return
    setExtractionStatus('queued')
    setProcessingProgress(0)
    setExtractionMessage('Re-queuing for processing…')
    try {
      const response = await apiFetch(`${API_BASE_URL}/materials/${uploadedResourceId}/process`, {
        method: 'POST',
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'The material could not be re-queued.')
      setExtractionMessage('Waiting for the processing worker…')
    } catch (error) {
      setExtractionStatus('error')
      setExtractionMessage(error instanceof Error ? error.message : 'The material could not be re-queued. Please try again.')
    }
  }

  const askChat = async () => {
    const question = chatQuestion.trim()
    if (!question || chatBusy || chatSourceIds.length === 0) return
    const optimisticMessage: ChatMessage = {
      message_id: crypto.randomUUID(),
      role: 'user',
      content: question,
      citations: [],
      created_at: new Date().toISOString(),
    }
    setChatMessages((current) => [...current, optimisticMessage])
    setChatQuestion('')
    setChatBusy(true)
    setChatError('')
    try {
      const response = await apiFetch(`${API_BASE_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: chatSessionId,
          question,
          allowed_source_ids: chatSourceIds,
          video_scopes: Object.entries(chatVideoScopes)
            .filter(([sourceId]) => chatSourceIds.includes(sourceId))
            .map(([sourceId, scope]) => ({ source_id: sourceId, playback_seconds: scope.playback })),
        }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'The answer could not be generated.')
      setChatMessages((current) => [
        ...current,
        { message_id: crypto.randomUUID(), role: 'assistant', content: payload.answer, citations: payload.citations || [], created_at: new Date().toISOString() },
      ])
      void loadHistories()
    } catch (error) {
      setChatError(error instanceof Error ? error.message : 'The answer could not be generated.')
      setChatMessages((current) => current.filter((item) => item.message_id !== optimisticMessage.message_id))
      setChatQuestion(question)
    } finally {
      setChatBusy(false)
    }
  }

  useEffect(() => {
    const container = chatMessagesRef.current
    if (container) container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
  }, [chatMessages, chatBusy])

  const handleChatKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void askChat()
    }
  }

  const startNewChat = () => {
    setChatSessionId(crypto.randomUUID().replaceAll('-', ''))
    setChatMessages([])
    setChatError('')
    setChatQuestion('')
  }

  const startNewQuiz = () => {
    setQuizSessionId(crypto.randomUUID().replaceAll('-', ''))
    setQuiz(null)
    setQuizAnswers({})
    setQuizResult(null)
    setSummarySourceIds([])
    setSummaryResult(null)
    setSummaryError('')
    setQuizError('')
  }

  const generateQuiz = async () => {
    if (quizBusy || quizSourceIds.length === 0) return
    setQuizBusy(true)
    setQuizError('')
    setQuiz(null)
    setQuizResult(null)
    setQuizAnswers({})
    try {
      const response = await apiFetch(`${API_BASE_URL}/quiz`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: quizSessionId,
          allowed_source_ids: quizSourceIds,
          count: quizCount,
          quiz_type: quizType,
        }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'The quiz could not be generated.')
      setQuiz(payload)
    } catch (error) {
      setQuizError(error instanceof Error ? error.message : 'The quiz could not be generated.')
    } finally {
      setQuizBusy(false)
    }
  }

  const submitQuiz = async () => {
    if (!quiz || quizBusy || quiz.questions.some((question) => {
      const answer = quizAnswers[question.question_id]
      return question.question_type === 'short_answer' ? !answer?.text.trim() : !answer?.indices.length
    })) return
    setQuizBusy(true)
    setQuizError('')
    try {
      const response = await apiFetch(`${API_BASE_URL}/quiz/${quiz.quiz_id}/submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: quiz.session_id,
          answers: quiz.questions.map((question) => ({
            question_id: question.question_id,
            selected_option_indices: quizAnswers[question.question_id]?.indices || [],
            text_answer: quizAnswers[question.question_id]?.text || '',
          })),
        }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'The quiz could not be scored.')
      setQuizResult(payload)
    } catch (error) {
      setQuizError(error instanceof Error ? error.message : 'The quiz could not be scored. Please try again.')
    } finally {
      setQuizBusy(false)
    }
  }

  const generateSummary = async () => {
    if (summaryBusy || summarySourceIds.length === 0) return
    setSummaryBusy(true)
    setSummaryError('')
    try {
      const response = await apiFetch(`${API_BASE_URL}/summary`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          allowed_source_ids: summarySourceIds,
          style: summaryStyle,
        }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'The summary could not be generated. Please try again.')
      setSummaryResult(payload)
    } catch (error) {
      setSummaryError(error instanceof Error ? error.message : 'The summary could not be generated. Please try again.')
    } finally {
      setSummaryBusy(false)
    }
  }

  // ---------- Interview handlers ----------
  const interviewSessionId = useRef(crypto.randomUUID().replaceAll('-', ''))

  const loadInterviewHistory = useCallback(async () => {
    try {
      const response = await apiFetch(`${API_BASE_URL}/interview/history`)
      const payload = await response.json()
      if (response.ok) setInterviewHistory(payload.sessions || [])
    } catch { /* Non-critical */ }
  }, [apiFetch])

  useEffect(() => {
    // Server history must be refreshed when the authenticated account changes.
    // oxlint-disable-next-line react/set-state-in-effect
    if (currentUser) void loadInterviewHistory()
  }, [currentUser, loadInterviewHistory])

  useEffect(() => {
    const container = interviewMessagesRef.current
    if (container) container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' })
  }, [interviewMessages, interviewBusy])

  const startInterview = async () => {
    if (!interviewJobRole.trim() || interviewBusy) return
    setInterviewBusy(true)
    setInterviewError('')
    setInterviewMessages([])
    setInterviewReport(null)
    interviewSessionId.current = crypto.randomUUID().replaceAll('-', '')
    try {
      const response = await apiFetch(`${API_BASE_URL}/interview/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: interviewSessionId.current,
          job_role: interviewJobRole.trim(),
          job_description: interviewJobDesc.trim(),
          resume_text: interviewResume.trim(),
          material_ids: interviewSourceIds,
          question_count: interviewQuestionCount,
          interview_type: interviewType,
        }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'The interview could not be started. Please try again.')
      setInterviewSession({
        interview_id: payload.interview_id,
        status: payload.status,
        questions_asked: payload.questions_asked,
        question_count: payload.question_count,
        job_role: interviewJobRole.trim(),
        interview_type: interviewType,
      })
      setInterviewMessages([{ role: 'interviewer', content: payload.message, timestamp: new Date().toISOString() }])
    } catch (error) {
      setInterviewError(error instanceof Error ? error.message : 'The interview could not be started. Please try again.')
    } finally {
      setInterviewBusy(false)
    }
  }

  const sendInterviewReply = async () => {
    const text = interviewInput.trim()
    if (!text || !interviewSession || interviewBusy || interviewSession.status !== 'active') return
    const userMsg: InterviewMessage = { role: 'candidate', content: text, timestamp: new Date().toISOString() }
    setInterviewMessages((prev) => [...prev, userMsg])
    setInterviewInput('')
    setInterviewBusy(true)
    setInterviewError('')
    try {
      const response = await apiFetch(`${API_BASE_URL}/interview/${interviewSession.interview_id}/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'Something went wrong. Please try again.')
      setInterviewSession((prev) => prev ? { ...prev, status: payload.status, questions_asked: payload.questions_asked } : prev)
      setInterviewMessages((prev) => [...prev, { role: 'interviewer', content: payload.message, timestamp: new Date().toISOString() }])
    } catch (error) {
      setInterviewError(error instanceof Error ? error.message : 'Something went wrong sending your response. Please try again.')
      setInterviewMessages((prev) => prev.filter((m) => m !== userMsg))
      setInterviewInput(text)
    } finally {
      setInterviewBusy(false)
    }
  }

  const fetchInterviewReport = async () => {
    if (!interviewSession || interviewReportBusy) return
    setInterviewReportBusy(true)
    setInterviewError('')
    try {
      const response = await apiFetch(`${API_BASE_URL}/interview/${interviewSession.interview_id}/report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'The evaluation report could not be generated. Please try again.')
      setInterviewReport(payload.report)
      setInterviewSession((prev) => prev ? { ...prev, status: 'reported' } : prev)
      void loadInterviewHistory()
    } catch (error) {
      setInterviewError(error instanceof Error ? error.message : 'The report could not be generated. Please try again.')
    } finally {
      setInterviewReportBusy(false)
    }
  }

  const resetInterview = () => {
    setInterviewSession(null)
    setInterviewMessages([])
    setInterviewReport(null)
    setInterviewError('')
    setInterviewInput('')
  }

  const deleteInterviewSession = async (id: string) => {
    try {
      await apiFetch(`${API_BASE_URL}/interview/${id}`, { method: 'DELETE' })
      setInterviewHistory((prev) => prev.filter((s) => s.interview_id !== id))
    } catch { /* Ignore */ }
  }

  const openInterviewSession = async (id: string) => {
    try {
      navigateTo('interview')
      setInterviewBusy(true)
      setInterviewError('')
      const response = await apiFetch(`${API_BASE_URL}/interview/${id}`)
      if (!response.ok) throw new Error('Could not load interview session.')
      const session = await response.json()
      setInterviewSession({
        interview_id: session.interview_id,
        status: session.status,
        questions_asked: session.history.filter((m: { role: string }) => m.role === 'assistant').length,
        question_count: session.question_count,
        job_role: session.job_role,
        interview_type: session.interview_type,
      })
      setInterviewJobRole(session.job_role)
      setInterviewType(session.interview_type)
      setInterviewMessages(
        session.history
          .filter((m: { content: string }) => m.content !== '[START_INTERVIEW]')
          .map((m: { role: string; content: string }) => ({
            role: m.role === 'assistant' ? 'interviewer' : 'candidate',
            content: m.content,
            timestamp: new Date().toISOString(),
          }))
      )
      setInterviewReport(session.report || null)
      document.getElementById('interview')?.scrollIntoView({ behavior: 'smooth' })
    } catch (error) {
      setInterviewError(error instanceof Error ? error.message : 'Could not open interview.')
    } finally {
      setInterviewBusy(false)
    }
  }

  const handleInterviewKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void sendInterviewReply()
    }
  }

  const openChatSession = async (sessionId: string) => {
    try {
      navigateTo('chat')
      const response = await apiFetch(`${API_BASE_URL}/chat/history/${sessionId}`)
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'This chat could not be opened.')
      setChatSessionId(payload.session_id)
      setChatMessages(payload.messages || [])
      const readyIds = new Set(materials.filter((item) => item.status === 'ready').map((item) => item.resource_id))
      const restoredIds = (payload.source_ids || []).filter((id: string) => readyIds.has(id))
      setChatSourceIds(restoredIds)
      const restoredVideos = materials.filter((item) => restoredIds.includes(item.resource_id) && item.source_type === 'video')
      setChatVideoScopes({})
      restoredVideos.forEach((item) => void loadVideoScope(item.resource_id))
      setChatError('')
      document.getElementById('chat')?.scrollIntoView({ behavior: 'smooth' })
    } catch (error) {
      setHistoryMessage(error instanceof Error ? error.message : 'This chat could not be opened.')
    }
  }

  const deleteChatSession = async (session: ChatSession) => {
    if (!window.confirm(`Delete this chat history?\n\n“${session.title}”`)) return
    try {
      const response = await apiFetch(`${API_BASE_URL}/chat/history/${session.session_id}`, { method: 'DELETE' })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'The chat could not be deleted.')
      if (chatSessionId === session.session_id) startNewChat()
      await loadHistories()
      setHistoryMessage('Chat history deleted.')
    } catch (error) {
      setHistoryMessage(error instanceof Error ? error.message : 'The chat could not be deleted.')
    }
  }

  const deleteMaterial = async (material: MaterialRecord) => {
    if (material.status === 'processing') return
    if (!window.confirm(`Permanently delete “${material.original_filename}” and its processed data? This also removes its cached extraction, chunks, and embeddings.`)) return
    try {
      const response = await apiFetch(`${API_BASE_URL}/materials/${material.resource_id}`, { method: 'DELETE' })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'The material could not be deleted.')
      setChatSourceIds((current) => current.filter((id) => id !== material.resource_id))
      setQuizSourceIds((current) => current.filter((id) => id !== material.resource_id))
      setSummarySourceIds((current) => current.filter((id) => id !== material.resource_id))
      setChatVideoScopes((current) => {
        const next = { ...current }
        delete next[material.resource_id]
        return next
      })
      if (uploadedResourceId === material.resource_id) {
        setUploadedResourceId('')
        setExtractedContent([])
        setExtractionStatus('idle')
        setExtractionMessage('')
      }
      await loadHistories()
      setHistoryMessage('Material and its processed data deleted.')
    } catch (error) {
      setHistoryMessage(error instanceof Error ? error.message : 'The material could not be deleted.')
    }
  }

  const retryHistoryMaterial = async (material: MaterialRecord) => {
    try {
      const response = await apiFetch(`${API_BASE_URL}/materials/${material.resource_id}/process`, { method: 'POST' })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'The material could not be queued for retry.')
      await loadHistories()
      setHistoryMessage('Processing retry queued. The history will update when it finishes.')
    } catch (error) {
      setHistoryMessage(error instanceof Error ? error.message : 'The material could not be queued for retry.')
    }
  }

  const openMaterial = async (
    material: MaterialRecord,
    referenceType?: string,
    referenceNumber?: number,
  ) => {
    if (material.status !== 'ready') return
    navigateTo('materials')
    setHistoryMessage('')
    setUploadedResourceId(material.resource_id)
    setSelectedFile(null)
    setStatus('success')
    setActiveYoutubeUrl(material.source_url || '')
    setExtractionStatus('processing')
    setExtractionMessage(material.source_type === 'video' ? 'Opening saved transcript…' : 'Opening saved extracted content…')
    try {
      await loadExtractedContent(material.resource_id)
      window.setTimeout(() => {
        const target = referenceType && referenceNumber
          ? document.getElementById(`content-${material.resource_id}-${referenceType}-${referenceNumber}`)
          : document.getElementById('workspace-content')
        target?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        target?.classList.add('citation-highlight')
        if (target) window.setTimeout(() => target.classList.remove('citation-highlight'), 2200)
      }, 0)
    } catch (error) {
      setExtractionStatus('error')
      setExtractionMessage(error instanceof Error ? error.message : 'Saved content could not be opened.')
    }
  }

  const renderCitations = (citations: ChatMessage['citations']) => (
    <div className="citation-list" aria-label="Sources">
      <span className="citation-label">Sources</span>
      {citations.map((citation, index) => {
        const material = materials.find((item) => item.resource_id === citation.source_id)
        const sourceName = material?.original_filename || 'Material'
        const location = citation.page ? `Page ${citation.page}`
          : citation.slide ? `Slide ${citation.slide}`
            : citation.image ? `Image ${citation.image}`
              : citation.start_seconds !== undefined
                ? `${formatTimestamp(citation.start_seconds)}–${formatTimestamp(citation.end_seconds)}` : 'Source'
        const label = `${sourceName} · ${location}`
        if (material?.source_type === 'video' && material.source_url) {
          const videoId = new URL(material.source_url).searchParams.get('v')
          return <button className="citation-chip" type="button" key={`${citation.chunk_id || index}`} onClick={() => videoId && setVideoPreview({ title: label, embedUrl: `https://www.youtube-nocookie.com/embed/${videoId}?start=${Math.floor(citation.start_seconds || 0)}&autoplay=1` })}>▶ {label}</button>
        }
        const referenceType = citation.page ? 'page' : citation.slide ? 'slide' : 'image'
        const referenceNumber = citation.page || citation.slide || citation.image
        return <button className="citation-chip" type="button" key={`${citation.chunk_id || index}`} onClick={() => material && void openMaterial(material, referenceType, referenceNumber)}>↗ {label}</button>
      })}
    </div>
  )

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDragging(false)
    const file = event.dataTransfer.files[0]
    if (file) selectFile(file)
  }

  const openAdmin = async () => {
    if (currentUser?.role !== 'admin') return
    setAdminOpen(true)
    setAdminBusy(true)
    setAdminError('')
    try {
      const response = await apiFetch(`${API_BASE_URL}/admin/users`)
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'Admin metrics could not be loaded.')
      setAdminUsers(payload.users || [])
    } catch (error) {
      setAdminError(error instanceof Error ? error.message : 'Admin metrics could not be loaded.')
    } finally {
      setAdminBusy(false)
    }
  }

  const quizAnsweredCount = quiz?.questions.filter((question) => {
    const answer = quizAnswers[question.question_id]
    return question.question_type === 'short_answer' ? Boolean(answer?.text.trim()) : Boolean(answer?.indices.length)
  }).length || 0
  const quizComplete = Boolean(quiz && quizAnsweredCount === quiz.questions.length)

  if (!authReady) {
    return <div className="app-loading"><span className="loading-spinner" /><p>Opening your study space…</p></div>
  }

  if (!currentUser) return (
    <AuthScreen
      onAuthenticated={authenticated}
      theme={theme}
      onToggleTheme={toggleTheme}
      palette={palette}
      onPaletteChange={setPalette}
    />
  )

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="brand" type="button" onClick={() => navigateTo('materials')} aria-label="Open materials workspace">
          <BookLogo />
          <span className="brand-copy"><strong>LearnFlow<span className="brand-accent"> AI</span></strong><small>Study workspace</small></span>
        </button>
        <nav className="nav-links" aria-label="Main navigation">
          {WORKSPACE_VIEWS.map((view) => (
            <button
              className={activeView === view.id ? 'active' : ''}
              type="button"
              aria-current={activeView === view.id ? 'page' : undefined}
              onClick={() => navigateTo(view.id)}
              key={view.id}
            >
              {view.label}
            </button>
          ))}
        </nav>
        <div className="profile-cluster">
          <PalettePicker palette={palette} onChange={setPalette} />
          <ThemeToggle theme={theme} onToggle={toggleTheme} />
          {currentUser.role === 'admin' && <button className="admin-link" type="button" onClick={() => void openAdmin()}>Admin</button>}
          <button className="export-button" type="button" disabled={exportBusy} onClick={() => void exportAccountData()}>{exportBusy ? 'Exporting…' : 'Export data'}</button>
          <div className="profile-button" aria-label="Signed-in profile">
            <span className="profile-avatar">{currentUser.display_name.slice(0, 1).toUpperCase()}</span>
            <span className="profile-copy"><strong>{currentUser.display_name}</strong><small>{currentUser.email}</small></span>
          </div>
          <button className="signout-button" type="button" onClick={() => void logout()}>Sign out</button>
        </div>
      </header>

      {videoPreview && (
        <div className="preview-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setVideoPreview(null) }}>
          <section className="video-preview" role="dialog" aria-modal="true" aria-label="YouTube citation preview">
            <div className="section-heading"><div><p className="eyebrow">CITED MOMENT</p><h2>{videoPreview.title}</h2></div><button className="secondary-button" type="button" onClick={() => setVideoPreview(null)}>Close</button></div>
            <iframe src={videoPreview.embedUrl} title={videoPreview.title} allow="autoplay; encrypted-media; picture-in-picture" allowFullScreen />
          </section>
        </div>
      )}

      <main className="page-main">
        {adminOpen && (
          <div className="admin-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setAdminOpen(false) }}>
          <section className="admin-panel" role="dialog" aria-modal="true" aria-label="Administrator usage panel">
            <div className="section-heading">
              <div><p className="eyebrow">PRIVACY-SAFE OPERATIONS</p><h2>Admin overview</h2></div>
              <button className="secondary-button" type="button" onClick={() => setAdminOpen(false)}>Close</button>
            </div>
            <p className="admin-privacy">Only anonymized account labels and aggregate activity are shown. Names, email addresses, material names, content, questions, answers, and transcripts stay private.</p>
            {adminError && <p className="history-alert" role="alert">{adminError}</p>}
            {adminBusy ? <p>Loading account usage…</p> : (
              <div className="admin-users">
                {adminUsers.map((item) => (
                  <article className="admin-user" key={item.user_id}>
                    <div><strong>{item.display_name}</strong><small>{item.email_hint} · {item.role}</small></div>
                    <dl>
                      <div><dt>Materials</dt><dd>{item.material_count}</dd></div>
                      <div><dt>Storage</dt><dd>{formatFileSize(item.storage_bytes)}</dd></div>
                      <div><dt>Est. input tokens</dt><dd>{item.input_tokens.toLocaleString()}</dd></div>
                      <div><dt>Est. output tokens</dt><dd>{item.output_tokens.toLocaleString()}</dd></div>
                      <div><dt>Chat requests</dt><dd>{item.chat_requests.toLocaleString()}</dd></div>
                      <div><dt>Quiz requests</dt><dd>{item.quiz_requests.toLocaleString()}</dd></div>
                      <div><dt>Summary requests</dt><dd>{item.summary_requests.toLocaleString()}</dd></div>
                      <div><dt>Active time</dt><dd>{Math.round(item.active_seconds / 60)} min</dd></div>
                    </dl>
                    <p>Explored domains: {item.explored_domains.length ? item.explored_domains.map((domain) => `${domain.label} (${domain.count})`).join(', ') : 'None yet'}</p>
                    <small>Last active {formatDate(item.last_seen_at)}</small>
                  </article>
                ))}
              </div>
            )}
          </section>
          </div>
        )}
        <section className="welcome-section workspace-page" hidden={activeView !== 'materials'}>
          <div>
            <p className="eyebrow">YOUR PERSONAL LEARNING SPACE</p>
            <h1>Turn curiosity into <span>momentum.</span></h1>
            <p className="welcome-copy">
              Bring your learning materials together and build a clearer path to understanding.
            </p>
          </div>
          <div className="welcome-book" aria-hidden="true">
            <BookLogo />
            <span>Read. Ask. Practice.</span>
          </div>
        </section>

        <section className="dashboard-grid workspace-page" id="workspace" hidden={activeView !== 'materials'}>
          <article className={`upload-card ${isDragging ? 'is-dragging' : ''}`}>
            <div className="card-heading">
              <SectionGlyph kind="materials" />
              <div>
                <p className="card-kicker">START HERE</p>
                <h2>Add your first material</h2>
              </div>
            </div>
            <p className="card-description">
              Bring in a presentation, document, or video to set up your learning workspace.
            </p>
            <div
              className="drop-zone"
              role="button"
              tabIndex={0}
              aria-label="Choose or drop a learning material"
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') fileInputRef.current?.click() }}
              onDragEnter={(event) => { event.preventDefault(); setIsDragging(true) }}
              onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = 'copy' }}
              onDragLeave={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setIsDragging(false)
              }}
              onDrop={handleDrop}
            >
              <input
                ref={fileInputRef}
                className="file-input"
                type="file"
                accept={ACCEPTED_FILE_TYPES}
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  if (file) selectFile(file)
                  event.target.value = ''
                }}
              />
              <div className="drop-icon" aria-hidden="true">⇧</div>
              <strong>{isDragging ? 'Release to add your file' : 'Drop a file anywhere in this area'}</strong>
              <p className="drop-hint">or click to browse</p>
            </div>
            <p className="file-note">PDF, PPTX, PNG or JPEG · Up to 100 MB</p>
            <p className="file-note">
              Intelligent text extraction{ocrRuntime?.execution === 'google_cloud' ? ' (enhanced cloud mode)' : ''} and visual analysis enabled
            </p>
            <div className="source-divider"><span>or use a video link</span></div>
            <div className="youtube-row">
              <input
                type="url"
                value={youtubeUrl}
                onChange={(event) => setYoutubeUrl(event.target.value)}
                placeholder="https://www.youtube.com/watch?v=…"
                aria-label="YouTube video URL"
              />
              <button type="button" onClick={() => void importYoutube()} disabled={status === 'uploading'}>
                Add link
              </button>
            </div>
            <p className="file-note">Public YouTube videos with available captions</p>
            {selectedFile && (
              <div className="selected-file">
                <div className="file-summary">
                  <span className="file-type-badge">{fileExtension(selectedFile.name).slice(1).toUpperCase()}</span>
                  <div>
                    <strong title={selectedFile.name}>{selectedFile.name}</strong>
                    <span>{formatFileSize(selectedFile.size)} · {selectedFile.type || 'File'}</span>
                  </div>
                </div>
                {status === 'uploading' && <div className="progress-track"><div style={{ width: `${progress}%` }} /></div>}
                <button className="submit-upload" type="button" onClick={uploadFile} disabled={status === 'uploading' || status === 'success'}>
                  {status === 'uploading' ? `${progress}%` : status === 'success' ? 'Uploaded' : 'Upload material'}
                </button>
                {uploadedResourceId && (
                  <>
                    {(extractionStatus === 'queued' || extractionStatus === 'processing') && (
                      <div className="progress-track" aria-label={`Processing ${processingProgress}%`}>
                        <div style={{ width: `${processingProgress}%` }} />
                      </div>
                    )}
                    <button
                      className="extract-button"
                      type="button"
                      onClick={retryProcessing}
                      disabled={extractionStatus !== 'error'}
                    >
                      {extractionStatus === 'queued' ? 'Queued for processing'
                        : extractionStatus === 'processing' ? `Processing · ${processingProgress}%`
                          : extractionStatus === 'success' ? 'Processing complete ✓'
                            : 'Retry processing'}
                    </button>
                  </>
                )}
              </div>
            )}
            {activeYoutubeUrl && (
              <div className="selected-file">
                <div className="file-summary">
                  <span className="file-type-badge">YT</span>
                  <div><strong>{materials.find((item) => item.resource_id === uploadedResourceId)?.original_filename || 'YouTube video'}</strong><span>Saved YouTube source</span></div>
                </div>
                {(extractionStatus === 'queued' || extractionStatus === 'processing') && (
                  <div className="progress-track"><div style={{ width: `${processingProgress}%` }} /></div>
                )}
                <button className="extract-button" type="button" onClick={retryProcessing} disabled={extractionStatus !== 'error'}>
                  {extractionStatus === 'queued' ? 'Queued for captions'
                    : extractionStatus === 'processing' ? `Processing captions · ${processingProgress}%`
                      : extractionStatus === 'success' ? 'Timestamped captions ready'
                        : 'Retry caption import'}
                </button>
              </div>
            )}
            {message && <p className={`upload-message ${status}`}>{message}</p>}
            {extractionMessage && <p className={`upload-message ${extractionStatus}`}>{extractionMessage}</p>}
          </article>

          <article className="workspace-card" id="workspace-content">
            <div className="workspace-header">
              <div className="section-title"><SectionGlyph kind="materials" /><div>
                <p className="card-kicker">LEARNING WORKSPACE</p>
                <h2>Your space is ready</h2>
              </div></div>
              <span className="status-pill"><span /> {extractedContent.length > 0 ? 'Content ready' : 'Empty'}</span>
            </div>
            {extractedContent.length > 0 ? (
              <div className="extracted-content">
                {extractedContent.map((unit) => (
                  <section id={`content-${uploadedResourceId}-${unit.reference_type}-${unit.reference_number}`} className={`content-unit ${!unit.has_text ? 'content-unit-empty' : ''}`} key={`${unit.reference_type}-${unit.reference_number}`}>
                    <div className="content-unit-heading">
                      <span>{unit.reference_type === 'timestamp'
                        ? `${formatTimestamp(unit.start_seconds)}–${formatTimestamp(unit.end_seconds)}`
                        : `${unit.reference_type === 'page' ? 'Page' : unit.reference_type === 'slide' ? 'Slide' : 'Image'} ${unit.reference_number}`}</span>
                      <small>{unit.extraction_method ? 'AI text analysis' : 'Document text'}</small>
                      {!unit.has_text && <small>No extractable text</small>}
                    </div>
                    <p>{(unit.literal_text ?? unit.text) || 'No readable text could be detected in this section.'}</p>
                    {unit.visual_description && <div className="visual-insight"><strong>Visual interpretation</strong><MarkdownAnswer>{unit.visual_description}</MarkdownAnswer></div>}
                  </section>
                ))}
              </div>
            ) : (
              <div className="empty-state">
                <div className="empty-illustration" aria-hidden="true">
                  <span className="paper paper-back" />
                  <span className="paper paper-front">✧</span>
                </div>
                <h3>Nothing here yet</h3>
                <p>Your extracted learning material will appear here.</p>
              </div>
            )}
          </article>
        </section>

        <section className="chat-section workspace-page" id="chat" hidden={activeView !== 'chat'}>
          <div className="section-heading">
            <div className="section-title"><SectionGlyph kind="chat" /><div><p className="eyebrow">GROUNDED STUDY HELP</p><h2>Ask about your materials</h2></div></div>
            <button className="secondary-button" type="button" onClick={startNewChat}>New chat</button>
          </div>
          <div className="chat-layout">
            <aside className="source-picker">
              <SelectionToolbar title="Use ready materials" availableIds={chatBulkMaterials.map((item) => item.resource_id)} selectedIds={chatSourceIds} totalCount={readyMaterials.length} limit={30} onToggle={toggleAllChatSources} />
              {readyMaterials.length ? (
                readyMaterials.map((material) => (
                  <label className={`source-option${chatSourceIds.includes(material.resource_id) ? ' selected' : ''}`} key={material.resource_id}>
                    <input
                      type="checkbox"
                      checked={chatSourceIds.includes(material.resource_id)}
                      disabled={!chatSourceIds.includes(material.resource_id) && (chatSourceIds.length >= 30 || (material.source_type === 'video' && readyMaterials.filter((item) => item.source_type === 'video' && chatSourceIds.includes(item.resource_id)).length >= 10))}
                      onChange={(event) => updateChatSource(material, event.target.checked)}
                    />
                    {material.thumbnail_url && <img src={material.thumbnail_url} alt="" />}
                    <span title={material.original_filename}><small>{material.source_type === 'video' ? 'YouTube' : material.source_type.toUpperCase()}</small>{material.original_filename}</span>
                  </label>
                ))
              ) : <p className="history-muted">Finish processing a material to use it in chat.</p>}
              {Object.entries(chatVideoScopes).filter(([sourceId]) => chatSourceIds.includes(sourceId)).map(([sourceId, scope]) => {
                const video = materials.find((item) => item.resource_id === sourceId)
                return (
                  <div className="video-chat-scope" key={sourceId}>
                    <label htmlFor={`video-playback-${sourceId}`}>
                      <span>{video?.original_filename || 'Video'}</span>
                      Through <strong>{formatTimestamp(scope.playback)}</strong>
                    </label>
                    <input
                      id={`video-playback-${sourceId}`}
                      type="range"
                      min="0"
                      max={Math.max(1, Math.ceil(scope.duration))}
                      value={Math.min(scope.playback, Math.max(1, Math.ceil(scope.duration)))}
                      onChange={(event) => setChatVideoScopes((current) => ({ ...current, [sourceId]: { ...scope, playback: Number(event.target.value) } }))}
                      disabled={scope.duration <= 0}
                    />
                  </div>
                )
              })}
              {Object.keys(chatVideoScopes).length > 0 && <small className="scope-help">Each video defaults to its full transcript. Move its slider left to limit context to what you watched.</small>}
            </aside>
            <div className="chat-panel">
              <div className="chat-messages" aria-live="polite" aria-busy={chatBusy} ref={chatMessagesRef}>
                {chatMessages.length ? chatMessages.map((item) => (
                  <article className={`chat-message ${item.role}`} key={item.message_id}>
                    <strong>{item.role === 'user' ? 'You' : 'LearnFlow AI'}</strong>
                    {item.role === 'assistant' ? <MarkdownAnswer>{item.content}</MarkdownAnswer> : <p>{item.content}</p>}
                    {item.citations.length > 0 && renderCitations(item.citations)}
                  </article>
                )) : (
                  <div className="chat-empty"><SectionGlyph kind="chat" /><h3>Start with a question</h3><p>Answers use only the ready materials you select.</p></div>
                )}
                {chatBusy && <article className="chat-message assistant thinking-message"><strong>LearnFlow AI</strong><div className="thinking-dots" aria-label="Reading selected materials and composing an answer"><span /><span /><span /></div><small>Reading your selected sources and checking citations…</small></article>}
              </div>
              {chatError && <p className="history-alert" role="alert">{chatError}</p>}
              <form className="chat-compose" onSubmit={(event) => { event.preventDefault(); void askChat() }}>
                <textarea
                  value={chatQuestion}
                  onChange={(event) => setChatQuestion(event.target.value)}
                  onKeyDown={handleChatKeyDown}
                  placeholder="Ask a question about your selected materials…"
                  aria-label="Question for LearnFlow AI"
                  maxLength={4000}
                />
                <button type="submit" disabled={chatBusy || chatSourceIds.length === 0 || !chatQuestion.trim() || Object.entries(chatVideoScopes).some(([sourceId, scope]) => chatSourceIds.includes(sourceId) && scope.duration <= 0)}>
                  {chatBusy ? 'Thinking…' : 'Ask'}
                </button>
              </form>
            </div>
          </div>
        </section>

        <section className="summary-section workspace-page" id="summary" hidden={activeView !== 'summary'}>
          <div className="section-heading">
            <div className="section-title"><SectionGlyph kind="summary" /><div><p className="eyebrow">GROUNDED OVERVIEW</p><h2>Summarize your materials</h2></div></div>
            {summaryResult && <button className="secondary-button" type="button" onClick={() => { setSummaryResult(null); setSummaryError('') }}>Clear summary</button>}
          </div>
          <div className="summary-layout">
            <aside className="source-picker">
              <SelectionToolbar title="Summary materials" availableIds={summaryBulkIds} selectedIds={summarySourceIds} totalCount={readyMaterials.length} limit={12} onToggle={(select) => setSummarySourceIds(select ? summaryBulkIds : [])} disabled={summaryBusy} />
              {readyMaterials.length ? readyMaterials.map((material) => (
                <label className={`source-option${summarySourceIds.includes(material.resource_id) ? ' selected' : ''}`} key={material.resource_id}>
                  <input
                    type="checkbox"
                    checked={summarySourceIds.includes(material.resource_id)}
                    disabled={summaryBusy || (!summarySourceIds.includes(material.resource_id) && summarySourceIds.length >= 12)}
                    onChange={(event) => setSummarySourceIds((current) => event.target.checked
                      ? [...new Set([...current, material.resource_id])].slice(0, 12)
                      : current.filter((id) => id !== material.resource_id))}
                  />
                  {material.thumbnail_url && <img src={material.thumbnail_url} alt="" />}
                  <span title={material.original_filename}><small>{material.source_type === 'video' ? 'YouTube' : material.source_type.toUpperCase()}</small>{material.original_filename}</span>
                </label>
              )) : <p className="history-muted">Finish processing a material to summarize it.</p>}
              <div className="quiz-controls">
                <label htmlFor="summary-style">Summary style</label>
                <select id="summary-style" value={summaryStyle} onChange={(event) => setSummaryStyle(event.target.value as typeof summaryStyle)} disabled={summaryBusy}>
                  <option value="concise">Concise overview</option>
                  <option value="detailed">Detailed summary</option>
                  <option value="study_guide">Study guide</option>
                </select>
                <button type="button" onClick={() => void generateSummary()} disabled={summaryBusy || summarySourceIds.length === 0}>{summaryBusy ? 'Summarizing…' : 'Generate summary'}</button>
                <small>Select up to 12 materials. The summary is generated only from sampled, citation-preserving evidence.</small>
              </div>
            </aside>
            <article className="summary-panel" aria-live="polite" aria-busy={summaryBusy}>
              {summaryError && <p className="history-alert" role="alert">{summaryError}</p>}
              {summaryBusy && <div className="summary-loading"><div className="thinking-dots" aria-hidden="true"><span /><span /><span /></div><p>Building a grounded summary from your selected sources…</p></div>}
              {!summaryBusy && summaryResult && <><MarkdownAnswer>{summaryResult.summary}</MarkdownAnswer>{renderCitations(summaryResult.citations)}</>}
              {!summaryBusy && !summaryResult && <div className="chat-empty"><SectionGlyph kind="summary" /><h3>Create a source-backed summary</h3><p>Choose your materials and the level of detail you need.</p></div>}
            </article>
          </div>
        </section>

        <section className="quiz-section workspace-page" id="quiz" hidden={activeView !== 'quiz'}>
          <div className="section-heading">
            <div className="section-title"><SectionGlyph kind="quiz" /><div><p className="eyebrow">GROUNDED PRACTICE</p><h2>Test what you learned</h2></div></div>
            <button className="secondary-button" type="button" onClick={startNewQuiz}>New quiz</button>
          </div>
          <div className="quiz-layout">
            <aside className="source-picker">
              <SelectionToolbar title="Quiz materials" availableIds={quizBulkIds} selectedIds={quizSourceIds} totalCount={readyMaterials.length} limit={12} onToggle={(select) => setQuizSourceIds(select ? quizBulkIds : [])} disabled={quizBusy} />
              {readyMaterials.length ? (
                readyMaterials.map((material) => (
                  <label className={`source-option${quizSourceIds.includes(material.resource_id) ? ' selected' : ''}`} key={material.resource_id}>
                    <input
                      type="checkbox"
                      checked={quizSourceIds.includes(material.resource_id)}
                      disabled={quizBusy || (!quizSourceIds.includes(material.resource_id) && quizSourceIds.length >= 12)}
                      onChange={(event) => setQuizSourceIds((current) => event.target.checked
                        ? [...new Set([...current, material.resource_id])].slice(0, 12)
                        : current.filter((id) => id !== material.resource_id))}
                    />
                    {material.thumbnail_url && <img src={material.thumbnail_url} alt="" />}
                    <span title={material.original_filename}><small>{material.source_type === 'video' ? 'YouTube' : material.source_type.toUpperCase()}</small>{material.original_filename}</span>
                  </label>
                ))
              ) : <p className="history-muted">Finish processing a material to generate a quiz.</p>}
              <div className="quiz-controls">
                <label htmlFor="quiz-count">Questions</label>
                <input id="quiz-count" type="number" min="1" max="20" value={quizCount} onChange={(event) => setQuizCount(Math.min(20, Math.max(1, Number(event.target.value) || 1)))} disabled={quizBusy} />
                <label htmlFor="quiz-type">Answer type</label>
                <select id="quiz-type" value={quizType} onChange={(event) => setQuizType(event.target.value as typeof quizType)} disabled={quizBusy}>
                  <option value="mixed">Mixed types</option>
                  <option value="single_answer">Single answer</option>
                  <option value="multiple_answer">Multiple answers</option>
                  <option value="short_answer">Short answer</option>
                </select>
                <button type="button" onClick={() => void generateQuiz()} disabled={quizBusy || quizSourceIds.length === 0}>
                  {quizBusy && !quiz ? 'Generating…' : 'Generate quiz'}
                </button>
                <small>Select up to 12 processed materials. Answers stay hidden until submission.</small>
              </div>
            </aside>
            <div className="quiz-panel" aria-live="polite">
              {quizError && <p className="history-alert" role="alert">{quizError}</p>}
              {quiz ? (
                <>
                  {quizResult && (
                    <div className="quiz-score">
                      <strong>{quizResult.score}/{quizResult.total}</strong>
                      <span>{quizResult.score === quizResult.total ? 'Perfect score' : 'Quiz complete'}</span>
                    </div>
                  )}
                  <div className="quiz-questions">
                    {quiz.questions.map((question, questionIndex) => {
                      const result = quizResult?.questions.find((item) => item.question_id === question.question_id)
                      return (
                        <article className="quiz-question" key={question.question_id}>
                          <p className="quiz-number">QUESTION {questionIndex + 1}</p>
                          <h3>{question.question}</h3>
                          <p className="question-type">{question.question_type === 'single_answer' ? 'Choose one' : question.question_type === 'multiple_answer' ? `Choose all that apply${question.max_selections ? ` · up to ${question.max_selections}` : ''}` : 'Write a short answer'}</p>
                          {question.question_type === 'short_answer' ? (
                            <textarea
                              className="short-answer"
                              value={quizAnswers[question.question_id]?.text || ''}
                              onChange={(event) => setQuizAnswers((current) => ({ ...current, [question.question_id]: { indices: [], text: event.target.value } }))}
                              placeholder="Type your answer…"
                              maxLength={2000}
                              disabled={Boolean(quizResult)}
                            />
                          ) : (
                            <div className="quiz-options">
                              {question.options.map((option, optionIndex) => {
                                const selected = quizAnswers[question.question_id]?.indices.includes(optionIndex) || false
                                const optionState = result
                                  ? result.correct_option_indices.includes(optionIndex) ? 'correct'
                                    : result.selected_option_indices.includes(optionIndex) ? 'incorrect' : ''
                                  : ''
                                return (
                                  <label className={`quiz-option ${optionState}`} key={`${question.question_id}-${optionIndex}`}>
                                    <input
                                      type={question.question_type === 'single_answer' ? 'radio' : 'checkbox'}
                                      name={question.question_id}
                                      checked={selected}
                                      onChange={() => setQuizAnswers((current) => {
                                        const previous = current[question.question_id]?.indices || []
                                        const indices = question.question_type === 'single_answer'
                                          ? [optionIndex]
                                          : previous.includes(optionIndex) ? previous.filter((index) => index !== optionIndex)
                                            : previous.length >= question.max_selections ? previous : [...previous, optionIndex]
                                        return { ...current, [question.question_id]: { indices, text: '' } }
                                      })}
                                      disabled={Boolean(quizResult)}
                                    />
                                    <span>{option}</span>
                                  </label>
                                )
                              })}
                            </div>
                          )}
                          {result && (
                            <div className={`quiz-explanation ${result.correct ? 'correct' : 'incorrect'}`}>
                              <strong>{result.correct ? 'Correct' : 'Not quite'}</strong>
                              <p>{result.explanation}</p>
                              {!result.correct && result.question_type === 'short_answer' && result.accepted_answers.length > 0 && <p className="accepted-answer">Accepted answer: {result.accepted_answers[0]}</p>}
                              {renderCitations(result.citations)}
                            </div>
                          )}
                        </article>
                      )
                    })}
                  </div>
                  {!quizResult && (
                    <button
                      className="quiz-submit"
                      type="button"
                      onClick={() => void submitQuiz()}
                      disabled={quizBusy || !quizComplete}
                    >
                      {quizBusy ? 'Scoring…' : `Submit ${quizAnsweredCount}/${quiz.questions.length} answered`}
                    </button>
                  )}
                </>
              ) : (
                <div className="chat-empty"><SectionGlyph kind="quiz" /><h3>Build a grounded quiz</h3><p>Select ready materials and choose how many questions you want.</p></div>
              )}
            </div>
          </div>
        </section>

        <section className="interview-section workspace-page" id="interview" hidden={activeView !== 'interview'}>
          <div className="section-heading">
            <div className="section-title"><SectionGlyph kind="interview" /><div>
              <p className="eyebrow">AI MOCK INTERVIEW & PREPARATION</p>
              <h2>Realistic Interview Practice</h2>
            </div></div>
            {(interviewSession || interviewReport) && (
              <button
                className="secondary-button"
                type="button"
                onClick={resetInterview}
              >
                + New interview
              </button>
            )}
          </div>

          {!interviewSession && !interviewReport && (
            <div className="interview-setup-layout">
              <div className="interview-setup-form">
                <div className="interview-form-group">
                  <label htmlFor="interview-role">
                    <strong>Target Job Role / Title</strong>
                    <span className="field-hint">Specify the role you are preparing for</span>
                  </label>
                  <input
                    id="interview-role"
                    type="text"
                    className="interview-input"
                    value={interviewJobRole}
                    onChange={(e) => setInterviewJobRole(e.target.value)}
                    placeholder="e.g. Senior Frontend Engineer, Product Manager, Data Scientist"
                  />
                  <div className="role-chips">
                    {['Frontend Engineer', 'Full Stack Developer', 'Backend Engineer', 'Data Scientist', 'Product Manager', 'DevOps Specialist'].map((role) => (
                      <button
                        key={role}
                        type="button"
                        className="role-chip"
                        onClick={() => setInterviewJobRole(role)}
                      >
                        {role}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="interview-form-row">
                  <div className="interview-form-group">
                    <label htmlFor="interview-type">
                      <strong>Interview Style</strong>
                      <span className="field-hint">Focus areas for questions</span>
                    </label>
                    <select
                      id="interview-type"
                      className="interview-select"
                      value={interviewType}
                      onChange={(e) => setInterviewType(e.target.value)}
                    >
                      <option value="mixed">Comprehensive (Technical + Behavioral)</option>
                      <option value="technical">Technical Depth & Architecture</option>
                      <option value="behavioral">Behavioral (STAR Method)</option>
                      <option value="hr">HR, Leadership & Culture Fit</option>
                    </select>
                  </div>

                  <div className="interview-form-group">
                    <label htmlFor="interview-count">
                      <strong>Question Count</strong>
                      <span className="field-hint">Target session length</span>
                    </label>
                    <select
                      id="interview-count"
                      className="interview-select"
                      value={interviewQuestionCount}
                      onChange={(e) => setInterviewQuestionCount(Number(e.target.value))}
                    >
                      <option value={3}>3 Questions (~5 minutes)</option>
                      <option value={5}>5 Questions (~12 minutes)</option>
                      <option value={7}>7 Questions (~20 minutes)</option>
                      <option value={10}>10 Questions (~30 minutes)</option>
                    </select>
                  </div>
                </div>

                <div className="interview-form-group">
                  <label htmlFor="interview-desc">
                    <strong>Job Description / Key Requirements (Optional)</strong>
                    <span className="field-hint">Paste details from the job posting to personalize questions</span>
                  </label>
                  <textarea
                    id="interview-desc"
                    className="interview-textarea"
                    rows={3}
                    value={interviewJobDesc}
                    onChange={(e) => setInterviewJobDesc(e.target.value)}
                    placeholder="Paste key responsibilities, required skills, or tech stack..."
                  />
                </div>

                <div className="interview-form-group">
                  <label htmlFor="interview-resume">
                    <strong>Your Resume / Background (Optional)</strong>
                    <span className="field-hint">Share your past projects or skills so questions test your background</span>
                  </label>
                  <textarea
                    id="interview-resume"
                    className="interview-textarea"
                    rows={3}
                    value={interviewResume}
                    onChange={(e) => setInterviewResume(e.target.value)}
                    placeholder="Paste your key experiences, projects, or background..."
                  />
                </div>

                {readyMaterials.length > 0 && (
                  <div className="interview-form-group">
                    <div className="interview-material-heading">
                      <strong>Link Library Materials (Optional)</strong>
                      <span className="field-hint">AI will incorporate concepts from your uploaded study materials</span>
                    </div>
                    <div className="interview-material-selector">
                      <SelectionToolbar title="Ready materials" availableIds={interviewBulkIds} selectedIds={interviewSourceIds} totalCount={readyMaterials.length} limit={5} onToggle={(select) => setInterviewSourceIds(select ? interviewBulkIds : [])} disabled={interviewBusy} />
                      {readyMaterials.map((mat) => (
                        <label key={mat.resource_id} className={`interview-mat-option${interviewSourceIds.includes(mat.resource_id) ? ' selected' : ''}`}>
                          <input
                            type="checkbox"
                            checked={interviewSourceIds.includes(mat.resource_id)}
                            disabled={interviewBusy || (!interviewSourceIds.includes(mat.resource_id) && interviewSourceIds.length >= 5)}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setInterviewSourceIds((prev) => [...new Set([...prev, mat.resource_id])].slice(0, 5))
                              } else {
                                setInterviewSourceIds((prev) => prev.filter((id) => id !== mat.resource_id))
                              }
                            }}
                          />
                          <span>{mat.original_filename}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                )}

                {interviewError && <p className="history-alert" role="alert">⚠ {interviewError}</p>}

                <button
                  type="button"
                  className="start-interview-btn"
                  onClick={() => void startInterview()}
                  disabled={!interviewJobRole.trim() || interviewBusy}
                >
                  {interviewBusy ? 'Setting up your interview…' : 'Start Mock Interview →'}
                </button>
              </div>

              <div className="interview-setup-guide">
                <div className="guide-card">
                  <h3>How Mock Interviews Work</h3>
                  <div className="guide-steps">
                    <div className="guide-step">
                      <span className="guide-num">01</span>
                      <div>
                        <strong>Adaptive Questions</strong>
                        <p>The AI acts as an interviewer, asking one tailored question at a time and evaluating responses in context.</p>
                      </div>
                    </div>
                    <div className="guide-step">
                      <span className="guide-num">02</span>
                      <div>
                        <strong>Natural Dialogue</strong>
                        <p>Answer at your own pace. You can structure your points, give examples, and provide technical depth.</p>
                      </div>
                    </div>
                    <div className="guide-step">
                      <span className="guide-num">03</span>
                      <div>
                        <strong>Actionable Scorecard</strong>
                        <p>When completed, receive a detailed evaluation with overall scores (0-10), strengths, and ideal answers.</p>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {interviewSession && !interviewReport && (
            <div className="interview-live-layout">
              <div className="interview-live-header">
                <div className="interview-meta-pills">
                  <span className="pill-badge role">{interviewSession.job_role}</span>
                  <span className="pill-badge type">
                    {interviewSession.interview_type === 'technical' ? 'Technical Focus'
                      : interviewSession.interview_type === 'behavioral' ? 'Behavioral (STAR)'
                      : interviewSession.interview_type === 'hr' ? 'HR & Culture'
                      : 'Comprehensive Mixed'}
                  </span>
                  <span className="pill-badge count">
                    {interviewSession.status === 'completed'
                      ? 'Interview Completed ✓'
                      : `Question ${Math.min(interviewSession.questions_asked + 1, interviewSession.question_count)} of ${interviewSession.question_count}`}
                  </span>
                </div>
                <div className="interview-header-actions">
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => void fetchInterviewReport()}
                    disabled={interviewReportBusy || interviewBusy}
                  >
                    {interviewReportBusy ? 'Generating evaluation…' : 'Finish & Generate Report →'}
                  </button>
                </div>
              </div>

              <div className="interview-chat-window" ref={interviewMessagesRef}>
                {interviewMessages.map((msg, idx) => (
                  <div key={idx} className={`interview-msg-row ${msg.role}`}>
                    <div className="interview-msg-avatar">
                      {msg.role === 'interviewer' ? '🎙' : currentUser?.display_name?.slice(0, 1).toUpperCase() || 'U'}
                    </div>
                    <div className="interview-msg-bubble">
                      <div className="interview-msg-header">
                        <strong>{msg.role === 'interviewer' ? 'AI Interviewer' : currentUser?.display_name || 'You'}</strong>
                      </div>
                      <p className="interview-msg-text">{msg.content}</p>
                    </div>
                  </div>
                ))}
                {interviewBusy && (
                  <div className="interview-msg-row interviewer">
                    <div className="interview-msg-avatar">🎙</div>
                    <div className="interview-msg-bubble thinking">
                      <div className="thinking-dots">
                        <span /><span /><span />
                      </div>
                      <small>Interviewer is evaluating and formulating the next question…</small>
                    </div>
                  </div>
                )}
              </div>

              {interviewError && <p className="history-alert" role="alert">⚠ {interviewError}</p>}

              {interviewSession.status === 'active' ? (
                <div className="interview-compose-box">
                  <textarea
                    className="interview-compose-input"
                    value={interviewInput}
                    onChange={(e) => setInterviewInput(e.target.value)}
                    onKeyDown={handleInterviewKeyDown}
                    placeholder="Type your response here... (Press Enter to send, Shift+Enter for a new line)"
                    rows={3}
                    disabled={interviewBusy}
                  />
                  <div className="interview-compose-actions">
                    <button
                      type="button"
                      className="conclude-early-btn"
                      onClick={() => void fetchInterviewReport()}
                      disabled={interviewReportBusy || interviewBusy}
                    >
                      {interviewReportBusy ? 'Evaluating…' : 'Wrap up & score'}
                    </button>
                    <button
                      type="button"
                      className="send-response-btn"
                      onClick={() => void sendInterviewReply()}
                      disabled={!interviewInput.trim() || interviewBusy}
                    >
                      {interviewBusy ? 'Sending…' : 'Send Answer →'}
                    </button>
                  </div>
                </div>
              ) : (
                <div className="interview-completed-banner">
                  <div className="banner-content">
                    <h3>Interview Completed!</h3>
                    <p>You have answered all questions. Click below to generate your performance scorecard and feedback report.</p>
                  </div>
                  <button
                    type="button"
                    className="generate-report-btn"
                    onClick={() => void fetchInterviewReport()}
                    disabled={interviewReportBusy}
                  >
                    {interviewReportBusy ? 'Generating Evaluation…' : 'View Evaluation Report →'}
                  </button>
                </div>
              )}
            </div>
          )}

          {interviewReport && (
            <div className="interview-report-view">
              <div className="report-hero-card">
                <div className="report-score-ring">
                  <div className="score-number">{interviewReport.overall_score}</div>
                  <div className="score-denom">/ 10</div>
                  <div className="score-verdict">
                    {interviewReport.overall_score >= 8 ? 'Exceptional' : interviewReport.overall_score >= 6 ? 'Competent' : 'Needs Practice'}
                  </div>
                </div>
                <div className="report-hero-copy">
                  <div className="report-role-tag">Performance Scorecard · {interviewSession?.job_role || 'Target Role'}</div>
                  <h3>Executive Assessment</h3>
                  <p>{interviewReport.summary}</p>
                  <div className="report-action-buttons">
                    <button type="button" className="secondary-button" onClick={resetInterview}>
                      + Practice Another Role
                    </button>
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => setInterviewReport(null)}
                    >
                      Review Transcript
                    </button>
                  </div>
                </div>
              </div>

              <div className="report-breakdown-grid">
                <div className="report-pillar-card strengths">
                  <h4><span className="pillar-icon">✓</span> Key Strengths</h4>
                  <ul>
                    {interviewReport.strengths?.map((item, idx) => (
                      <li key={idx}>{item}</li>
                    ))}
                  </ul>
                </div>

                <div className="report-pillar-card improvements">
                  <h4><span className="pillar-icon">▲</span> Areas for Growth</h4>
                  <ul>
                    {interviewReport.areas_for_improvement?.map((item, idx) => (
                      <li key={idx}>{item}</li>
                    ))}
                  </ul>
                </div>

                <div className="report-pillar-card recommendations">
                  <h4><span className="pillar-icon">★</span> Actionable Recommendations</h4>
                  <ul>
                    {interviewReport.recommendations?.map((item, idx) => (
                      <li key={idx}>{item}</li>
                    ))}
                  </ul>
                </div>
              </div>

              <div className="report-questions-section">
                <h3>Question-by-Question Breakdown</h3>
                <div className="report-questions-list">
                  {interviewReport.questions?.map((q, idx) => (
                    <article key={idx} className="report-question-card">
                      <div className="report-q-header">
                        <span className="report-q-num">Question {idx + 1}</span>
                        <span className={`report-q-score score-${Math.round(q.score)}`}>
                          Score: {q.score} / 10
                        </span>
                      </div>
                      <h4 className="report-q-prompt">{q.question}</h4>
                      <div className="report-q-answer">
                        <strong>Your Response:</strong>
                        <p>{q.user_answer || '(No response provided)'}</p>
                      </div>
                      <div className="report-q-feedback">
                        <strong>Evaluator Feedback:</strong>
                        <p>{q.feedback}</p>
                      </div>
                      {q.ideal_answer_hint && (
                        <div className="report-q-ideal">
                          <strong>Ideal Approach & Key Points:</strong>
                          <p>{q.ideal_answer_hint}</p>
                        </div>
                      )}
                    </article>
                  ))}
                </div>
              </div>
            </div>
          )}
        </section>

        <section className="history-section workspace-page" id="history" hidden={activeView !== 'history'}>
          <div className="section-heading">
            <div className="section-title"><SectionGlyph kind="history" /><div><p className="eyebrow">LOCAL DATABASE</p><h2>History and cleanup</h2></div></div>
            <button className="secondary-button" type="button" onClick={() => void loadHistories()} disabled={historyBusy}>
              {historyBusy ? 'Refreshing…' : 'Refresh history'}
            </button>
          </div>
          <div className="history-tabs" role="tablist" aria-label="History type">
            <button type="button" role="tab" aria-selected={historyTab === 'processed'} className={historyTab === 'processed' ? 'selected' : ''} onClick={() => setHistoryTab('processed')}>
              Materials <span>{materials.length}</span>
            </button>
            <button type="button" role="tab" aria-selected={historyTab === 'chat'} className={historyTab === 'chat' ? 'selected' : ''} onClick={() => setHistoryTab('chat')}>
              Chat history <span>{chatSessions.length}</span>
            </button>
            <button type="button" role="tab" aria-selected={historyTab === 'interview'} className={historyTab === 'interview' ? 'selected' : ''} onClick={() => setHistoryTab('interview')}>
              Interviews <span>{interviewHistory.length}</span>
            </button>
          </div>
          {historyMessage && <p className="history-alert" role="status">{historyMessage}</p>}
          {historyTab === 'processed' ? (
            <div className="history-list">
              {materials.length ? materials.map((material) => {
                const processingError = material.error || material.processing_job?.error
                return (
                  <article className="history-card" key={material.resource_id}>
                    {material.thumbnail_url && <img className="history-thumbnail" src={material.thumbnail_url} alt="" />}
                    <div className="history-card-main">
                      <div className="history-title-row"><h3 title={material.original_filename}>{material.original_filename}</h3><span className={`history-status ${material.status}`}>{material.status}</span></div>
                      <p>{material.source_type === 'video' ? 'YouTube video' : material.source_type === 'pdf' ? 'PDF document' : material.source_type === 'pptx' ? 'Presentation' : 'Image'} · Added {formatDate(material.created_at)}</p>
                      {processingError && <p className="history-error">Processing error: {processingError}</p>}
                    </div>
                    <div className="history-actions">
                      {material.status === 'ready' && <button className="secondary-button" type="button" onClick={() => void openMaterial(material)}>{material.source_type === 'video' ? 'View transcript' : 'View content'}</button>}
                      {material.status === 'failed' && <button className="secondary-button" type="button" onClick={() => void retryHistoryMaterial(material)}>Retry</button>}
                      <button className="delete-button" type="button" disabled={material.status === 'processing'} onClick={() => void deleteMaterial(material)}>
                        {material.status === 'processing' ? 'Processing…' : 'Delete data'}
                      </button>
                    </div>
                  </article>
                )
              }) : <p className="history-muted">No materials have been added yet. Upload a file or add a YouTube link to get started.</p>}
            </div>
          ) : historyTab === 'interview' ? (
            <div className="history-list">
              {interviewHistory.length ? interviewHistory.map((session) => (
                <article className="history-card" key={session.interview_id}>
                  <div className="history-card-main">
                    <div className="history-title-row">
                      <h3>{session.job_role}</h3>
                      <span className={`history-status ${session.status === 'reported' ? 'ready' : session.status === 'completed' ? 'processing' : 'uploaded'}`}>
                        {session.status === 'reported' ? 'Report ready' : session.status === 'completed' ? 'Completed' : 'In progress'}
                      </span>
                    </div>
                    <p>{session.interview_type === 'technical' ? 'Technical' : session.interview_type === 'behavioral' ? 'Behavioral' : session.interview_type === 'hr' ? 'HR' : 'Mixed'} interview · {session.question_count} questions · {formatDate(session.created_at || '')}</p>
                  </div>
                  <div className="history-actions">
                    <button className="secondary-button" type="button" onClick={() => void openInterviewSession(session.interview_id)}>
                      {session.status === 'reported' ? 'View report' : 'Open interview'}
                    </button>
                    <button className="delete-button" type="button" onClick={() => void deleteInterviewSession(session.interview_id)}>Delete</button>
                  </div>
                </article>
              )) : <p className="history-muted">Your completed interviews will appear here.</p>}
            </div>
          ) : (
            <div className="history-list">
              {chatSessions.length ? chatSessions.map((session) => (
                <article className="history-card" key={session.session_id}>
                  <button className="history-open" type="button" onClick={() => void openChatSession(session.session_id)}>
                    <h3>{session.title}</h3>
                    <p>{session.message_count} messages · Updated {formatDate(session.updated_at)}</p>
                  </button>
                  <div className="history-actions">
                    <button className="secondary-button" type="button" onClick={() => void openChatSession(session.session_id)}>Open</button>
                    <button className="delete-button" type="button" onClick={() => void deleteChatSession(session)}>Delete chat</button>
                  </div>
                </article>
              )) : <p className="history-muted">Completed chat turns will be saved here.</p>}
            </div>
          )}
          <p className="history-footnote">Deleting a material removes its stored content, search index, and AI embeddings. Your data stays on this device only.</p>
        </section>

        <section className="how-section workspace-page" id="how-it-works" hidden={activeView !== 'materials'}>
          <p className="eyebrow">A SIMPLE START</p>
          <div className="steps">
            <div className="step">
              <span className="step-number">01</span>
              <div><h3>Bring it in</h3><p>Add the material you want to learn from.</p></div>
            </div>
            <div className="step">
              <span className="step-number">02</span>
              <div><h3>Make sense of it</h3><p>Build a focused space for your ideas.</p></div>
            </div>
            <div className="step">
              <span className="step-number">03</span>
              <div><h3>Keep moving</h3><p>Return whenever you are ready to learn.</p></div>
            </div>
          </div>
        </section>
      </main>

      <footer>LearnFlow AI <span>·</span> Your learning, in flow.</footer>
    </div>
  )
}

export default App
