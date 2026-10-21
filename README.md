# LearnFlow AI

For a repeatable one-time setup, daily startup sequence, and end-to-end test,
follow [docs/START_HERE.md](docs/START_HERE.md).

For the complete project journey—including the starting point, failures,
fixes, architecture decisions, current limits, and remaining production work—
read [REPORT.md](REPORT.md).

LearnFlow AI is a learning workspace being built in small milestones. The current milestone contains:

- A React + TypeScript + Vite frontend
- A Python + FastAPI backend with health, local material-upload, and extraction endpoints
- Google Document AI OCR for scanned/visual PDF pages, PPTX images, and standalone images
- Bounded Gemma 4 visual interpretation for diagrams, workflows, charts, and relationships
- A local SQLite resource registry with content-hash deduplication and cached extraction results
- A restart-safe SQLite processing queue with one CPU-heavy extraction job at a time
- Automatic UI polling, per-page/slide progress, failure details, and explicit retry
- Deterministic semantic-boundary chunks that preserve exact page/slide/image citations
- Local SQLite FTS5/BM25 retrieval filtered by an explicit resource allow-list
- Guarded Jina AI embeddings with SQLite lexical/dense rank fusion
- Grounded Bedrock chat with Markdown, actionable citations, and multi-video playback scopes
- Grounded concise, detailed, and study-guide summaries across selected materials
- Server-scored single-answer, multiple-answer, short-answer, and mixed quizzes with citations
- Salted-password accounts, revocable sessions, per-user material access, and a privacy-safe admin usage view
- A responsive warm-olive workspace with drag-and-drop ingestion, saved transcript viewing, and YouTube thumbnails

YouTube caption ingestion, citation-safe local RAG, document OCR, bounded visual understanding, conversational Bedrock chat, grounded summaries and quizzes, and local password authentication are implemented. Captionless/uploaded-media transcription, password recovery/email verification, and hardened internet-scale deployment controls remain future production work.

## Folder guide

- `src/` - The frontend source code. `App.tsx` contains the page structure, while `App.css` and `index.css` contain its styles.
- `backend/` - The Python API. `main.py` defines the FastAPI application, CORS settings, validation, upload, and extraction endpoints.
- `backend/extraction.py` - PyMuPDF and python-pptx extraction with OCR enrichment and page/slide/image provenance.
- `backend/ocr.py` - Inline Google Document AI OCR, local usage cap, and opt-in RapidOCR fallback.
- `backend/resource_store.py` - SQLite metadata, cache, chunks, FTS, and compact dense vectors.
- `backend/processing.py` - One-job-at-a-time extraction coordinator with durable progress and safe failures.
- `backend/worker.py` - Local queue worker that renders bounded inputs and sends OCR requests to the configured provider.
- `backend/chunking.py` - Dependency-free text normalization and bounded, overlapping citation chunks.
- `backend/embeddings.py` - Guarded Jina REST adapter and opt-in local FastEmbed fallback.
- `backend/retrieval.py` - Citation-valid lexical and hybrid retrievers for grounded chat.
- `backend/quiz_service.py` - Grounded quiz generation, private answer-key storage, scoring, explanations, and citations.
- `backend/uploads/` - Created automatically when the first upload succeeds. Local uploaded files are kept here and are ignored by Git.
- `public/` - Static files that Vite serves directly.
- `package.json` - Frontend commands and JavaScript dependencies.
- `requirements.txt` - Python backend dependencies.
- `.env.example` - Safe placeholder names for future configuration. It contains no real secrets.

The upload endpoint currently accepts PDF, PPTX, PNG, JPG, and JPEG files up to 100 MB by default. The UI intentionally lists only formats that can be processed now. Set `LEARNFLOW_MAX_UPLOAD_SIZE_MB` before starting the backend to change that development limit.

Exact duplicate uploads reuse the existing resource and stored file. Extraction results are cached with a pipeline version, so unchanged resources do not repeat OCR while future extractor upgrades can invalidate stale results safely. Metadata is stored in `backend/data/learnflow.db` by default; override it with `LEARNFLOW_DATABASE_PATH`. Uploaded files default to `backend/uploads`; override that shared API/worker path with `LEARNFLOW_UPLOAD_DIR`.

The worker also converts each page, slide, or image record into normalized chunks of at most 1,200 characters with a small overlap. A chunk never crosses a citation boundary. Chunk IDs are deterministic, and the extraction plus its chunks are committed atomically to SQLite. Existing cached extraction can be backfilled into the current chunk format without loading OCR again.

SQLite FTS5 and normalized `float32` embeddings are written in the same transaction as each resource's chunks. Searches apply the resource allow-list inside both lexical and dense SQL queries. The hybrid adapter combines BM25 and semantic ranks with reciprocal-rank fusion and returns strict `RetrievalHit`/`Citation` contracts. Dense search is an exact, streaming SQLite scan, which avoids a vector service or a resident FAISS index for the current hackathon-scale corpus. Chat remains fail-closed until resource ownership is connected.

Jina AI is the default embedding provider, using `jina-embeddings-v3` with 256-dimensional retrieval vectors to keep stored vectors compact. Documents use `retrieval.passage` and questions use `retrieval.query`. Requests are split into batches of at most 16 texts, and HTTP 429 responses receive bounded exponential-backoff retries before processing fails. A conservative local counter reserves UTF-8 byte units before each request and defaults to 10 million units per calendar month. Inspect it at `GET /usage/embeddings`. Deleting the SQLite database resets this local guard, so monitor the API key balance in Jina's dashboard as a second control.

FastEmbed is the automatic last resort when Jina still cannot serve a request after retries. Set `LEARNFLOW_EMBEDDING_PROVIDER=fastembed` to use it directly, or keep `LEARNFLOW_EMBEDDING_LOCAL_FALLBACK_ENABLED=true` while Jina remains the primary provider. The local model is loaded lazily only after a Jina failure, stays CPU-only and one-threaded, uses batches of at most four texts, and is protected by the 768 MB free-memory gate.

PDF and PPTX extraction is limited to 500 pages/slides and 2 million extracted characters. Google OCR runs outside web requests in the dedicated worker and sends bounded page/image bytes directly; it does not use Google Cloud Storage. Clean, substantial native PDF text is kept locally without a paid OCR call unless the page contains raster or vector visuals. Scanned/short pages, PPTX images, and standalone images always pass through OCR. SQLite claiming guarantees that only one job runs at once. Jobs retain progress and failures across restarts; work with no update for 15 minutes is re-queued.

When visual understanding is enabled, the same worker selects only pages/slides with visual structure, samples at most the configured per-material limit, resizes each image to a bounded JPEG, and sends it inline to the configured Gemma 4 model through Bedrock Mantle. The model description is stored separately as `visual_description` and also indexed with the literal text so questions about arrows, flow, axes, and relationships are retrievable. No S3 bucket or other AWS service is used.

## Prerequisites

Install these separately if they are not already installed: Node.js 20+, Python 3.10+, and Git. This project does not install software or change Windows settings for you.

## Windows PowerShell setup

Run these commands from the project folder:

```powershell
cd F:\LearnflowAI
npm install

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
```

## Configure Google Document AI OCR

You need a Google Cloud project with billing enabled, the Document AI API enabled, and one **Enterprise Document OCR** processor. Create a service account with the least-privilege **Document AI API User** role (`roles/documentai.apiUser`) and download its JSON key outside this repository. Do not upload or commit that key.

Before starting the worker, set these values in the same PowerShell window:

```powershell
$env:LEARNFLOW_OCR_PROVIDER="google_document_ai"
$env:GOOGLE_CLOUD_PROJECT="your-project-id"
$env:GOOGLE_DOCUMENT_AI_LOCATION="us"
$env:GOOGLE_DOCUMENT_AI_PROCESSOR_ID="your-processor-id"
$env:GOOGLE_APPLICATION_CREDENTIALS="C:\secure\path\document-ai-key.json"
$env:LEARNFLOW_GOOGLE_OCR_MONTHLY_PAGE_LIMIT="1000"
$env:LEARNFLOW_OCR_LOCAL_ENGINE_ENABLED="false"
$env:LEARNFLOW_OCR_LOCAL_FALLBACK_ENABLED="false"
```

Use the exact location shown on the processor; the location is part of its identity and API endpoint. For hosted deployment, set the same non-secret values in the host settings and store the complete service-account JSON in the secret `LEARNFLOW_GOOGLE_SERVICE_ACCOUNT_JSON` instead of committing a file.

The local SQLite counter reserves one page before every request and blocks requests beyond 1,000 pages in a calendar month by default. Inspect it at `GET /usage/ocr`; the response also reports the execution location and whether the local engine or fallback is active. Keep a Google billing budget alert as a second guard because deleting the local database resets the local counter. RapidOCR cannot run unless `LEARNFLOW_OCR_LOCAL_ENGINE_ENABLED=true` is explicitly configured. The default is fail-closed Google-only OCR.

## Configure Jina embeddings

Create a Jina API key at the Jina AI API dashboard and store it only in an environment secret. Do not commit it or place it in `.env.example`.

For local development, copy `.env.example` to `.env` in the project root and fill in the values for both Google Document AI and Jina. The backend loads this file automatically. Existing process or hosting environment variables take priority over `.env`, and `.env` is ignored by Git.

```powershell
$env:LEARNFLOW_EMBEDDING_PROVIDER="jina"
$env:JINA_API_KEY="your-secret-key"
$env:LEARNFLOW_JINA_EMBEDDING_MODEL="jina-embeddings-v3"
$env:LEARNFLOW_JINA_EMBEDDING_DIMENSIONS="256"
$env:LEARNFLOW_JINA_MONTHLY_TOKEN_LIMIT="10000000"
$env:LEARNFLOW_EMBEDDING_LOCAL_FALLBACK_ENABLED="true"
```

For hosted deployment, configure the same values in the host's secret/environment settings. The API key must never be exposed through a `VITE_` variable because those values are compiled into browser code.

If PowerShell blocks activation, you can run the backend with the virtual environment's Python directly instead:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000
```

## Run the frontend, API, and local worker

Open two PowerShell windows. In the first window, run the frontend:

```powershell
cd F:\LearnflowAI
npm run dev
```

Open the frontend at [http://localhost:5173](http://localhost:5173).

In the second window, run the API:

```powershell
cd F:\LearnflowAI
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.main:app --reload --port 8000
```

The API is available at [http://localhost:8000](http://localhost:8000).

In a third PowerShell window, run the local extraction worker:

```powershell
cd F:\LearnflowAI
.\.venv\Scripts\python.exe -m backend.worker
```

Keep the worker running while uploading material. It polls the local SQLite queue and processes one PDF, presentation, or image at a time. OCR uses Google Document AI and embeddings use Jina AI; chunking, indexing, storage, and jobs remain local. The only AWS service planned is Bedrock.

## YouTube links

Paste a direct public YouTube video, Shorts, or `youtu.be` link in the upload card. The worker retrieves an existing manual or automatically generated caption track, preserves its real timestamps, embeds the transcript with the same guarded embedding provider, and stores everything in local SQLite. It does not download video or audio, so this path has negligible additional RAM use.

Set `LEARNFLOW_YOUTUBE_TRANSCRIPT_LANGUAGES` to a comma-separated priority list such as `en,en-US,en-GB,hi`. Videos that are private, restricted, blocked from the deployment host, or have no usable captions return a clear processing error. This lightweight caption library uses YouTube's internal web endpoints, so it may require maintenance when YouTube changes them.

## Amazon Bedrock grounded chat

Bedrock is the only AWS service used by LearnFlowAI. For the fastest development setup, create an Amazon Bedrock API key and save it as `AWS_BEARER_TOKEN_BEDROCK` in the untracked root `.env`. Standard temporary AWS credentials or an IAM role also work through Boto3's normal credential chain.

```dotenv
LEARNFLOW_BEDROCK_CHAT_ENABLED=true
AWS_REGION=us-east-1
AWS_BEARER_TOKEN_BEDROCK=replace-with-a-new-bedrock-api-key
LEARNFLOW_BEDROCK_API_MODE=mantle_chat_completions
LEARNFLOW_BEDROCK_MODEL_ID=google.gemma-4-31b
LEARNFLOW_BEDROCK_MAX_OUTPUT_TOKENS=5000
LEARNFLOW_BEDROCK_MONTHLY_TOKEN_UNIT_LIMIT=2000000
LEARNFLOW_VISUAL_UNDERSTANDING_ENABLED=true
LEARNFLOW_VISUAL_MAX_UNITS_PER_MATERIAL=6
```

The backend defaults to Bedrock Mantle's Chat Completions endpoint so project-scoped Bedrock API keys and catalog models work together. Gemma 4 visual understanding requires this Mantle mode. At most eight retrieved chat chunks or sixteen summary chunks are sent. Before every text or image request the app reserves a deliberately conservative unit count in local SQLite. Requests stop when the configured monthly ceiling would be exceeded. View the counter and visual configuration at `GET /usage/bedrock`. This is a local safety guard, not an AWS billing budget; set an AWS Budget alert as an independent account-level warning.

`LEARNFLOW_BEDROCK_CHAT_ENABLED` deliberately defaults to `false`. Enable it only after configuring the administrator credentials. Registration, salted password storage, revocable bearer sessions, per-user resource ownership, chat history, and quiz ownership are enforced by the API. Three configurable process-local rate limits protect authentication, AI generation, and general routes from accidental bursts on a single instance. An internet-facing production deployment should still add HTTPS, email verification/password recovery, distributed edge rate limiting, and managed secret rotation.

Signed-in users can select **Export data** to stream a portable JSON backup containing their material metadata and extracted content, conversations with citations, and quiz history. Passwords, session tokens, internal hashes, and server paths are excluded; original uploaded file bytes require a volume backup. See `docs/DEPLOYMENT.md` for the single-instance persistent-host requirements and recovery checklist.

## Grounded quizzes

The Quiz section uses the same ready materials and Bedrock configuration as chat. Select up to 12 sources, request any count from 1 to 20, and choose single-answer, multiple-answer, short-answer, or mixed questions. Generation samples evidence across the selected materials. The browser never receives answer keys before submission; those remain in local SQLite until the completed attempt is scored. After submission, the UI shows the score, correct choices or accepted short answer, explanation, and actionable source citations.

Quiz generation consumes one bounded Bedrock request. Scoring is local and does not call Bedrock, Jina, Google, or AWS.

## Grounded summaries and follow-up chat

The Summary section creates a concise overview, detailed summary, or study guide from up to 12 selected ready materials. It samples citation-preserving chunks across every selected source, renders the result as Markdown, and exposes the supporting page, slide, image, or YouTube timestamp chips.

Chat follow-up turns now receive up to eight recent server-owned messages from the same account, session, and exact source selection. The most recent context is also used to improve retrieval for questions such as “explain that second point.” Changing the selected sources automatically prevents earlier context from being reused until a new turn establishes that source set.

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
GET  http://localhost:8000/materials/{resource_id}/chunks
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

Scanned/short PDF pages and PDF pages containing raster or vector visuals are rendered and sent to Google OCR, so screenshot and diagram labels are not silently skipped. Text-heavy native PDF pages without visuals avoid a redundant paid call. Embedded raster images in PPTX files are scanned individually. OCR supplies literal text; the bounded Gemma 4 visual stage separately explains supported arrows, spatial relationships, workflows, and chart meaning.

## Checks

```powershell
npm run build
npm run lint
python -m compileall backend
```
