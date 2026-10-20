# LearnFlow AI integration contract (v0)

This contract defines the *shared schema*, not a promise that the endpoints are
already implemented. Provider and chat routes arrive in subsequent PRs.

## Existing API

- `GET /health` returns `{"status":"ok"}`.
- `POST /materials/upload` accepts multipart `file` and returns
  `stored_filename` (legacy upload ID), stable `resource_id`, processing
  `status`, and `deduplicated`. Exact duplicate content reuses the existing
  resource and stored file.
- `POST /materials/{document_id}/extract` returns content records:
  `reference_type`, `reference_number`, `text`, `has_text`, extraction
  provenance, and `cached` at the response level.
- `GET /materials` lists locally registered resources.
- `GET /materials/{resource_id}/status` returns persisted processing status.

These endpoints must remain backwards-compatible.

## Proposed chat API

`POST /chat`

```json
{
  "session_id": "session-demo",
  "question": "What is overfitting?",
  "allowed_source_ids": ["lesson-1", "slides-1"],
  "video_source_id": "lesson-1",
  "playback_seconds": 1122
}
```

A supported answer returns:

```json
{
  "session_id": "session-demo",
  "answer": "The lecture introduces overfitting as ...",
  "grounded": true,
  "citations": [
    {"source_id":"lesson-1","source_type":"video","chunk_id":"v12",
     "start_seconds":1080,"end_seconds":1094,"page":null,"slide":null}
  ]
}
```

A question with no supporting evidence returns `grounded:false`, an
explicit refusal and `citations:[]`. No made-up sources.

## Retriever handshake

Sneha's document adapter and Vansh's video adapter both return
`list[RetrievalHit]` from `backend/contracts.py`. Each hit includes text,
optional ranking score, and a citation with an exact source identifier and
PDF page / PPTX slide / video start/end position.

**Enforcement:** The server, never just the browser, must enforce
`allowed_source_ids` and `playback_seconds` *before* sending retrieved
context to the model. A transcript chunk overlapping the cutoff must be
trimmed or excluded, not fully returned.

## Proposed quiz API

`POST /quiz` uses `session_id`, `video_source_id`,
`playback_seconds`, `allowed_source_ids` and `count`. It returns
MCQ questions with `options`, `correct_option_index`, `explanation`
and evidence citations. The frontend should not expose `correct_option_index`
before submitting the attempt; scoring endpoint is a future integration detail.

## Security decisions remaining

Session IDs are not authentication. Production access requires a validated
identity/authorization layer and durable source/session ownership mapping.
Do not treat caller-supplied allowed-source IDs as proof of authorization.
