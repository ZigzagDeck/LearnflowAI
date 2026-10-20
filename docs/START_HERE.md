# LearnFlowAI: setup, start, and test guide

Use this file as the permanent runbook for the `vm` branch. Commands below are
for Windows PowerShell and assume the repository is at `F:\LearnflowAI`.

## 1. One-time AWS Bedrock setup

1. Sign in to the [AWS Management Console](https://console.aws.amazon.com/).
   The public `aws.amazon.com/bedrock` page is only a product page.
2. Set the console Region in the top-right corner to **US East (N. Virginia) —
   `us-east-1`**.
3. Search for **Amazon Bedrock** and open the service console.
4. Open **Model catalog**, search for **Nova Lite**, and confirm that
   `Amazon Nova Lite` is available. Most models are enabled automatically. If
   the console shows an access action, complete it before continuing.
5. In Bedrock's left navigation, open **API keys**.
6. Open **Long-term API keys**, select **Generate long-term API key**, choose a
   short development expiry such as 30 days, and generate it. Keep the default
   `AmazonBedrockLimitedAccess` policy unless the account owner has supplied a
   narrower approved policy.
7. Copy the key immediately. AWS displays it only once. Do not paste it into
   chat, source files, `.env.example`, screenshots, or GitHub.
8. In AWS Billing and Cost Management, create a small email budget alert. The
   application's local limit is an extra safety guard, not an AWS spending cap.

Official references:

- [Generate a Bedrock API key](https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-generate.html)
- [Amazon Nova Lite model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-lite.html)
- [Create an AWS budget](https://docs.aws.amazon.com/cost-management/latest/userguide/budget-templates.html)

## 2. One-time local setup

Open PowerShell:

```powershell
Set-Location F:\LearnflowAI
git checkout vm
git pull origin vm
npm install
```

Create the Python environment only if `F:\LearnflowAI\.venv` does not already
exist:

```powershell
python -m venv .venv
```

Install or refresh the backend packages:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

The repository already has an untracked `.env`. Do not replace it or commit it.
Add these Bedrock values to that existing file:

```dotenv
LEARNFLOW_BEDROCK_CHAT_ENABLED=true
AWS_REGION=us-east-1
AWS_BEARER_TOKEN_BEDROCK=paste-the-new-key-here
LEARNFLOW_BEDROCK_MODEL_ID=amazon.nova-lite-v1:0
LEARNFLOW_BEDROCK_MAX_OUTPUT_TOKENS=600
LEARNFLOW_BEDROCK_MONTHLY_TOKEN_UNIT_LIMIT=2000000
```

Keep the existing Google Document AI and Voyage values in the same `.env`.

## 3. Start LearnFlowAI every time

Open three PowerShell windows. Keep all three running.

### Window 1 — API

```powershell
Set-Location F:\LearnflowAI
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000
```

Wait until the terminal says Uvicorn is running on `http://127.0.0.1:8000`.

### Window 2 — processing worker

```powershell
Set-Location F:\LearnflowAI
.\.venv\Scripts\python.exe -m backend.worker
```

The worker processes one material at a time to keep memory bounded.

### Window 3 — frontend

```powershell
Set-Location F:\LearnflowAI
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in the browser.

## 4. Quick health and configuration checks

In a fourth PowerShell window:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/usage/ocr
Invoke-RestMethod http://localhost:8000/usage/embeddings
Invoke-RestMethod http://localhost:8000/usage/bedrock
```

Expected basics:

- Health returns `status: ok`.
- OCR provider is `google_document_ai`.
- Embedding provider is `voyage`.
- Bedrock reports `enabled: true` and the configured Nova Lite model.

These checks do not call Google, Voyage, YouTube, or AWS.

## 5. See document and image processing work

1. Open the frontend.
2. Drag in a PDF, PPTX, PNG, JPG, or JPEG.
3. Select **Upload material**.
4. Watch the worker terminal and the UI processing status.
5. The workspace displays extracted/OCR text by page, slide, or image.

Google OCR and Voyage embedding requests occur during worker processing when
needed. Do not close the worker while a material is queued or processing.

## 6. See YouTube processing work

1. Use a public YouTube video with captions enabled.
2. Paste its direct URL into **or use a video link**.
3. Select **Add link**.
4. Keep the worker running.
5. The workspace displays caption text with real timestamp ranges.

The application does not download video or audio. Private, restricted,
captionless, or deployment-blocked videos return a readable error.

## 7. Verify Bedrock with one bounded request

The current frontend does not yet contain the chat panel. After at least one
material is ready, copy its `resource_id` from the upload response or
`http://localhost:8000/materials`, then run:

```powershell
$resourceId = "replace-with-ready-resource-id"
$body = @{
  session_id = "local-demo"
  question = "What is the main idea of this material?"
  allowed_source_ids = @($resourceId)
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/chat `
  -ContentType "application/json" `
  -Body $body
```

This performs Voyage query embedding and one bounded Bedrock request. The result
should contain `answer`, `grounded`, and server-validated `citations`.

For a YouTube resource, include the watched position so future captions are not
used:

```powershell
$body = @{
  session_id = "local-demo"
  question = "What has been explained so far?"
  allowed_source_ids = @($resourceId)
  video_source_id = $resourceId
  playback_seconds = 300
} | ConvertTo-Json
```

Then run the same `Invoke-RestMethod` command above.

## 8. Stop the project

Press `Ctrl+C` once in each of the three running PowerShell windows. This stops
the processes but preserves uploaded resources, cached extraction, embeddings,
and usage counters in local storage.

## 9. Common problems

- **Frontend says backend cannot be reached:** start Window 1 and confirm port
  8000 is not already occupied.
- **Material stays queued:** start Window 2. The API does not perform worker jobs.
- **Bedrock reports disabled:** add the Bedrock values to `.env`, save it, and
  restart the API.
- **Bedrock returns HTTP 503:** verify the API key has not expired, the Region is
  `us-east-1`, Nova Lite is available, and the local monthly limit is not reached.
- **YouTube captions fail:** first confirm the video is public and shows a
  transcript on YouTube. Some hosting providers' IP addresses may be blocked.
- **Voyage returns HTTP 429:** keep Voyage as the primary provider and set
  `LEARNFLOW_EMBEDDING_LOCAL_FALLBACK_ENABLED=true`. Restart the API and worker,
  then retry the material from History. The local fallback loads only after
  Voyage fails and remains protected by the configured free-memory gate.
- **Google or Voyage authentication fails:** verify the existing `.env` values,
  rotate any exposed key, then restart both API and worker.

Never commit `.env`, Google service-account JSON, Bedrock keys, or API keys.
