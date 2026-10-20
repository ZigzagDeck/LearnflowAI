# Google Document AI OCR ingestion

LearnFlow processes PDF, PPTX, PNG, JPG, and JPEG resources through a local
worker, but OCR is performed by Google Document AI by default. The worker
renders or decodes bounded images locally and sends those bytes directly to the
configured Enterprise Document OCR processor. Google Cloud Storage is not used.

## Processing stages

- **PDF:** extract selectable text locally, identify scanned/short/visual pages,
  render only those pages, and send them to Google Document AI.
- **PPTX:** extract editable shape text locally and send each unique embedded
  raster image to Google Document AI.
- **Image:** validate dimensions and the real file format, then send the image to
  Google Document AI.

Every record reports `native_text`, `ocr_text`, `text`, `ocr_applied`, and
`extraction_method`. This provenance flows into chunk and citation metadata.

## Cloud-only verification

The default configuration is fail-closed:

```dotenv
LEARNFLOW_OCR_PROVIDER=google_document_ai
LEARNFLOW_OCR_LOCAL_ENGINE_ENABLED=false
LEARNFLOW_OCR_LOCAL_FALLBACK_ENABLED=false
```

`GET /usage/ocr` reports `execution: google_cloud`,
`local_engine_enabled: false`, and `local_fallback_enabled: false`. With those
values, RapidOCR cannot be constructed. A Google authentication, IAM, quota, or
processor error fails the material instead of silently running OCR locally.

The extraction pipeline version includes the cloud-only/local-engine mode, so
cached output created under a different OCR mode is not reused after the mode
changes.

## Deliberate limits

OCR reads visible characters. It does not reliably infer diagram arrows, graph
relationships, or algorithm flow from layout. A later Bedrock multimodal step
can describe visually meaningful pages while retaining source references; that
description must remain model-derived metadata rather than literal OCR text.

No AWS OCR, storage, transcription, database, queue, or monitoring service is
used.
