# LearnFlowAI deployment guide

## What the repository supports

LearnFlowAI can run on one small, long-lived host with:

- the FastAPI web process;
- one background worker process;
- the built frontend;
- one persistent volume for SQLite and uploaded files.

It does not require any AWS service except Amazon Bedrock. Google Document AI,
Jina AI, and Bedrock are called directly over HTTPS. A live host is not created
by this repository because the provider, region, free-tier limits, and payment
method are decisions only the account owner can make.

## Hosting requirements

Choose a service that supports all of the following:

1. Two continuously running commands (API and worker), or one container in
   which a process supervisor keeps both alive.
2. A persistent disk mounted at stable paths for the database and uploads.
3. At least 1.4 GB RAM. The application processes one material at a time and
   uses remote OCR, embeddings, and inference by default, but PDF rendering
   still needs temporary memory.
4. Outbound HTTPS access to Google, Jina, Bedrock, and YouTube.
5. HTTPS and environment-secret support.

Avoid ephemeral-only serverless hosts: their files disappear across restarts,
and their request lifecycle is not suitable for this worker. Use one API replica
and one worker with SQLite. Multiple API replicas require moving to a shared
database and a distributed rate limiter first.

## Production environment

Copy the variable names from `.env.example` into the host's secret manager.
Never upload `.env` or a service-account file to Git. Important deployment
values include:

```dotenv
LEARNFLOW_DATABASE_PATH=/data/learnflow.db
LEARNFLOW_UPLOAD_DIR=/data/uploads
LEARNFLOW_CORS_ORIGINS=https://your-frontend.example
LEARNFLOW_ADMIN_EMAIL=you@example.com
LEARNFLOW_ADMIN_PASSWORD=replace-with-a-long-unique-secret
LEARNFLOW_AUTH_SESSION_DAYS=30
LEARNFLOW_GENERAL_REQUESTS_PER_MINUTE=180
LEARNFLOW_AUTH_REQUESTS_PER_MINUTE=10
LEARNFLOW_AI_REQUESTS_PER_MINUTE=20
```

Also configure the existing Google Document AI, Jina, and Bedrock secrets. For
Google credentials on a host, prefer `LEARNFLOW_GOOGLE_SERVICE_ACCOUNT_JSON`
from the host's encrypted secret store instead of a checked-in JSON file.

Set the frontend build variable to the public HTTPS API URL:

```dotenv
VITE_API_BASE_URL=https://api.example.com
```

## Build and start

Build the frontend once:

```bash
npm ci
npm run build
```

Start the API and worker as independent long-lived processes from the same
checkout and with the same environment and persistent volume:

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
python -m backend.worker
```

Serve `dist/` with the host's static-site or reverse-proxy feature. Route API
traffic to port 8000. Only `/health` is intentionally public; application data
endpoints require a bearer session.

## Data safety and recovery

- Use **Export data** in the signed-in profile bar for a portable JSON backup
  of that account's materials, extracted content, chats, citations, and quizzes.
- Back up `/data/learnflow.db` together with `/data/uploads` for a complete
  operational restore. The JSON export does not contain original uploaded file
  bytes.
- Configure host snapshots before accepting irreplaceable data.
- Use the History UI to delete failed or unwanted materials and chat sessions.
- Do not automatically delete user content without an explicit retention policy.

The built-in limiter is intentionally small and process-local. It protects one
low-cost instance from accidental bursts but is not a distributed denial-of-
service control. A larger public deployment needs a reverse-proxy or managed
rate limiter, email verification/password recovery, managed secret rotation,
central logs without content, and a shared production database.

## Verification after deployment

1. Confirm `GET /health` returns `{ "status": "ok" }`.
2. Register a non-admin account and verify it cannot see another account's
   materials, chats, quizzes, or admin metrics.
3. Upload one small image, keep the worker running, and confirm OCR, visual
   interpretation, embedding, and retrieval complete.
4. Generate one summary and a one-question quiz, then test citation navigation.
5. Restart the service and confirm the material and chat still exist.
6. Download an account export and confirm it contains no password hash, API key,
   bearer token, content hash, or server file path.

Deployment should remain single-instance until SQLite and the process-local
limiter are intentionally replaced.
