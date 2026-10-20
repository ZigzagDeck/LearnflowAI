# Local OCR ingestion

LearnFlow currently processes PDF, PPTX, PNG, JPG, and JPEG resources without a cloud OCR service.

## Processing stages

- **PDF:** extract selectable text, render every page at a bounded resolution, run RapidOCR, de-duplicate OCR lines already present in native text, and retain the page number.
- **PPTX:** extract editable shape text, OCR each unique embedded raster image, merge the results, and retain the slide number.
- **Image:** validate dimensions and actual file format, run OCR, and retain image reference `1`.

Every record reports `native_text`, `ocr_text`, `text`, `ocr_applied`, and `extraction_method`. This provenance is intended to flow into later chunk and citation metadata.

## Deliberate limits

OCR reads visible characters. It does not reliably infer diagram arrows, graph relationships, or algorithm flow from layout. A future Bedrock multimodal enrichment step should describe visually meaningful pages and slides while retaining their source reference. That description must be treated as model-derived metadata, not as literal extracted text.

OCR currently runs inside the extraction request with a configurable timeout. Moving processing to a local background job is required before supporting large uploads reliably.

No AWS OCR, storage, transcription, database, queue, or monitoring service is used.
