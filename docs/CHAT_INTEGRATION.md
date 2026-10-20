# Grounded chat orchestration (integration-gated)

This PR introduces a real `POST /chat` FastAPI route that **returns HTTP 503**
until trusted application integrations are installed. It intentionally does
not claim the end-to-end learner Q&A experience is ready.

## Current behavior

- Requests use the strict `ChatRequest` contract in `backend/contracts.py`.
- The service calls a trusted `SourceAuthorizer` before retrieving evidence.
- Two adapters supply document and video evidence using `RetrievalHit` objects.
- The server checks source IDs and evidence types. It excludes full transcript
  segments if their end time is after the current playback position, even if
  the video retriever supplies them accidentally.
- On no eligible evidence, the service abstains and does not call the model.
- Provider failures become HTTP 503, denied sources become HTTP 403.
- The response lists citation metadata from accepted evidence (not generated
  by the model). These are **candidate supporting citations**, not proven
  entailment of each sentence of the answer.

## Integration interface

Trusted application startup must install:

```python
app.state.chat_service = GroundedChatService(
    authorizer=trusted_authorizer,
    retriever=lesson_retriever,
    provider=OpenAICompatibleProvider(ProviderConfig.from_env()),
)
```

- **Shubhanshu** owns trusted source/session authorization, wiring, API and LLM.
- **Sneha** provides document RAG with source and PDF page / PPTX slide metadata.
- **Vansh** provides timestamp-aware video retrieval with source, start and end seconds.
- **Saumya** renders chat and evidence citations alongside current video position.

Do not substitute a permissive authorizer for testing on any publicly reachable
deployment. `session_id` and `allowed_source_ids` alone do not authenticate
the user. Integration must associate ownership with an authenticated identity.

## Accepted content policy

Documents are treated as separately permitted learning materials. If the
lesson's PDFs or PPTs contain future topics, an additional time/coverage filter
is needed before those materials can be considered safe at a prior playback
timestamp. Video evidence crossing the cutoff is **excluded**, not truncated.
The retrieval team may provide timestamp-split chunks for better coverage.

## Local application behavior

The local frontend now offers document, image, and timestamp-scoped YouTube Q&A, grounded candidate citations,
and a SQLite-backed history of completed chat turns. Chat history can be opened or
deleted in the History section. The same section lists uploaded materials, saved
processing errors, and per-material retry or delete controls. Deleting a material
also removes its extraction cache, normalized chunks, and embedding vectors.

This remains a single-user local integration: it has no account authentication,
and saved conversations are not sent as context to later model requests. Each
question is answered independently against the currently selected ready sources.
YouTube chat defaults its playback cutoff to the full processed transcript and
provides a timestamp slider so retrieval can be limited to material already watched.

## Still not completed

- Dense/video retrieval adapters or source authorization persistence. A filtered
  SQLite FTS5 document adapter now exists in `backend/retrieval.py`, but remains
  disconnected from `/chat` until authorization is real.
- Model-account connectivity/deployment smoke test
- Sentence-level citation entailment and hallucination evaluation
- Quiz API

These remain explicit dependencies. Keep the PR in draft and do not publicly
enable the route until source ownership and real retrieval are integrated.

## Tests

```bash
python -m pip install -r backend/requirements-dev.txt
python -m pytest backend/tests/test_chat_service.py -q
```
