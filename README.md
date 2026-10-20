# LearnFlow AI

LearnFlow AI is a learning workspace being built in small milestones. The current milestone contains:

- A React + TypeScript + Vite frontend
- A Python + FastAPI backend with health, local material-upload, and extraction endpoints
- Local OCR enrichment for PDF pages, PPTX embedded images, and standalone PNG/JPEG images
- A local SQLite resource registry with content-hash deduplication and cached extraction results
- A restart-safe SQLite processing queue with one CPU-heavy extraction job at a time
- Automatic UI polling, per-page/slide progress, failure details, and explicit retry
- A homepage with drag-and-drop upload, extraction controls, and a readable learning workspace

End-to-end RAG, transcription, summaries, quizzes, and Bedrock integration are **not implemented yet**. Grounded-chat contracts and orchestration boundaries exist, but no production retriever, source authorizer, or model provider is wired into the application.

## Folder guide

- `src/` - The frontend source code. `App.tsx` contains the page structure, while `App.css` and `index.css` contain its styles.
- `backend/` - The Python API. `main.py` defines the FastAPI application, CORS settings, validation, upload, and extraction endpoints.
- `backend/extraction.py` - PyMuPDF and python-pptx extraction with OCR enrichment and page/slide/image provenance.
- `backend/ocr.py` - Lazy local RapidOCR adapter backed by ONNX Runtime.
- `backend/resource_store.py` - SQLite metadata, status, SHA-256 deduplication, and versioned extraction cache.
- `backend/processing.py` - One-job-at-a-time extraction coordinator with durable progress and safe failures.
- `backend/worker.py` - Local queue worker; it is the only process that loads the OCR model.
- `backend/uploads/` - Created automatically when the first upload succeeds. Local uploaded files are kept here and are ignored by Git.
- `public/` - Static files that Vite serves directly.
- `package.json` - Frontend commands and JavaScript dependencies.
- `requirements.txt` - Python backend dependencies.
- `.env.example` - Safe placeholder names for future configuration. It contains no real secrets.

The upload endpoint currently accepts PDF, PPTX, PNG, JPG, and JPEG files up to 100 MB by default. The UI intentionally lists only formats that can be processed now. Set `LEARNFLOW_MAX_UPLOAD_SIZE_MB` before starting the backend to change that development limit.

Exact duplicate uploads reuse the existing resource and stored file. Extraction results are cached with a pipeline version, so unchanged resources do not repeat OCR while future extractor upgrades can invalidate stale results safely. Metadata is stored in `backend/data/learnflow.db` by default; override it with `LEARNFLOW_DATABASE_PATH`. Uploaded files default to `backend/uploads`; override that shared API/worker path with `LEARNFLOW_UPLOAD_DIR`.

PDF and PPTX extraction is limited to 500 pages/slides and 2 million extracted characters. OCR runs outside web requests in a dedicated local worker. SQLite claiming guarantees that only one heavy job runs at once, even if another worker is started. Jobs retain progress and failures across restarts; work with no update for 15 minutes is treated as interrupted and re-queued. Change that window with `LEARNFLOW_JOB_STALE_SECONDS`.

## Prerequisites

Install these separately if they are not already installed: Node.js 20+, Python 3.10+, and Git. This project does not install software or change Windows settings for you.

## Windows PowerShell setup

Run these commands from the project folder:

```powershell
cd C:\Users\saumy\OneDrive\Desktop\LearnflowAI
npm install

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
```

If PowerShell blocks activation, you can run the backend with the virtual environment's Python directly instead:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000
```

## Run the frontend, API, and local worker

Open two PowerShell windows. In the first window, run the frontend:

```powershell
cd C:\Users\saumy\OneDrive\Desktop\LearnflowAI
npm run dev
```

Open the frontend at [http://localhost:5173](http://localhost:5173).

In the second window, run the API:

```powershell
cd C:\Users\saumy\OneDrive\Desktop\LearnflowAI
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.main:app --reload --port 8000
```

The API is available at [http://localhost:8000](http://localhost:8000).

In a third PowerShell window, run the local extraction worker:

```powershell
cd C:\Users\saumy\OneDrive\Desktop\LearnflowAI
.\.venv\Scripts\python.exe -m backend.worker
```

Keep the worker running while uploading material. It polls the local SQLite queue and processes one PDF, presentation, or image at a time. It does not use AWS.

## Test the health endpoint

With the backend running, use this PowerShell command:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

You should receive:

```text
status
------
ok
```

You can also open [http://localhost:8000/health](http://localhost:8000/health) in a browser.

## Test a material upload

The easiest way to test the complete flow is to open [http://localhost:5173](http://localhost:5173), choose a supported file, and select **Upload material**. You can also test directly from PowerShell:

```powershell
curl.exe -X POST http://localhost:8000/materials/upload -F "file=@C:\path\to\your\sample.pdf"
```

The API returns the original filename, file type, byte size, and a generated stored filename. The generated file is saved under `backend\uploads\`; it is not publicly served by the API. Unsupported extensions return `415`, and files over the configured limit return `413`.

## Extract text and scan visual content

1. Upload a real `.pdf`, `.pptx`, `.png`, `.jpg`, or `.jpeg` file using the browser interface.
2. Uploading automatically queues mandatory text extraction and OCR.
3. The UI polls the durable job, shows progress, and displays the processed text grouped by page, slide, or image number.
4. If processing fails, use **Retry text + OCR** after addressing the reported issue.

The frontend uses:

```text
GET  http://localhost:8000/materials/{resource_id}/status
GET  http://localhost:8000/materials/{resource_id}/content
POST http://localhost:8000/materials/{resource_id}/process  # explicit retry
```

Resource metadata and processing status are also available from:

```text
GET http://localhost:8000/materials
GET http://localhost:8000/materials/{resource_id}/status
```

Use the opaque `resource_id` returned by the upload endpoint; do not send a local filesystem path. Completed content contains structured records with `reference_type`, `reference_number`, merged `text`, separate `native_text` and `ocr_text`, `ocr_applied`, `extraction_method`, and `has_text`. Invalid identifiers, missing files, unsupported formats, empty documents, and extraction failures are rejected or recorded safely.

The older stored-filename route remains as a compatibility endpoint. It now queues work and returns HTTP 202 instead of performing CPU-heavy OCR inside the web request:

```powershell
curl.exe -X POST http://localhost:8000/materials/REPLACE_WITH_STORED_FILENAME.pdf/extract
```

Each PDF page is rendered and scanned with local OCR even when selectable text exists, so screenshots and diagram labels are not silently skipped. Embedded raster images in PPTX files are also scanned. OCR recovers visible text, but it does not reliably understand arrows, spatial relationships, or the meaning of a workflow; that requires a later visual-understanding stage.

## Checks

```powershell
npm run build
npm run lint
python -m compileall backend
```
