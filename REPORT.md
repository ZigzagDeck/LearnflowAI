# LearnFlowAI — Full Engineering Journey and Architecture Report

**Report date:** 21 October 2026  
**Repository:** `ZigzagDeck/LearnflowAI`
**Implementation branch:** `vm`  
**Code snapshot reviewed:** `24e97c7` (`feat: add grounded server-scored quizzes`)

> This is a historical engineering snapshot. The root `README.md` is the current source of truth for features, setup, deployment, and remaining scope.

## 1. Purpose and evidence basis

This is a fresh reconstruction of the project journey. It does not reuse the conclusions of earlier audit documents. It is based on:

- the original master project brief;
- the initial repository at commit `9201028`;
- the complete Git history through `24e97c7`;
- the current backend, frontend, configuration, database, CI, and deployment code;
- the actual integration failures reported while the system was being built; and
- the compile and production-build checks completed after the quiz implementation.

The report deliberately distinguishes three levels of confidence:

- **Implemented:** the feature exists in the codebase.
- **Locally validated:** its code path compiled, built, or was covered by local automated checks.
- **Provider-dependent:** final behavior still depends on an external account, quota, credential, model, or deployment environment.

## 2. Executive summary

LearnFlowAI began as a small React and FastAPI application with a polished upload interface and basic native text extraction for PDFs and PPTX files. It did not have OCR, persistence, background processing, embeddings, retrieval, video-link ingestion, grounded question answering, quizzes, history, cost controls, or a working AWS integration.

The project was progressively converted into a cost-conscious, citation-aware learning system. The current application can:

- securely accept PDF, PPTX, PNG, JPG, and JPEG files;
- accept direct public YouTube links and ingest existing captions without downloading video or audio;
- extract native PDF/PPTX text while using Google Document AI for visual or scanned content;
- process materials in a durable, one-job-at-a-time worker rather than inside long HTTP requests;
- cache resources and extraction output by content hash and pipeline version;
- create deterministic page-, slide-, image-, or timestamp-bound chunks;
- create Jina embeddings and store compact vectors in SQLite;
- combine SQLite FTS5/BM25 and dense retrieval using reciprocal-rank fusion;
- answer questions through Amazon Bedrock using only retrieved evidence;
- enforce selected-resource scope and video playback cutoffs on the server;
- display citations, processed-material history, chat history, retry, and deletion controls; and
- generate grounded multiple-choice quizzes whose answer keys remain server-side until submission.

The most important architectural achievement is not simply that cloud APIs were connected. It is that external services were placed behind bounded, fail-closed interfaces while resource identity, provenance, caching, retrieval, history, usage counters, and processing state remained under application control.

The implementation grew by approximately **8,370 inserted lines across 59 changed files** from the original baseline. The repository currently contains 65 commits, 46 code files, and 17 backend test/support files. This reflects a staged build rather than a single risky rewrite.

## 3. Where the project started

At the initial commit, the repository contained only 15 tracked files. Its effective architecture was:

```text
React upload UI
    -> FastAPI upload endpoint
        -> local uploads folder
            -> synchronous PyMuPDF/python-pptx extraction
                -> page/slide text returned to the browser
```

The initial README explicitly stated that AI processing, transcription, summaries, OCR, and RAG were not implemented. The original application had several useful foundations:

- React, TypeScript, and Vite were already appropriate for the frontend.
- FastAPI was a good fit for the backend.
- PyMuPDF and `python-pptx` already provided native document extraction.
- Page and slide output was already visible in the UI.
- Uploads had a nominal 100 MB limit.

However, the initial system also had important gaps:

| Area | Starting condition | Consequence |
|---|---|---|
| OCR | No OCR | Scans, screenshots, diagrams, and image-only pages produced little or no usable text. |
| Persistence | No resource registry or durable processing state | Refreshes and restarts lost application-level state. |
| Processing | Extraction occurred through request-driven behavior | Long or expensive work could block the API and was hard to retry safely. |
| File support | The UI/documentation mentioned types the pipeline could not truly process | The product could imply support it did not actually have. |
| RAG | No chunks, embeddings, index, or retrieval | The model could not answer from selected resources. |
| Video | No transcript pipeline | Uploaded/video-link learning material was unusable for retrieval. |
| AI generation | No connected model | Chat and quizzes were absent. |
| Citations | Page/slide extraction existed, but no end-to-end citation contract | Later AI responses could not be safely tied to source locations. |
| Cost control | No service-level usage accounting | Cloud integration could create uncontrolled usage. |
| Security | Basic extension checks were insufficient | Malformed or mislabeled uploads could reach parsers. |

## 4. Constraints that shaped the implementation

Several requirements evolved while the project was being built. They materially changed the final architecture:

1. **Only Amazon Bedrock should be used from AWS.** S3, DynamoDB, Lambda, Textract, Transcribe, OpenSearch, and other AWS services were rejected for this version because of uncertainty about pricing and the limited $100 account budget.
2. **OCR was mandatory, not optional.** Native extraction alone could not understand text embedded in screenshots, diagrams, or scanned pages.
3. **Cloud processing should be the default.** Google Document AI was selected for OCR and Jina AI for embeddings. Local models were retained only as explicit code paths, then disabled by default so they could not silently hide cloud failures.
4. **Laptop memory had to stay below roughly 1.4 GB during testing.** This ruled out a large always-resident local model stack and influenced the single-worker design, bounded batches, streaming vector search, lazy local model loading, and free-memory gate.
5. **YouTube links were required.** The application needed to process a URL rather than requiring users to upload a video.
6. **The UI needed honest file support and functional drag-and-drop.** Unsupported extensions were removed from the user-facing input path, while PNG/JPEG support was added.
7. **Answers needed situation-dependent length.** A fixed short output cap was not acceptable, but every response also should not consume the full 5,000-token ceiling.
8. **Users needed manual cleanup.** Processed-material and chat histories had to be visible and deletable from the UI.
9. **All work had to remain isolated on `vm`.** Changes were committed and pushed as small, named milestones.

These constraints produced a hybrid local/cloud system rather than a fully local system or an all-AWS system.

## 5. Current architecture

### 5.1 System view

```text
React/Vite frontend
  |-- file drag-and-drop / YouTube URL
  |-- processing status and extracted content
  |-- grounded study chat
  |-- grounded quiz interaction
  `-- processed-data and chat cleanup

FastAPI API
  |-- upload and content validation
  |-- resource/status/history APIs
  |-- chat and quiz orchestration
  |-- usage/configuration visibility
  `-- safe provider error boundaries

Local worker (one job at a time)
  |-- native PDF/PPTX extraction
  |-- Google Document AI OCR
  |-- YouTube caption retrieval
  |-- deterministic chunking
  `-- Jina embedding generation

SQLite
  |-- resources and extraction cache
  |-- durable processing queue
  |-- FTS5 chunk index
  |-- compact normalized vectors
  |-- chat sessions/messages
  |-- quiz attempts/private answer keys
  `-- per-provider monthly usage counters

External services
  |-- Google Document AI: OCR only
  |-- Jina AI: embeddings only
  |-- YouTube: existing captions only
  `-- Amazon Bedrock: grounded answers and quiz generation only
```

### 5.2 Resource-processing flow

```text
Upload or YouTube link
  -> validate and register resource
  -> deduplicate by content/source identity
  -> enqueue durable processing job
  -> worker claims one job
  -> extract native text / retrieve captions / perform required OCR
  -> normalize page, slide, image, or timestamp records
  -> create deterministic bounded chunks
  -> request passage embeddings
  -> atomically save content, chunks, FTS rows, and vectors
  -> mark resource ready
```

The API and worker share SQLite and the configured upload directory. The worker processes one material at a time, limiting CPU and memory contention. Jobs inactive for 15 minutes can be reclaimed after an interrupted run.

### 5.3 Question-answering flow

```text
Question + explicit source IDs + optional video cutoff
  -> server validates selected ready resources
  -> Jina query embedding
  -> filtered FTS5 lexical search + filtered dense search
  -> reciprocal-rank fusion
  -> server rejects wrong-source/wrong-type/future-video evidence
  -> at most eight evidence chunks sent to Bedrock
  -> response returned with server-constructed citations
```

If no eligible evidence exists, the service refuses to answer and does not call Bedrock. Source content is treated as untrusted data rather than as model instructions.

### 5.4 Quiz flow

```text
Selected ready resources + question count
  -> server validates resource scope
  -> representative evidence sampled across sources
  -> one bounded Bedrock JSON-generation request
  -> strict Pydantic validation
  -> private answer key and citations stored in SQLite
  -> browser receives questions/options only
  -> learner submits every answer once
  -> local server scoring
  -> score, explanations, correct answers, and citations returned
```

Quiz scoring does not call Bedrock, Jina, Google, or AWS. Answer keys are not exposed in the initial generation response.

## 6. Implementation journey

### Stage 1 — Establishing engineering safeguards

The early repository work added CI, shared API contracts, stronger file validation, model-provider boundaries, grounded-chat orchestration, request observability, Docker packaging, and deployment documentation.

This stage mattered because it created contracts before the full AI pipeline existed. It also made the chat route fail closed instead of pretending that retrieval or model integration was ready.

Secure upload validation moved beyond filename extensions. PDFs are parsed, PPTX archives are inspected with safety limits, and images are decoded and checked. Invalid temporary files are removed instead of being retained as successful uploads.

### Stage 2 — OCR and image-aware ingestion

The first OCR implementation used RapidOCR locally. PDF pages could be rendered, PPTX images scanned, and standalone images processed. Native and OCR text were merged while preserving fields such as `native_text`, `ocr_text`, `ocr_applied`, and `extraction_method`.

This was a useful prototype but conflicted with the laptop-memory and cloud-first requirements. The design therefore evolved rather than being discarded: OCR stayed behind a provider interface, allowing Google Document AI to replace the default engine without rewriting extraction.

The final extraction policy is selective:

- PDF native text is extracted first.
- Empty, suspiciously short, raster-bearing, or vector-visual pages are rendered for OCR.
- PPTX editable text is extracted locally; embedded raster images are OCR-scanned.
- Standalone PNG/JPEG images always use OCR.
- Citation provenance remains the original page, slide, or image.

This avoids paying to OCR clean text-only pages while still treating OCR as a required stage for visual content.

### Stage 3 — Durable persistence and processing

A SQLite resource registry introduced stable resource IDs, content hashes, extraction cache fields, timestamps, statuses, and source URLs. Exact duplicate uploads reuse the existing resource rather than storing and processing the same content again.

Expensive extraction was then removed from the request lifecycle and placed in a durable local queue. The API registers and queues work; `backend.worker` claims one job at a time, reports progress, completes it atomically, or stores a safe error. The UI polls status and supports explicit retry.

This was one of the strongest engineering decisions in the project because it solved several problems together:

- lower peak memory and CPU contention;
- restart-safe jobs;
- visible progress;
- safe retries;
- a responsive API; and
- a clean place to execute OCR and embedding calls.

### Stage 4 — Citation-preserving content normalization

The application added a common normalized chunk representation for PDFs, PPTX files, images, and video captions. Text is normalized, divided on paragraph and sentence boundaries, and hard-split only when required.

Current text chunks are bounded to 1,200 characters with 160 characters of overlap. A chunk never crosses a page, slide, image, or timestamp boundary. Chunk IDs are deterministic hashes of the resource, pipeline version, source position, chunk index, and content.

Pipeline versions are stored with extraction, chunking, and embedding data. A meaningful implementation change can invalidate stale cached output without deleting unrelated data or repeatedly processing unchanged resources.

### Stage 5 — Local lexical and hybrid retrieval

SQLite FTS5 supplied BM25-style lexical retrieval for exact terminology, identifiers, and technical phrases. Dense vectors were stored in SQLite as compact normalized `float32` blobs, and dense similarity was computed with a bounded streaming scan.

This deliberately avoided FAISS or a hosted vector database for the current hackathon-scale corpus. It eliminated a permanently resident index and another service bill while retaining semantic retrieval.

Lexical and dense candidate ranks are fused using reciprocal-rank fusion with a constant of 60. Importantly, resource allow-lists are applied inside both database search paths, not merely filtered after retrieval.

### Stage 6 — Embedding-provider evolution

The first semantic implementation used local FastEmbed with `BAAI/bge-small-en-v1.5`. To protect the laptop, it used CPU-only execution, one thread by default, batches of four or fewer, lazy model loading, disabled CPU memory arena, and a 768 MB free-memory gate.

The product decision then changed to cloud-first embeddings. Voyage AI became the initial default, using compact 256-dimensional vectors and local usage accounting. During real use, Voyage returned HTTP 429 before the rest of the YouTube pipeline could proceed. A bounded local fallback was temporarily enabled, but that did not address the user's preference to understand and replace the failing provider.

The project then switched to Jina AI:

- `jina-embeddings-v3`;
- 256-dimensional normalized vectors;
- `retrieval.passage` for indexed chunks;
- `retrieval.query` for questions;
- batches of at most 16 by default;
- bounded 429 retries honoring `Retry-After`; and
- safe provider/request detail propagation without exposing secrets.

The exact account-side cause of the Voyage 429 could not be proven from the status code alone; it normally represents a quota or rate-limit rejection. The engineering response was to expose a bounded failure path, retain provider abstraction, and then switch providers cleanly when the product owner selected Jina.

Local embedding fallback was later disabled by default. The code remains available for an explicit offline configuration, but it cannot silently consume laptop memory during normal cloud-first operation.

### Stage 7 — Google Document AI integration

Google Document AI was selected instead of an AWS OCR service because the AWS scope had been intentionally restricted to Bedrock. Images are encoded as bounded inline PNG/JPEG documents and sent directly to the configured regional processor; Google Cloud Storage is not required.

The implementation supports either application-default/service-account credentials or a complete service-account JSON secret supplied by the deployment environment. It reserves one locally counted page before each provider call and stops at the configured monthly limit, currently 1,000 pages by default.

When Google OCR initially appeared not to work, a key observability problem was discovered: local OCR behavior and cached results could make it unclear which engine had actually executed. The fix was not another retry loop. The configuration was made explicit and fail closed:

```text
LEARNFLOW_OCR_PROVIDER=google_document_ai
LEARNFLOW_OCR_LOCAL_ENGINE_ENABLED=false
LEARNFLOW_OCR_LOCAL_FALLBACK_ENABLED=false
```

The `/usage/ocr` endpoint and frontend now report the provider, execution location, local-engine state, and fallback state. RapidOCR cannot even be constructed unless the local engine is explicitly enabled. The OCR execution mode is included in the extraction pipeline version, preventing output cached under a previous mode from being mistaken for a new Google OCR run.

### Stage 8 — YouTube link ingestion

YouTube support was implemented through existing captions rather than video download, audio extraction, or paid transcription. The URL parser accepts only HTTPS links from known YouTube hosts and normalizes direct watch, short, embed, live, and Shorts formats to a canonical video ID.

The caption reader preserves real start and end timestamps. It rejects malformed ordering, videos longer than the configured 12-hour safety limit, more than 20,000 caption segments, and more than 2 million caption characters.

This choice made YouTube processing inexpensive and memory-light. Its trade-off is explicit: private, restricted, captionless, or provider-blocked videos cannot be processed, and uploaded video files still require a future transcription pipeline.

After initial ingestion, YouTube materials appeared in processed data but were not fully usable in chat. The integration was repaired so video sources were included in the chat selection flow and routed through timestamp-aware retrieval. The UI gained a playback cutoff slider, and the server excludes any transcript chunk whose end time lies beyond that cutoff.

### Stage 9 — Amazon Bedrock model integration

Bedrock was retained as the only AWS service, satisfying the hackathon requirement without adding storage, databases, queues, transcription, or OCR bills inside AWS.

The first proposed Nova model was not available in the account. A later attempt to use `openai.gpt-5.6-luna` returned HTTP 401 stating that the model was unavailable for the account. This exposed an important distinction: seeing a model in the catalog or trying it in a workbench does not guarantee that a particular account/API key can invoke it programmatically.

The selected working direction became Google Gemma 4 31B through Bedrock Mantle using model ID `google.gemma-4-31b`. The provider supports both:

- Bedrock Mantle Chat Completions with a Bedrock API key; and
- native Bedrock Runtime Converse when standard AWS credentials/roles are available.

Gemma 4 required the Mantle `/openai/v1/chat/completions` route, while other Mantle models use `/v1/chat/completions`. This model-specific route handling was encoded in the provider instead of being left as a manual setup trick.

Every request reserves a conservative local usage estimate before the network call. The estimate includes UTF-8 prompt bytes plus the complete output allowance. This intentionally overestimates normal token use. The default local ceiling is 2,000,000 units per calendar month. It is a safety guard, not an AWS billing cap.

### Stage 10 — Grounded chat, history, and answer quality

The chat service enforces resource scope on the server, retrieves no more than eight evidence chunks, and constructs citations from stored metadata rather than trusting the model to invent them. If retrieval returns nothing eligible, it refuses without spending a Bedrock request.

The UI now supports selecting ready documents, images, and YouTube resources; asking questions; viewing citations; opening previous chat sessions; and deleting chat history. A processed-data history lists current state, failures, retry actions, and deletion controls.

Initial answers were too short because output was explicitly capped near 1,200 tokens. Raising every response to 5,000 would have increased cost and latency even for simple questions. The fix was an adaptive budget:

- brief requests: up to 500 tokens;
- ordinary factual requests: around 900;
- explanatory requests: around 1,800;
- complex/multipart requests: around 2,800;
- large multi-source analytical requests: additional room; and
- explicit detailed requests: up to the configured 5,000 ceiling.

This is a better policy than either a permanently low cap or an unconditional maximum.

### Stage 11 — Grounded quiz implementation

The final implemented milestone added a complete multiple-choice quiz flow. Users can select up to 12 ready materials and request 3, 5, 8, or 10 questions from the UI. The backend can support one to ten questions.

The Bedrock model must return a strict JSON object containing exactly four distinct options, a correct index, an explanation, and evidence indices. Pydantic validation rejects malformed structure, wrong question counts, duplicate questions, invalid option sets, or evidence references outside the supplied context.

The browser never receives the answer key during generation. The private questions, correct indices, explanations, and validated citations are stored in SQLite under a random quiz ID. Submission requires exactly one answer for every question and is accepted only once. The server scores locally and then reveals the correct answers and explanations.

This prevents the common implementation mistake of shipping correct answers to browser state before the learner submits.

## 7. What broke and how it was fixed

| Problem observed | Why it mattered | Engineering response | Result |
|---|---|---|---|
| Initial uploads claimed formats not actually processable | Misleading UI and parser failures | Restricted the input surface to PDF, PPTX, PNG, JPG, and JPEG; added content-signature/container validation | UI and API now advertise the same supported formats. |
| OCR absent for scans and screenshots | Native extractors missed visible text | Added visual detection, rendering, image OCR, merge rules, and provenance | Scanned/visual content now enters the same citation pipeline. |
| OCR/embedding work risked blocking API requests | Slow responses and poor retry behavior | Added durable SQLite jobs and a one-job worker | Processing is restart-safe, observable, and bounded. |
| Laptop RAM concern under 1.4 GB | Local AI models could exhaust memory | Cloud-first providers, lazy local loading, one/two thread caps, batches of four, 768 MB free-memory gate, single worker | Normal configuration avoids local model loading. |
| Voyage embedding requests returned 429 | Materials could not finish indexing; YouTube stopped before RAG | Added bounded fallback guidance, then replaced Voyage with Jina through the provider interface | Current default uses Jina with bounded 429 backoff and better error detail. |
| Local embedding fallback contradicted cloud-first testing | Cloud failures could be hidden and RAM used unexpectedly | Disabled local fallback by default | Provider failures are visible unless fallback is explicitly enabled. |
| Google Document AI seemed inactive despite credentials | It was unclear whether cloud OCR or local/cached output had run | Added explicit local-engine gate, provider/execution status API and UI, fail-closed cloud mode, and pipeline-version invalidation | Google-only behavior is observable and local OCR cannot silently run. |
| Nova models were unavailable | Planned model could not be invoked | Inspected account-visible alternatives rather than hard-coding the original recommendation | Avoided building against inaccessible model IDs. |
| GPT-5.6 Luna returned 401 unavailable for the account | Catalog/workbench visibility did not translate into API authorization | Moved to an account-usable Bedrock catalog model and proper Mantle path | Current configuration targets Gemma 4 31B. |
| Gemma 4 used a different Mantle route | Correct credentials/model still fail against the wrong endpoint | Added `/openai/v1` routing for Gemma 4 and retained `/v1` for other models | Provider selects the correct endpoint automatically. |
| YouTube links processed but did not appear/usefully work in chat | Ingestion and chat were not fully connected | Included video resources in UI selection, added video retrieval and playback scope | Ready YouTube transcripts can ground chat with timestamps. |
| Chat answers were consistently small | Fixed 1,200-token output cap ignored user intent | Added request-sensitive budgets with a 5,000 maximum | Short questions stay efficient; detailed requests can receive detailed answers. |
| User could not recover from bad processing/chat outcomes | SQLite data existed but had no user control | Added processed-data and chat history, retry, open, and delete actions | The user can inspect and clean local state without database tools. |
| Quiz answer keys could have been exposed to the browser | Learners could inspect network/state and cheat | Split generation and submission, persisted private keys server-side, one-time scoring | Quiz interaction is materially safer and more realistic. |

## 8. Strong engineering decisions

### 8.1 Preserving the existing stack

React/Vite, FastAPI, PyMuPDF, and `python-pptx` were retained. There was no framework rewrite merely to make the project appear more sophisticated. New behavior was added around existing working extraction and UI flows.

### 8.2 Using AWS only where it had clear value

Bedrock is the only AWS dependency. This satisfies the hackathon integration requirement while avoiding uncertain costs for S3, Transcribe, Textract, DynamoDB, Lambda, and OpenSearch. The architecture still leaves room to add durable cloud storage or transcription later.

### 8.3 Choosing SQLite over premature infrastructure

One SQLite database currently handles metadata, processing state, extraction cache, FTS, compact vectors, histories, quiz attempts, and usage counters. At the current single-user/hackathon scale, this is simpler, cheaper, and easier to debug than operating multiple hosted services.

### 8.4 Keeping provenance structural

Citations are carried from extraction through chunks and retrieval. The LLM does not create source IDs, page numbers, slide numbers, or timestamps. Chat citations come from accepted retrieval hits; quiz citations come from validated evidence indices mapped back to stored chunks.

### 8.5 Failing closed

The system avoids pretending to work when a critical dependency fails:

- no evidence means no model call;
- invalid source scope is rejected;
- future video content is excluded;
- usage tracking failure blocks provider calls;
- cloud-only OCR failure does not silently run locally;
- malformed quiz JSON is rejected;
- incomplete embeddings fail material processing; and
- provider errors are converted into safe, non-secret messages.

### 8.6 Separating request handling from expensive work

OCR and document embedding happen in the worker, not in normal web requests. This produces a more reliable interface and protects the API from CPU/memory spikes.

### 8.7 Bounded operations everywhere

Important limits are explicit:

- uploads: 100 MB by default;
- documents: 500 pages/slides and 2 million extracted characters;
- rendered PDF pages: 20 million pixels;
- Google inline document: 35 MB;
- chunks: 1,200 characters with 160 overlap;
- YouTube: 20,000 segments, 2 million characters, 12 hours;
- Jina default batch: 16 texts and 256 dimensions;
- local embeddings: one thread by default, batch four, 768 MB free-memory gate;
- chat: no more than eight evidence chunks;
- quizzes: no more than 12 sources, 12 evidence chunks, and 10 questions;
- Bedrock: adaptive output with a hard 5,000-token ceiling.

### 8.8 Treating provider content as untrusted

Retrieved learning material is placed in prompts as evidence, not instructions. This reduces the risk that text embedded in an uploaded document can override system behavior.

### 8.9 Making configuration observable

`/usage/ocr`, `/usage/embeddings`, and `/usage/bedrock` expose configured provider names, modes, limits, and locally counted usage. The frontend also displays the OCR execution mode. This directly addressed the confusion caused by silent fallback and cached results.

### 8.10 Versioning processed artifacts

Extraction, chunking, and embedding versions form a processing pipeline version. Changing OCR mode or embedding model does not accidentally reuse semantically incompatible artifacts.

### 8.11 Keeping secrets outside Git

Real API keys and service-account credentials are expected in an ignored `.env`, an external credentials file, or deployment secrets. `.env.example` contains placeholders only. Provider error handling avoids returning raw credential-bearing responses.

## 9. Current feature status

| Capability | Current status | Notes |
|---|---|---|
| Drag-and-drop uploads | Implemented | PDF, PPTX, PNG, JPG, JPEG; default 100 MB maximum. |
| Upload validation | Implemented | Signature/container/decoder checks; not a full antivirus system. |
| Native PDF extraction | Implemented | Page-level provenance and bounded rendering. |
| PPTX extraction | Implemented | Slide text plus OCR of unique embedded images. |
| Standalone image OCR | Implemented | PNG/JPEG decoded and sent to configured OCR provider. |
| Google Document AI | Implemented, provider-dependent | Cloud-only by default; requires valid project, processor, IAM, billing, and credentials. |
| Local RapidOCR | Implemented but disabled | Requires explicit engine and fallback flags. |
| Resource persistence | Implemented | SQLite metadata, cache, statuses, source URLs, hashes. |
| Background processing | Implemented | Dedicated local worker, one job at a time, retry/stale recovery. |
| YouTube links | Implemented, provider-dependent | Uses existing captions; does not download video/audio. |
| Uploaded video transcription | Not implemented | A future transcription/storage pipeline is still required. |
| Chunking/citations | Implemented | Deterministic page/slide/image/timestamp-bound chunks. |
| Jina embeddings | Implemented, provider-dependent | Default provider; local usage guard and 429 backoff. |
| Local embeddings | Implemented but disabled | Explicit last-resort mode only. |
| Lexical retrieval | Implemented | SQLite FTS5/BM25 with source filters. |
| Dense retrieval | Implemented | Streaming exact search over SQLite vectors. |
| Hybrid ranking | Implemented | Reciprocal-rank fusion. |
| Bedrock grounded chat | Implemented, provider-dependent | Gemma 4 31B/Mantle configuration; selected sources only. |
| YouTube playback cutoff | Implemented | Future transcript chunks are excluded server-side. |
| Adaptive response length | Implemented | 500–5,000 depending on intent and configured ceiling. |
| Chat history | Implemented | Local sessions/messages can be reopened or deleted. |
| Processed-data history | Implemented | Retry and delete controls included. |
| Grounded MCQ quizzes | Implemented, provider-dependent | Server-side keys, local scoring, explanations, citations. |
| Summaries | Not implemented as a separate product feature | Users can ask for grounded summaries in chat, but no dedicated summary workflow exists. |
| Production authentication | Not implemented | Current source authorizer is suitable only for private/single-user use. |
| Free public deployment | Not completed | Container exists, but persistent storage, worker lifecycle, secrets, and identity remain deployment concerns. |

## 10. Data and API surface

### 10.1 SQLite responsibilities

The database contains:

- `resources` — stable identity, source type, filenames, hashes, status, cached extraction, and source URL;
- `processing_jobs` — queue state, attempts, progress, errors, and timestamps;
- `monthly_service_usage` — conservative local counters for Google, Jina, and Bedrock;
- `chunks` — normalized text and exact provenance;
- `chunks_fts` — SQLite full-text index;
- `chunk_embeddings` — model-tagged compact vectors;
- `chat_sessions` and `chat_messages` — local chat history;
- `quiz_attempts` — selected sources, private questions/keys, answers, score, and state.

### 10.2 Main APIs

- `GET /health`
- `GET /usage/ocr`
- `GET /usage/embeddings`
- `GET /usage/bedrock`
- `POST /materials/upload`
- `POST /materials/youtube`
- `GET /materials`
- `DELETE /materials/{resource_id}`
- `GET /materials/{resource_id}/status`
- `POST /materials/{resource_id}/process`
- `GET /materials/{resource_id}/content`
- `GET /materials/{resource_id}/chunks`
- `POST /chat`
- `GET /chat/history`
- `GET /chat/history/{session_id}`
- `DELETE /chat/history/{session_id}`
- `POST /quiz`
- `POST /quiz/{quiz_id}/submit`

## 11. Cost and resource strategy

### Local laptop

The normal cloud-first configuration does not load RapidOCR or FastEmbed. Local work consists mainly of the Vite frontend, FastAPI, one worker, file parsing/rendering, SQLite, and bounded image conversion. The single-worker policy prevents multiple heavy documents from being processed simultaneously.

The 1.4 GB target is an operational goal rather than a formally measured guarantee for every possible 100 MB document. PDF rendering, decompression, or unusually large presentation images can still create spikes, which is why pixel, page, character, and job-concurrency limits exist.

### External providers

- **Google Document AI:** used only for OCR-required pages/images; local default guard is 1,000 pages/month.
- **Jina AI:** used for document and query embeddings; conservative local default guard is 10,000,000 UTF-8-byte units/month.
- **Amazon Bedrock:** used for chat and quiz generation; conservative local default guard is 2,000,000 prompt/output units/month.
- **YouTube:** existing captions are retrieved; there is no video/audio download or transcription bill.

Local counters are not provider billing caps. Deleting the SQLite database resets them, and providers may count usage differently. Provider-side budget alerts and dashboards remain necessary.

## 12. Security and reliability posture

Current strengths include:

- safe generated filenames and opaque resource IDs;
- content validation before accepting an upload;
- source allow-listing inside retrieval queries;
- no default web research path;
- no LLM-generated citation metadata;
- bounded redirects/timeouts and safe provider errors;
- secret placeholders rather than committed credentials;
- CORS configuration;
- request tracing/timing middleware;
- unprivileged Docker user;
- durable status/error records; and
- one-time server-side quiz scoring.

Important limitations remain:

- a caller-supplied session ID is not authentication;
- the local authorizer checks that resources exist and are ready, not that a signed-in user owns them;
- local SQLite/upload storage is not tenant-isolated;
- upload validation is not malware scanning;
- the Docker image starts only the API, not the worker;
- container-local uploads and SQLite data are ephemeral without a mounted persistent volume;
- no retention policy or automatic cleanup exists;
- citations identify candidate evidence but do not mathematically prove sentence-level entailment;
- OCR extracts visible text but does not fully understand arrows, diagrams, charts, or spatial workflow semantics.

Any API key previously pasted into chat or another non-secret channel should be rotated, even if that provider is no longer used. Secrets should remain only in the ignored `.env`, an external Google credentials file, or a hosting secret manager.

## 13. Verification and quality controls

The repository has GitHub Actions jobs for:

- frontend lint;
- TypeScript checking and production build;
- Python compilation;
- backend pytest execution;
- backend Docker build; and
- container health smoke testing.

Backend tests cover API behavior, contracts, upload validation, resource storage, extraction/OCR, OCR providers, chunking, embeddings, Jina behavior, retrieval, YouTube ingestion, chat service, Bedrock provider, generic model provider, and observability.

For the latest quiz implementation, the following were completed locally:

- Python backend compilation: passed;
- frontend TypeScript and Vite production build: passed;
- FastAPI OpenAPI registration of `/quiz` and `/quiz/{quiz_id}/submit`: confirmed;
- Git diff whitespace validation: passed.

No live Bedrock request was made during that final validation, so current provider credentials, account access, output quality, and cost behavior were not re-proven by the build check. The newest quiz path also does not yet have a dedicated automated test module; this is an explicit follow-up rather than a hidden claim of completeness.

## 14. What remains to make it production-ready

Priority order:

1. **Add real authentication and ownership.** Associate users with resources, chats, and quizzes. Never expose the current private local authorizer on a public multi-user service.
2. **Add dedicated quiz tests.** Cover malformed model JSON, evidence-index rejection, hidden answers, duplicate/missing answers, resubmission, scoring, and citations.
3. **Choose a persistent deployment design.** The API, worker, SQLite database, and uploads need durable storage and a reliable worker process. A free host may sleep, have ephemeral disks, or disallow long-running workers.
4. **Run provider smoke tests using controlled sample data.** Verify one Google OCR page, one Jina passage/query pair, one Bedrock chat, and one Bedrock quiz while recording actual provider usage.
5. **Create a small evaluation set.** Measure extraction correctness, retrieval relevance, citation accuracy, groundedness, and quiz-answer validity with known pages/slides/timestamps.
6. **Add uploaded video transcription only if required.** This needs file/audio validation, a transcription provider, asynchronous job polling, real timestamps, storage, and cost controls. It should not be improvised inside an HTTP request.
7. **Improve visual understanding separately from OCR.** Diagrams and algorithm flows may require a multimodal description stage. Model-derived descriptions must be labeled as such and retain their page/slide reference.
8. **Add quiz-history management if needed.** Quiz attempts are persisted but do not yet have a history/cleanup UI equivalent to chat and processed data.
9. **Add retention and backup policies.** Define when uploads, transcripts, chats, quizzes, and provider usage records are deleted or backed up.
10. **Keep operational documentation current.** The consolidated `README.md` is the primary setup and deployment guide; this report remains a milestone record.

## 15. Recommended demonstration sequence

For a reliable hackathon demonstration:

1. Start the API, worker, and frontend using the root `README.md`.
2. Show `/usage/ocr`, `/usage/embeddings`, and `/usage/bedrock` to prove the selected providers and limits.
3. Upload one digital PDF containing text and one page with an image or scan.
4. Show processing progress and page-level extracted/OCR provenance.
5. Add a public captioned YouTube link and show timestamped transcript records.
6. Ask a question restricted to one source and show its page/slide/timestamp citations.
7. Move the YouTube playback cutoff earlier and demonstrate that future evidence is excluded.
8. Ask a deliberately unsupported question and show the refusal behavior.
9. Ask a detailed question and demonstrate adaptive response depth.
10. Generate a five-question quiz, show that answers are absent before submission, submit it, and review explanations/citations.
11. Open chat history and processed-data history, then demonstrate retry or deletion.

Use small, pre-verified inputs for the demo. Do not depend on a private/captionless YouTube link or an untested provider key during the presentation.

## 16. Commit-based milestone record

The principal implementation milestones on `vm` were:

| Commit | Milestone |
|---|---|
| `9201028` | Initial React/FastAPI upload and native extraction application |
| `123b89d` | Local OCR ingestion for documents and images |
| `840fcd5` | Persistent resource registry and extraction cache |
| `c7cce05` | Durable one-job extraction worker |
| `9880f6f` | Citation-aware deterministic chunks |
| `4a8c642` | Filtered SQLite lexical retrieval |
| `badaece` | Memory-safe local hybrid retrieval |
| `dbd4281` | Guarded Google Document AI OCR |
| `e8bfd15` | Guarded Voyage embeddings as the first cloud default |
| `1dca1da` | Safe local `.env` loading |
| `480401c` | Timestamped YouTube caption ingestion |
| `efcaa43` | Guarded Amazon Bedrock chat |
| `febc9b2` | Permanent setup/startup runbook |
| `6b53ab0` | Local chat and processed-data history/cleanup |
| `143fd17` | Bounded fallback response to Voyage failures |
| `87be5c1` | Cloud embedding migration from Voyage to Jina |
| `1523601` | YouTube materials connected to grounded chat |
| `d905c4c` | Gemma 4 Bedrock configuration and endpoint handling |
| `1ac557a` | Adaptive 500–5,000 answer budget |
| `bf2db49` | Local embedding fallback disabled by default |
| `4c62820` | Enforced and observable cloud-only Google OCR |
| `24e97c7` | Grounded server-scored quiz workflow |

## 17. Final assessment

LearnFlowAI is no longer a static upload demonstration. It is now a coherent single-user learning pipeline with real ingestion, cloud OCR, timestamped caption support, cached processing, hybrid retrieval, evidence-bounded Bedrock generation, citations, histories, and quizzes.

The project’s strongest quality is its restraint. It did not add AWS services merely for architecture-diagram complexity; it did not keep an inaccessible model because it looked attractive in a catalog; it did not hide provider failures behind local execution once cloud-only verification became important; it did not send entire documents to the LLM; and it did not expose quiz answer keys to the browser.

The project is credible as a hackathon implementation and a strong engineering prototype. It is not yet a public multi-user production service. Authentication, durable hosted storage/worker operation, systematic evaluation, quiz-specific automated tests, and uploaded-video transcription are the clearest remaining boundaries.

That distinction is a strength: the system now has a solid enough core that the remaining work can be added deliberately instead of being hidden behind an overclaimed demo.
