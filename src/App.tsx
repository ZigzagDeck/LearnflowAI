import { useRef, useState } from 'react'
import type { DragEvent } from 'react'
import './App.css'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const MAX_FILE_SIZE = 100 * 1024 * 1024
const ACCEPTED_EXTENSIONS = ['.pdf', '.pptx', '.png', '.jpg', '.jpeg']
const ACCEPTED_FILE_TYPES = ACCEPTED_EXTENSIONS.join(',')

type UploadStatus = 'idle' | 'ready' | 'uploading' | 'success' | 'error'
type ExtractionStatus = 'idle' | 'extracting' | 'success' | 'error'

type ExtractedUnit = {
  reference_type: 'page' | 'slide' | 'image'
  reference_number: number
  text: string
  has_text: boolean
  ocr_applied: boolean
  extraction_method: 'native' | 'ocr' | 'native+ocr'
}

function formatFileSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function fileExtension(fileName: string) {
  return fileName.slice(fileName.lastIndexOf('.')).toLowerCase()
}

function App() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [status, setStatus] = useState<UploadStatus>('idle')
  const [progress, setProgress] = useState(0)
  const [message, setMessage] = useState('')
  const [isDragging, setIsDragging] = useState(false)
  const [uploadedDocumentId, setUploadedDocumentId] = useState('')
  const [extractionStatus, setExtractionStatus] = useState<ExtractionStatus>('idle')
  const [extractionMessage, setExtractionMessage] = useState('')
  const [extractedContent, setExtractedContent] = useState<ExtractedUnit[]>([])

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
    setUploadedDocumentId('')
    setExtractionStatus('idle')
    setExtractionMessage('')
    setExtractedContent([])
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
        setUploadedDocumentId(response.stored_filename)
        setMessage(response.deduplicated
          ? 'This material already exists. Its saved processing result will be reused.'
          : 'Uploaded securely. You can now process its text and images.')
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

  const extractMaterial = async () => {
    if (!uploadedDocumentId || !selectedFile || extractionStatus === 'extracting') return

    setExtractionStatus('extracting')
    setExtractionMessage('Extracting text and scanning images locally with OCR...')
    setExtractedContent([])

    try {
      const response = await fetch(`${API_BASE_URL}/materials/${encodeURIComponent(uploadedDocumentId)}/extract`, {
        method: 'POST',
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.detail || 'The text could not be extracted.')
      setExtractedContent(payload.content)
      setExtractionStatus('success')
      const extension = fileExtension(selectedFile.name)
      const units = extension === '.pdf' ? 'pages' : extension === '.pptx' ? 'slides' : 'image'
      setExtractionMessage(payload.cached
        ? `Loaded the saved result for ${payload.content.length} ${units}; OCR was not repeated.`
        : `Processed ${payload.content.length} ${units} with text extraction and OCR.`)
    } catch (error) {
      setExtractionStatus('error')
      setExtractionMessage(error instanceof Error ? error.message : 'The text could not be extracted.')
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
                {uploadedDocumentId && (
                  <button className="extract-button" type="button" onClick={extractMaterial} disabled={extractionStatus === 'extracting'}>
                    {extractionStatus === 'extracting' ? 'Processing locally...' : extractionStatus === 'success' ? 'Processing complete' : 'Extract text + OCR'}
                  </button>
                )}
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
                      <span>{unit.reference_type === 'page' ? 'Page' : unit.reference_type === 'slide' ? 'Slide' : 'Image'} {unit.reference_number}</span>
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
