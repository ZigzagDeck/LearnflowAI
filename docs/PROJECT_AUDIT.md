# LearnFlowAI repository audit

Audit date: 2026-10-20

Branch: `vm`

Cloud constraint: Amazon Bedrock is the only approved AWS service. Google Document AI is approved for bounded OCR requests; storage, transcription, retrieval, jobs, and metadata remain local.

## Actual implementation status

| Feature | Existing implementation | Relevant paths | Verified status | Missing work |
| --- | --- | --- | --- | --- |
| Frontend shell | React 19 + TypeScript + Vite single-page workspace | `src/App.tsx`, `src/App.css`, `src/index.css` | Lint and production build pass | Resource library, chat, citations, transcript, quiz, and persisted state |
| Upload UI | File picker, drag/drop, progress, local validation; advertises PDF, PPTX, PNG, JPEG only | `src/App.tsx` | Build verified; automatic job polling and retry are integrated | Multiple uploads, cancellation, accessibility/UI tests |
| Upload API | Streams bounded files to ignored local upload storage and verifies file contents | `backend/main.py`, `backend/file_validation.py` | API tests pass | Content hashes, deduplication, metadata registry, quotas, malware scanning |
| PDF ingestion | Page-level native extraction plus selective Google OCR for scanned, short, or visual pages | `backend/extraction.py`, `backend/ocr.py` | Durable background execution, progress, cache, routing, and OCR tests pass | Tables/layout and visual-semantic descriptions |
| PPTX ingestion | Editable shape text plus OCR of unique embedded PNG/JPEG images, with slide references | `backend/extraction.py` | Unit tests pass | Whole-slide rendering and visual-semantic descriptions; charts/grouped shapes need evaluation |
| Image ingestion | Safe PNG/JPEG validation and OCR with image reference | `backend/image_utils.py`, `backend/file_validation.py`, `backend/extraction.py` | Upload/extract API tests pass | Visual-semantic descriptions and broader image formats only if justified |
| OCR | Google Enterprise Document OCR with inline bytes, selective visual/scanned-page routing, a local 1,000-page monthly cap, and opt-in RapidOCR fallback | `backend/ocr.py`, `backend/extraction.py`, `backend/worker.py` | Mock transport, cap, fallback, provenance, and routing tests pass without cloud calls | Live credential smoke test and OCR quality evaluation set |
| Video | Contracts contain timestamp citation fields | `backend/contracts.py`, `backend/chat_service.py` | Contract tests pass | Upload, FFmpeg audio extraction, transcription, segment persistence, UI |
| RAG | Strict retrieval-hit/citation contracts, deterministic citation chunks, allow-list-filtered SQLite FTS5/BM25, compact local embeddings, and reciprocal-rank fusion | `backend/contracts.py`, `backend/chunking.py`, `backend/embeddings.py`, `backend/retrieval.py`, `backend/chat_service.py` | Chunk, provenance, lexical/dense filtering, hybrid citation-adapter, persistence, and service tests pass | Ownership/authorization adapter and evaluation set |
| Chat API | `/chat` router is now registered and fails closed when integrations are absent | `backend/chat_api.py`, `backend/main.py` | API tests pass | Real authorizer, retriever, Bedrock provider, frontend |
| Model provider | Generic OpenAI-compatible adapter exists | `backend/llm_provider.py` | Mock tests pass | Replace/wrap with a Bedrock Runtime Converse provider; no live AWS test yet |
| Quiz | Strict request/question/response models | `backend/contracts.py` | Validation tests pass | Retrieval-backed service, API, scoring boundary, frontend |
| Persistence | Local files plus SQLite resource metadata, status, hashes, versioned extraction cache, durable jobs, and normalized chunks | `backend/uploads/`, `backend/resource_store.py` | Persistence, deduplication, cache, chunks, jobs, progress, retry, and recovery tests pass | Ownership and cleanup policy |
| Tests/CI | Backend pytest, frontend lint/build, Docker smoke workflow | `backend/tests/`, `.github/workflows/ci.yml` | 86 backend tests pass locally; frontend lint/build pass | OCR fixtures with real-world samples, retrieval evaluation, Docker build rerun |

## Current data flow and diagnosis

The working flow is browser selection/drop → multipart upload and streaming SHA-256 → local file validation → SQLite resource registration/deduplication → durable job enqueue → one local worker claims the job → mandatory extraction/OCR with page/slide progress → versioned cached records → status polling and rendering in React.

The strongest existing design work is in the strict citation contracts, fail-closed chat coordinator, and durable resource/cache/job boundary. The main architectural gaps are that resource ownership is not authenticated and chat abstractions are not connected to real ingestion or retrieval. The generic model adapter is not a Bedrock adapter. There is no implemented video flow, resource library UI, or quiz service.

OCR now prevents image text from being silently skipped, but OCR alone cannot infer arrows, layout relationships, chart meaning, or algorithm flow. A Bedrock multimodal enrichment record must remain distinct from literal native/OCR text and retain the same page, slide, or image reference.

## Recommended minimal stack

| Concern | Choice | Requirement level | Reason |
| --- | --- | --- | --- |
| PDF/PPTX extraction | PyMuPDF + python-pptx | Mandatory/current | Already integrated and suitable for native text and source references |
| OCR | Google Enterprise Document OCR + optional RapidOCR fallback | Mandatory/current | Moves OCR inference off the laptop; inline requests avoid Cloud Storage, and a local monthly page cap limits usage |
| Visual understanding | Bedrock Converse with an approved multimodal model | Mandatory for diagrams | The only cloud service; pass bounded page/image bytes directly, not through S3 |
| Video transcription | FFmpeg + faster-whisper | Mandatory later | Local timestamped transcription; avoids Amazon Transcribe charges |
| Metadata/cache | SQLite + content-addressed local files | Mandatory next | Durable, cheap, simple, supports hashes/status/jobs without a managed database |
| Background processing | Dedicated local Python worker over a SQLite job table | Mandatory before large resources | Restart-safe processing without Redis or a cloud queue; keep web requests short |
| Chunking | Small in-repository semantic-boundary chunker | Mandatory | Paragraph/heading/slide/transcript-aware behavior without a framework dependency |
| Embeddings | FastEmbed/ONNX with `BAAI/bge-small-en-v1.5` | Mandatory/current | Local asymmetric embeddings without loading PyTorch; lazy, CPU-only, one-thread execution with a memory guard |
| Dense retrieval | Normalized float32 vectors in SQLite with bounded exact cosine scan | Mandatory/current | Avoids another compiled index and resident copy while the hackathon corpus is small |
| Lexical retrieval | SQLite FTS5/BM25 | Mandatory for hybrid RAG | No extra service; strong exact-term search beside semantic retrieval |
| Reranking | None initially | Optional | Add a local cross-encoder only if the evaluation set shows a useful gain |
| LLM/quiz generation | Bedrock Runtime Converse via `boto3`, validated with Pydantic | Mandatory later | One AWS integration, one request interface, structured grounded outputs |
| Storage/cloud services | Local disk + SQLite; Bedrock and bounded Google Document AI calls only | Mandatory constraint | Do not add S3, Transcribe, Textract, DynamoDB, Lambda, OpenSearch, CloudWatch, or Google Cloud Storage |

For small corpora, Sentence Transformers documents direct semantic search as practical, so the current SQLite scan avoids a second index dependency. Bedrock Converse accepts raw image bytes for supported multimodal models, so S3 is not required for diagram analysis.

## Prioritized roadmap

1. **Reliable multimodal document ingestion (first slice complete).** PDF native+OCR, PPTX image OCR, standalone images, provenance, aligned UI formats, and passing tests.
2. **Durable resource registry and cache (complete).** SHA-256 deduplication, SQLite resource/status records, versioned extraction JSON, listing/status APIs, and restart-safe tests are implemented.
3. **Local background worker (complete).** Upload returns after durable enqueue, the UI polls unit progress, a SQLite claim permits one heavy job, failures are explicitly retryable, and stale interrupted work resumes.
4. **Normalized chunks and hybrid index (core complete).** Citation-preserving chunks, atomic lexical/vector persistence, filtered BM25 and exact cosine retrieval, and reciprocal-rank fusion are complete. Remaining: a representative retrieval evaluation set and tuning from its results.
5. **Bedrock text and vision integration.** Complete when one configured model answers only from retrieved evidence, selected visual pages get clearly marked model-derived descriptions, usage is logged without content/secrets, and spend limits are documented.
6. **Grounded chat UI.** Complete when users select resources, receive insufficient-evidence responses, and open exact citations.
7. **Local video and authorized YouTube ingestion.** Complete when supported uploads produce real timestamped faster-whisper segments, YouTube links support embedded playback plus authorized captions/transcripts, and citations seek to exact timestamps. Arbitrary YouTube audiovisual downloading is not a dependable core path.
8. **Grounded quizzes.** Complete when validated MCQs cite retrievable evidence and scoring does not expose answers prematurely.
9. **Evaluation and demo hardening.** Complete when real PDF/PPTX/image/video fixtures measure extraction, retrieval, citation accuracy, latency, failures, and Bedrock cost for the final demo volume.

## First implementation impact

The first slice adds two runtime dependencies (`rapidocr`, `onnxruntime`), keeps all OCR local, expands the extraction response with backward-compatible provenance fields, adds image citation support, registers the existing fail-closed chat route, and changes the upload allow-list. Video and legacy PPT uploads were intentionally removed until they have a working processor; `.pptx` remains supported.

## Technical references

- [RapidOCR installation and packaged-model guidance](https://rapidai.github.io/RapidOCRDocs/main/install_usage/rapidocr/install/)
- [Google Document AI setup](https://docs.cloud.google.com/document-ai/docs/setup)
- [Google Document AI pricing](https://cloud.google.com/products/document-ai/pricing)
- [Document AI IAM roles](https://docs.cloud.google.com/document-ai/docs/access-control/iam-roles)
- [PyMuPDF OCR guidance](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html)
- [faster-whisper repository](https://github.com/SYSTRAN/faster-whisper)
- [Sentence Transformers semantic-search documentation](https://www.sbert.net/examples/sentence_transformer/applications/semantic-search/README.html)
- [FastEmbed documentation](https://qdrant.github.io/fastembed/Getting%20Started/)
- [Amazon Bedrock Runtime Converse API](https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-runtime/client/converse.html)
