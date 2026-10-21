import { useCallback, useEffect, useRef, useState } from 'react'
import type { DragEvent, FormEvent, KeyboardEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import './App.css'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const MAX_FILE_SIZE = 100 * 1024 * 1024
const ACCEPTED_EXTENSIONS = ['.pdf', '.pptx', '.png', '.jpg', '.jpeg']
const ACCEPTED_FILE_TYPES = ACCEPTED_EXTENSIONS.join(',')
const AUTH_STORAGE_KEY = 'learnflow.auth.token'

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

function MarkdownAnswer({ children }: { children: string }) {
  return (
    <div className="markdown-answer">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children: label, ...props }) => <a {...props} target="_blank" rel="noreferrer">{label}</a>,
        }}
      >{children}</ReactMarkdown>
    </div>
  )
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

function AuthScreen({ onAuthenticated }: { onAuthenticated: (token: string, user: UserProfile) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
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
      if (!response.ok) throw new Error(payload.detail || 'Authentication failed.')
      onAuthenticated(payload.token, payload.user)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Authentication failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-card">
        <BookLogo small />
        <p className="eyebrow">YOUR PRIVATE STUDY SPACE</p>
        <h1>{mode === 'login' ? 'Welcome back' : 'Create your account'}</h1>
        <p>Sign in to keep materials, transcripts, conversations, and quizzes separated by account.</p>
        <form onSubmit={(event) => void submit(event)}>
          {mode === 'register' && (
            <label>Display name<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} autoComplete="name" required /></label>
          )}
          <label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" required /></label>
          <label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} required /></label>
          {mode === 'register' && <small>Use at least 8 characters, one uppercase letter, and one number.</small>}
          {error && <p className="form-error" role="alert">{error}</p>}
          <button type="submit" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}</button>
        </form>
        <button className="auth-switch" type="button" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError('') }}>
          {mode === 'login' ? 'New here? Create an account' : 'Already registered? Sign in'}
        </button>
      </section>
    </main>
  )
}

function App() {
  const [authToken, setAuthToken] = useState(() => window.localStorage.getItem(AUTH_STORAGE_KEY) || '')
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(null)
  const [authReady, setAuthReady] = useState(() => !window.localStorage.getItem(AUTH_STORAGE_KEY))
  const [adminOpen, setAdminOpen] = useState(false)
  const [adminUsers, setAdminUsers] = useState<AdminUserMetric[]>([])
  const [adminBusy, setAdminBusy] = useState(false)
  const [adminError, setAdminError] = useState('')
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
  const [historyTab, setHistoryTab] = useState<'processed' | 'chat'>('processed')
  const [historyMessage, setHistoryMessage] = useState('')
  const [historyBusy, setHistoryBusy] = useState(false)
  const [ocrRuntime, setOcrRuntime] = useState<OcrRuntime | null>(null)
  const [bedrockRuntime, setBedrockRuntime] = useState<BedrockRuntime | null>(null)
  const ocrProviderLabel = ocrRuntime?.provider === 'google_document_ai'
    ? 'Google Document AI'
    : ocrRuntime?.provider === 'rapidocr' ? 'RapidOCR' : 'configured provider'

  const apiFetch = useCallback((url: string, options: RequestInit = {}) => {
    const headers = new Headers(options.headers)
    if (authToken) headers.set('Authorization', `Bearer ${authToken}`)
    return fetch(url, { ...options, headers })
  }, [authToken])

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

  const loadHistories = useCallback(async (silent = false) => {
    if (!silent) setHistoryBusy(true)
    try {
      const [materialsResponse, chatsResponse] = await Promise.all([
        apiFetch(`${API_BASE_URL}/materials`),
        apiFetch(`${API_BASE_URL}/chat/history`),
      ])
      const materialsPayload = await materialsResponse.json()
      const chatsPayload = await chatsResponse.json()
      if (!materialsResponse.ok) throw new Error(materialsPayload.detail || 'Processed data history could not be loaded.')
      if (!chatsResponse.ok) throw new Error(chatsPayload.detail || 'Chat history could not be loaded.')
      const nextMaterials: MaterialRecord[] = materialsPayload.materials || []
      setMaterials(nextMaterials)
      setChatSessions(chatsPayload.sessions || [])
      setChatSourceIds((current) => current.length
        ? current.filter((id) => nextMaterials.some((item) => item.resource_id === id && item.status === 'ready'))
        : nextMaterials.filter((item) => item.status === 'ready' && item.source_type !== 'video').map((item) => item.resource_id))
      setQuizSourceIds((current) => current.length
        ? current.filter((id) => nextMaterials.some((item) => item.resource_id === id && item.status === 'ready'))
        : nextMaterials.filter((item) => item.status === 'ready').slice(0, 12).map((item) => item.resource_id))
      setSummarySourceIds((current) => current.length
        ? current.filter((id) => nextMaterials.some((item) => item.resource_id === id && item.status === 'ready'))
        : nextMaterials.filter((item) => item.status === 'ready').slice(0, 12).map((item) => item.resource_id))
      setHistoryMessage('')
    } catch (error) {
      setHistoryMessage(error instanceof Error ? error.message : 'History could not be loaded.')
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
          ? 'This material already exists. Its saved processing result will be reused.'
          : `Uploaded securely. Text extraction, ${ocrProviderLabel} OCR${bedrockRuntime?.visual_understanding_enabled ? ', and Bedrock visual understanding' : ''} have been queued automatically.`)
        void loadHistories()
      } else {
        let detail = 'The upload could not be completed. Please try again.'
        try {
          detail = JSON.parse(request.responseText).detail || detail
        } catch {
          // Keep the clear generic message when the server response is not JSON.
        }
        setStatus('error')
        setMessage(detail)
      }
    })
    request.addEventListener('error', () => {
      setStatus('error')
      setMessage('The backend could not be reached. Check that it is running on port 8000.')
    })
    setStatus('uploading')
    setProgress(0)
    setMessage('Uploading securely to your local workspace...')
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
      : `Processed ${payload.content.length} ${units} with local text extraction and ${ocrProviderLabel} OCR.`)
    void loadHistories()
  }, [apiFetch, loadHistories, ocrProviderLabel])

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
            ? `Extracting text, running ${ocrProviderLabel} OCR${bedrockRuntime?.visual_understanding_enabled ? ', and interpreting relevant visuals with Bedrock' : ''}… ${job.progress_current} of ${job.progress_total}`
            : activeYoutubeUrl ? 'Retrieving timestamped YouTube captions…' : `Starting local text extraction and ${ocrProviderLabel} OCR…`)
        } else {
          setExtractionStatus('queued')
          setExtractionMessage('Waiting for the local processing worker…')
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
  }, [apiFetch, uploadedResourceId, extractionStatus, loadExtractedContent, loadHistories, activeYoutubeUrl, ocrProviderLabel, bedrockRuntime?.visual_understanding_enabled])

  const retryProcessing = async () => {
    if (!uploadedResourceId || extractionStatus !== 'error') return
    setExtractionStatus('queued')
    setProcessingProgress(0)
    setExtractionMessage(`Re-queuing local text extraction and ${ocrProviderLabel} OCR…`)
    try {
      const response = await apiFetch(`${API_BASE_URL}/materials/${uploadedResourceId}/process`, {
        method: 'POST',
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'The material could not be re-queued.')
      setExtractionMessage('Waiting for the local processing worker…')
    } catch (error) {
      setExtractionStatus('error')
      setExtractionMessage(error instanceof Error ? error.message : 'The material could not be re-queued.')
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
      setQuizError(error instanceof Error ? error.message : 'The quiz could not be scored.')
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
      if (!response.ok) throw new Error(payload.detail || 'The summary could not be generated.')
      setSummaryResult(payload)
    } catch (error) {
      setSummaryError(error instanceof Error ? error.message : 'The summary could not be generated.')
    } finally {
      setSummaryBusy(false)
    }
  }

  const openChatSession = async (sessionId: string) => {
    try {
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

  if (!currentUser) return <AuthScreen onAuthenticated={authenticated} />

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#workspace" aria-label="LearnFlow AI workspace">
          <BookLogo />
          <span>LearnFlow<span className="brand-accent"> AI</span></span>
        </a>
        <div className="profile-cluster">
          {currentUser.role === 'admin' && <button className="admin-link" type="button" onClick={() => void openAdmin()}>Admin</button>}
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

      <main>
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
        <section className="welcome-section">
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

        <section className="dashboard-grid" id="workspace">
          <article className={`upload-card ${isDragging ? 'is-dragging' : ''}`}>
            <div className="card-heading">
              <div className="icon-badge upload-icon" aria-hidden="true">↑</div>
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
            {ocrRuntime && (
              <p className="file-note">
                OCR: {ocrProviderLabel} · {ocrRuntime.execution === 'google_cloud' ? 'Google Cloud' : 'Local'} · local fallback {ocrRuntime.local_fallback_enabled ? 'on' : 'off'}
              </p>
            )}
            {bedrockRuntime?.visual_understanding_enabled && <p className="file-note">Visual understanding: {bedrockRuntime.model} · up to {bedrockRuntime.visual_max_units_per_material} relevant visuals per material</p>}
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
                      {extractionStatus === 'queued' ? 'Queued for OCR'
                        : extractionStatus === 'processing' ? `${ocrProviderLabel} OCR · ${processingProgress}%`
                          : extractionStatus === 'success' ? `Text + OCR${bedrockRuntime?.visual_understanding_enabled ? ' + visual' : ''} complete`
                            : 'Retry text + OCR'}
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
              <div>
                <p className="card-kicker">LEARNING WORKSPACE</p>
                <h2>Your space is ready</h2>
              </div>
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
                      <small>{unit.extraction_method.replace('+', ' + ')}</small>
                      {!unit.has_text && <small>No extractable text</small>}
                    </div>
                    <p>{(unit.literal_text ?? unit.text) || 'No readable text was found after OCR.'}</p>
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

        <section className="chat-section" id="chat">
          <div className="section-heading">
            <div><p className="eyebrow">GROUNDED STUDY HELP</p><h2>Ask about your materials</h2></div>
            <button className="secondary-button" type="button" onClick={startNewChat}>New chat</button>
          </div>
          <div className="chat-layout">
            <aside className="source-picker">
              <h3>Use ready materials</h3>
              {materials.filter((item) => item.status === 'ready').length ? (
                materials.filter((item) => item.status === 'ready').map((material) => (
                  <label className="source-option" key={material.resource_id}>
                    <input
                      type="checkbox"
                      checked={chatSourceIds.includes(material.resource_id)}
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
                  <div className="chat-empty"><span aria-hidden="true">✦</span><h3>Start with a question</h3><p>Answers use only the ready materials you select.</p></div>
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

        <section className="summary-section" id="summary">
          <div className="section-heading">
            <div><p className="eyebrow">GROUNDED OVERVIEW</p><h2>Summarize your materials</h2></div>
            {summaryResult && <button className="secondary-button" type="button" onClick={() => { setSummaryResult(null); setSummaryError('') }}>Clear summary</button>}
          </div>
          <div className="summary-layout">
            <aside className="source-picker">
              <h3>Summary materials</h3>
              {materials.filter((item) => item.status === 'ready').length ? materials.filter((item) => item.status === 'ready').map((material) => (
                <label className="source-option" key={material.resource_id}>
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
              {!summaryBusy && !summaryResult && <div className="chat-empty"><span aria-hidden="true">≡</span><h3>Create a source-backed summary</h3><p>Choose your materials and the level of detail you need.</p></div>}
            </article>
          </div>
        </section>

        <section className="quiz-section" id="quiz">
          <div className="section-heading">
            <div><p className="eyebrow">GROUNDED PRACTICE</p><h2>Test what you learned</h2></div>
            <button className="secondary-button" type="button" onClick={startNewQuiz}>New quiz</button>
          </div>
          <div className="quiz-layout">
            <aside className="source-picker">
              <h3>Quiz materials</h3>
              {materials.filter((item) => item.status === 'ready').length ? (
                materials.filter((item) => item.status === 'ready').map((material) => (
                  <label className="source-option" key={material.resource_id}>
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
                <div className="chat-empty"><span aria-hidden="true">✓</span><h3>Build a grounded quiz</h3><p>Select ready materials and choose how many questions you want.</p></div>
              )}
            </div>
          </div>
        </section>

        <section className="history-section" id="history">
          <div className="section-heading">
            <div><p className="eyebrow">LOCAL DATABASE</p><h2>History and cleanup</h2></div>
            <button className="secondary-button" type="button" onClick={() => void loadHistories()} disabled={historyBusy}>
              {historyBusy ? 'Refreshing…' : 'Refresh history'}
            </button>
          </div>
          <div className="history-tabs" role="tablist" aria-label="History type">
            <button type="button" role="tab" aria-selected={historyTab === 'processed'} className={historyTab === 'processed' ? 'selected' : ''} onClick={() => setHistoryTab('processed')}>
              Processed data <span>{materials.length}</span>
            </button>
            <button type="button" role="tab" aria-selected={historyTab === 'chat'} className={historyTab === 'chat' ? 'selected' : ''} onClick={() => setHistoryTab('chat')}>
              Chat history <span>{chatSessions.length}</span>
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
                      <p>{material.source_type === 'video' ? 'YouTube transcript' : material.source_type.toUpperCase()} · Added {formatDate(material.created_at)}</p>
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
              }) : <p className="history-muted">No processed materials are saved in the local database.</p>}
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
          <p className="history-footnote">Deleting a material removes its database record, cached extracted text, chunks, and embeddings. Chat history is stored locally in this app’s SQLite database.</p>
        </section>

        <section className="how-section" id="how-it-works">
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
