# Upload content validation

## Existing flow

The server currently supports PDF, PPTX, PNG, JPG, and JPEG. Formats without a
working processor are intentionally rejected rather than being stored in an
unusable state.
Upload still returns the same `stored_filename` shape as before.
Size limits and temporary cleanup behavior remain intact.

## New checks

- Reject empty files (HTTP 422).
- Reject obviously mismatched formats by file signature (HTTP 415).
- Open PDFs with PyMuPDF and reject corrupt/password-protected PDFs.
- Validate required PPTX ZIP parts and bound individual uncompressed members.
- Decode images with Pillow, enforce a 40-megapixel limit, and require their
  contents to match the PNG or JPEG extension.

No scanning for viruses is performed.
Production deployments must add sandboxing, malware scanning, storage
quotas and authenticated file ownership.

## Test

```bash
python -m pip install -r backend/requirements-dev.txt
python -m pytest backend/tests/test_upload_validation.py -q
```

Tests validate valid and forged PDF/PPTX/image inputs and cleanup paths.
