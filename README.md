# LearnFlow AI

LearnFlow AI is a learning workspace being built in small milestones. The current milestone contains:

- A React + TypeScript + Vite frontend
- A Python + FastAPI backend with health, local material-upload, and extraction endpoints
- Local OCR enrichment for PDF pages, PPTX embedded images, and standalone PNG/JPEG images
- A homepage with drag-and-drop upload, extraction controls, and a readable learning workspace

End-to-end RAG, transcription, summaries, quizzes, and Bedrock integration are **not implemented yet**. Grounded-chat contracts and orchestration boundaries exist, but no production retriever, source authorizer, or model provider is wired into the application.

## Folder guide

- `src/` - The frontend source code. `App.tsx` contains the page structure, while `App.css` and `index.css` contain its styles.
- `backend/` - The Python API. `main.py` defines the FastAPI application, CORS settings, validation, upload, and extraction endpoints.
- `backend/extraction.py` - PyMuPDF and python-pptx extraction with OCR enrichment and page/slide/image provenance.
- `backend/ocr.py` - Lazy local RapidOCR adapter backed by ONNX Runtime.
- `backend/uploads/` - Created automatically when the first upload succeeds. Local uploaded files are kept here and are ignored by Git.
- `public/` - Static files that Vite serves directly.
- `package.json` - Frontend commands and JavaScript dependencies.
- `requirements.txt` - Python backend dependencies.
- `.env.example` - Safe placeholder names for future configuration. It contains no real secrets.

The upload endpoint currently accepts PDF, PPTX, PNG, JPG, and JPEG files up to 100 MB by default. The UI intentionally lists only formats that can be processed now. Set `LEARNFLOW_MAX_UPLOAD_SIZE_MB` before starting the backend to change that development limit.

PDF and PPTX extraction is limited to 500 pages/slides and 2 million extracted characters. The default processing timeout is 180 seconds and can be changed with `LEARNFLOW_EXTRACTION_TIMEOUT_SECONDS`. OCR is CPU-intensive; background processing is still required before large documents should be treated as production-ready.

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

## Run both services

Open two PowerShell windows. In the first window, run the frontend:

```powershell
cd C:\Users\saumy\OneDrive\Desktop\LearnflowAI
npm run dev
```

Open the frontend at [http://localhost:5173](http://localhost:5173).

In the second window, run the backend:

```powershell
cd C:\Users\saumy\OneDrive\Desktop\LearnflowAI
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.main:app --reload --port 8000
```

The API is available at [http://localhost:8000](http://localhost:8000).

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
2. After the upload succeeds, select **Extract text + OCR**.
3. The workspace displays the processed text grouped by page, slide, or image number.

The frontend calls:

```text
POST http://localhost:8000/materials/{stored_filename}/extract
```

Use the safe `stored_filename` returned by the upload endpoint; do not send a local filesystem path. The extraction endpoint returns structured records with `reference_type`, `reference_number`, merged `text`, separate `native_text` and `ocr_text`, `ocr_applied`, `extraction_method`, and `has_text`. It rejects invalid identifiers, missing files, unsupported formats, empty documents, and extraction failures.

To test extraction directly from PowerShell after uploading:

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
