import { useCallback, useEffect, useRef, useState } from 'react'
import type { DragEvent } from 'react'
import './App.css'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const MAX_FILE_SIZE = 100 * 1024 * 1024
const ACCEPTED_EXTENSIONS = ['.pdf', '.pptx', '.png', '.jpg', '.jpeg']
const ACCEPTED_FILE_TYPES = ACCEPTED_EXTENSIONS.join(',')

type UploadStatus = 'idle' | 'ready' | 'uploading' | 'success' | 'error'
type ExtractionStatus = 'idle' | 'queued' | 'processing' | 'success' | 'error'

type ExtractedUnit = {
  reference_type: 'page' | 'slide' | 'image' | 'timestamp'
  reference_number: number
  text: string
  has_text: boolean
  ocr_applied: boolean
  extraction_method: string
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
  processing_job: { status: string; error: string | null } | null
}

type ChatMessage = {
  message_id: string
  role: 'user' | 'assistant'
  content: string
  citations: Array<{ source_id: string; source_type: string; page?: number; slide?: number; image?: number }>
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

function App() {
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
  const [chatBusy, setChatBusy] = useState(false)
  const [chatError, setChatError] = useState('')
  const [historyTab, setHistoryTab] = useState<'processed' | 'chat'>('processed')
  const [historyMessage, setHistoryMessage] = useState('')
  const [historyBusy, setHistoryBusy] = useState(false)

  const loadHistories = useCallback(async () => {
    setHistoryBusy(true)
    try {
      const [materialsResponse, chatsResponse] = await Promise.all([
        fetch(`${API_BASE_URL}/materials`),
        fetch(`${API_BASE_URL}/chat/history`),
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
      setHistoryMessage('')
    } catch (error) {
      setHistoryMessage(error instanceof Error ? error.message : 'History could not be loaded.')
    } finally {
      setHistoryBusy(false)
    }
  }, [])

  useEffect(() => { void loadHistories() }, [loadHistories])

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
          : 'Uploaded securely. Local text extraction and OCR have been queued automatically.')
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
    const response = await fetch(`${API_BASE_URL}/materials/${resourceId}/content`)
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
      : `Processed ${payload.content.length} ${units} with text extraction and OCR.`)
    void loadHistories()
  }, [loadHistories])

  const importYoutube = async () => {
    if (!youtubeUrl.trim() || status === 'uploading') return
    setSelectedFile(null)
    setStatus('uploading')
    setMessage('Validating the YouTube link…')
    setExtractedContent([])
    setExtractionStatus('idle')
    try {
      const response = await fetch(`${API_BASE_URL}/materials/youtube`, {
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
        const response = await fetch(`${API_BASE_URL}/materials/${uploadedResourceId}/status`)
        const payload = await response.json()
        if (!response.ok) throw new Error(payload.detail || 'Processing status is unavailable.')
        if (!active) return
        const job = payload.processing_job
        setProcessingProgress(job?.progress_percent || 0)
        if (payload.status === 'ready' || job?.status === 'completed') {
          await loadExtractedContent(uploadedResourceId)
        } else if (payload.status === 'failed' || job?.status === 'failed') {
          setExtractionStatus('error')
          setExtractionMessage(job?.error || payload.error || 'Local processing failed. You can retry it.')
          void loadHistories()
        } else if (job?.status === 'processing') {
          setExtractionStatus('processing')
          setExtractionMessage(job.progress_total
            ? `Extracting text and scanning visual content locally… ${job.progress_current} of ${job.progress_total}`
            : activeYoutubeUrl ? 'Retrieving timestamped YouTube captions…' : 'Starting local text extraction and OCR…')
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
  }, [uploadedResourceId, extractionStatus, loadExtractedContent, activeYoutubeUrl])

  const retryProcessing = async () => {
    if (!uploadedResourceId || extractionStatus !== 'error') return
    setExtractionStatus('queued')
    setProcessingProgress(0)
    setExtractionMessage('Re-queuing local text extraction and OCR…')
    try {
      const response = await fetch(`${API_BASE_URL}/materials/${uploadedResourceId}/process`, {
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
    setChatBusy(true)
    setChatError('')
    try {
      const response = await fetch(`${API_BASE_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: chatSessionId,
          question,
          allowed_source_ids: chatSourceIds,
        }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'The answer could not be generated.')
      setChatMessages((current) => [
        ...current,
        { message_id: crypto.randomUUID(), role: 'user', content: question, citations: [], created_at: new Date().toISOString() },
        { message_id: crypto.randomUUID(), role: 'assistant', content: payload.answer, citations: payload.citations || [], created_at: new Date().toISOString() },
      ])
      setChatQuestion('')
      void loadHistories()
    } catch (error) {
      setChatError(error instanceof Error ? error.message : 'The answer could not be generated.')
    } finally {
      setChatBusy(false)
    }
  }

  const startNewChat = () => {
    setChatSessionId(crypto.randomUUID().replaceAll('-', ''))
    setChatMessages([])
    setChatError('')
    setChatQuestion('')
  }

  const openChatSession = async (sessionId: string) => {
    try {
      const response = await fetch(`${API_BASE_URL}/chat/history/${sessionId}`)
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'This chat could not be opened.')
      setChatSessionId(payload.session_id)
      setChatMessages(payload.messages || [])
      const readyIds = new Set(materials.filter((item) => item.status === 'ready').map((item) => item.resource_id))
      setChatSourceIds((payload.source_ids || []).filter((id: string) => readyIds.has(id)))
      setChatError('')
      document.getElementById('chat')?.scrollIntoView({ behavior: 'smooth' })
    } catch (error) {
      setHistoryMessage(error instanceof Error ? error.message : 'This chat could not be opened.')
    }
  }

  const deleteChatSession = async (session: ChatSession) => {
    if (!window.confirm(`Delete this chat history?\n\n“${session.title}”`)) return
    try {
      const response = await fetch(`${API_BASE_URL}/chat/history/${session.session_id}`, { method: 'DELETE' })
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
      const response = await fetch(`${API_BASE_URL}/materials/${material.resource_id}`, { method: 'DELETE' })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'The material could not be deleted.')
      setChatSourceIds((current) => current.filter((id) => id !== material.resource_id))
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
      const response = await fetch(`${API_BASE_URL}/materials/${material.resource_id}/process`, { method: 'POST' })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'The material could not be queued for retry.')
      await loadHistories()
      setHistoryMessage('Processing retry queued. The history will update when it finishes.')
    } catch (error) {
      setHistoryMessage(error instanceof Error ? error.message : 'The material could not be queued for retry.')
    }
  }

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDragging(false)
    const file = event.dataTransfer.files[0]
    if (file) selectFile(file)
  }

  return (
    <div className="app-shell">
      <nav className="topbar" aria-label="Main navigation">
        <a className="brand" href="/">
          <span className="brand-mark" aria-hidden="true">L</span>
          <span>LearnFlow<span className="brand-accent"> AI</span></span>
        </a>
        <div className="nav-links">
          <a className="active" href="#workspace">Workspace</a>
          <a href="#chat">Study chat</a>
          <a href="#history">History</a>
          <a href="#how-it-works">How it works</a>
        </div>
        <button className="profile-button" type="button" aria-label="Open profile menu">
          <span className="profile-avatar">S</span>
          <span className="profile-name">Student</span>
          <span className="chevron" aria-hidden="true">⌄</span>
        </button>
      </nav>

      <main>
        <section className="welcome-section">
          <div>
            <p className="eyebrow">YOUR PERSONAL LEARNING SPACE</p>
            <h1>Turn curiosity into <span>momentum.</span></h1>
            <p className="welcome-copy">
              Bring your learning materials together and build a clearer path to understanding.
            </p>
          </div>
          <div className="welcome-orbit" aria-hidden="true">
            <div className="orbit orbit-one" />
            <div className="orbit orbit-two" />
            <div className="orbit-core">✦</div>
            <span className="orbit-dot dot-one">✦</span>
            <span className="orbit-dot dot-two">•</span>
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
              <button className="upload-button" type="button" onClick={() => fileInputRef.current?.click()}>
                <span aria-hidden="true">＋</span> Choose a file
              </button>
              <p className="drop-hint">or drag and drop it here</p>
            </div>
            <p className="file-note">PDF, PPTX, PNG or JPEG · Up to 100 MB</p>
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
                        : extractionStatus === 'processing' ? `Processing locally · ${processingProgress}%`
                          : extractionStatus === 'success' ? 'Text + OCR complete'
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
                  <div><strong>YouTube video</strong><span title={activeYoutubeUrl}>{activeYoutubeUrl}</span></div>
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

          <article className="workspace-card">
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
                  <section className={`content-unit ${!unit.has_text ? 'content-unit-empty' : ''}`} key={`${unit.reference_type}-${unit.reference_number}`}>
                    <div className="content-unit-heading">
                      <span>{unit.reference_type === 'timestamp'
                        ? `${formatTimestamp(unit.start_seconds)}–${formatTimestamp(unit.end_seconds)}`
                        : `${unit.reference_type === 'page' ? 'Page' : unit.reference_type === 'slide' ? 'Slide' : 'Image'} ${unit.reference_number}`}</span>
                      <small>{unit.extraction_method.replace('+', ' + ')}</small>
                      {!unit.has_text && <small>No extractable text</small>}
                    </div>
                    <p>{unit.text || 'No readable text was found after OCR.'}</p>
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
              {materials.filter((item) => item.status === 'ready' && item.source_type !== 'video').length ? (
                materials.filter((item) => item.status === 'ready' && item.source_type !== 'video').map((material) => (
                  <label className="source-option" key={material.resource_id}>
                    <input
                      type="checkbox"
                      checked={chatSourceIds.includes(material.resource_id)}
                      onChange={(event) => setChatSourceIds((current) => event.target.checked
                        ? [...new Set([...current, material.resource_id])]
                        : current.filter((id) => id !== material.resource_id))}
                    />
                    <span title={material.original_filename}>{material.original_filename}</span>
                  </label>
                ))
              ) : <p className="history-muted">Finish processing a document or image to use it in chat.</p>}
              <p className="history-muted">Video chat will be available with timestamp-aware playback.</p>
            </aside>
            <div className="chat-panel">
              <div className="chat-messages" aria-live="polite">
                {chatMessages.length ? chatMessages.map((item) => (
                  <article className={`chat-message ${item.role}`} key={item.message_id}>
                    <strong>{item.role === 'user' ? 'You' : 'LearnFlow AI'}</strong>
                    <p>{item.content}</p>
                    {item.citations.length > 0 && <small>
                      Sources: {item.citations.map((citation, index) => {
                        const sourceName = materials.find((material) => material.resource_id === citation.source_id)?.original_filename || 'Material'
                        const location = citation.page ? ` · page ${citation.page}`
                          : citation.slide ? ` · slide ${citation.slide}`
                            : citation.image ? ` · image ${citation.image}` : ''
                        return `${index ? '; ' : ''}${sourceName}${location}`
                      }).join('')}
                    </small>}
                  </article>
                )) : (
                  <div className="chat-empty"><span aria-hidden="true">✦</span><h3>Start with a question</h3><p>Answers use only the ready materials you select.</p></div>
                )}
              </div>
              {chatError && <p className="history-alert" role="alert">{chatError}</p>}
              <form className="chat-compose" onSubmit={(event) => { event.preventDefault(); void askChat() }}>
                <textarea
                  value={chatQuestion}
                  onChange={(event) => setChatQuestion(event.target.value)}
                  placeholder="Ask a question about your selected materials…"
                  aria-label="Question for LearnFlow AI"
                  maxLength={4000}
                />
                <button type="submit" disabled={chatBusy || chatSourceIds.length === 0 || !chatQuestion.trim()}>
                  {chatBusy ? 'Thinking…' : 'Ask'}
                </button>
              </form>
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
                    <div className="history-card-main">
                      <div className="history-title-row"><h3 title={material.original_filename}>{material.original_filename}</h3><span className={`history-status ${material.status}`}>{material.status}</span></div>
                      <p>{material.source_type === 'video' ? material.source_url || 'YouTube video' : material.source_type.toUpperCase()} · Added {formatDate(material.created_at)}</p>
                      {processingError && <p className="history-error">Processing error: {processingError}</p>}
                    </div>
                    <div className="history-actions">
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
