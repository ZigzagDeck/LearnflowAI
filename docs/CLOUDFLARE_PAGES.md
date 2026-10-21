# Cloudflare Pages frontend setup

This guide deploys only the React/Vite frontend to Cloudflare Pages. The API,
worker, SQLite database, and uploaded files remain on your laptop. The laptop
must stay awake and online, with the API, worker, and Cloudflare Tunnel running
whenever someone uses the deployed site.

## 1. Deploy the frontend from GitHub

1. Push the intended frontend changes to the GitHub `vm` branch.
2. In Cloudflare, open **Workers & Pages** and choose **Create application** >
   **Pages** > **Connect to Git**.
3. Connect GitHub and select `saumyayadav2603-dot/LearnflowAI`.
4. Set the production branch to `vm`.
5. Use these build settings:

   | Setting | Value |
   | --- | --- |
   | Root directory | `/` (repository root; leave blank if the dashboard uses blank for root) |
   | Framework preset | `React (Vite)` or `Vite` |
   | Build command | `npm run build` |
   | Build output directory | `dist` |

6. Start the deployment. Cloudflare Pages serves the Vite static build and
   automatically provides the single-page-app fallback used by this React app.
7. Copy the resulting production URL, normally
   `https://<project-name>.pages.dev`.

Cloudflare's React/Vite build settings are `npm run build` and `dist`.
Static assets are served from its CDN; no Pages Function or Cloudflare Worker
is needed for the current frontend.

## 2. Connect the frontend to the laptop API

The frontend reads `VITE_API_BASE_URL` at build time. Once the API has a stable
HTTPS hostname through Cloudflare Tunnel, open the Pages project's **Settings**
> **Environment variables** and add this variable for **Production**:

```text
VITE_API_BASE_URL=https://api.your-domain.example
```

Use the API origin only: do not add a path such as `/api`, and do not add a
trailing slash. Then trigger a new Pages deployment so Vite bakes the URL into
the frontend bundle. This value is public by design; **never put Jina, Google,
Bedrock, admin, or other secrets in any `VITE_` variable**.

The API hostname must route through a Cloudflare Tunnel on your laptop to
`http://localhost:8000`. A named tunnel with a hostname you control is stable;
a temporary Quick Tunnel URL changes and requires rebuilding/redeploying the
frontend whenever it changes.

## 3. Allow the Pages origin in FastAPI

After the first Pages deployment, add the exact production site origin to your
existing root `.env` (keep all existing credentials and settings):

```dotenv
LEARNFLOW_CORS_ORIGINS=https://<project-name>.pages.dev
```

If you add a custom frontend domain, list both origins separated by a comma,
with no trailing slashes:

```dotenv
LEARNFLOW_CORS_ORIGINS=https://<project-name>.pages.dev,https://learnflow.example
```

Restart the API after changing this setting. For a Pages preview deployment,
add its exact preview origin only if you intend to test that preview against
your laptop API. Do not use `*` for a public app.

## 4. Start the local services for a demo

Keep the existing API and worker startup steps in
[`START_HERE.md`](START_HERE.md), and also run your named Cloudflare Tunnel
that routes the API hostname to `http://localhost:8000`. Check the public API
URL first:

```text
https://api.your-domain.example/health
```

It should return `{"status":"ok"}`. Then open the Pages URL, sign in, and
test one small material. The API, worker, SQLite data, and original files are
still local; Cloudflare Pages hosts only the browser assets.

## Important limits and safety

- Cloudflare's Free plan has a 100 MB maximum request body. The app's current
  upload limit is also 100 MB, so files near the app limit can exceed the edge
  limit once multipart overhead is included. Start with smaller test files.
- The laptop's RAM, CPU, storage, and internet upload speed remain the backend
  limits. The worker still processes one material at a time.
- The database is not moved to Cloudflare. Keep a backup of the local
  `backend/data/learnflow.db` and `backend/uploads` directory.
- Keep provider keys and service-account credentials on the laptop in `.env`;
  Pages only needs the non-secret API base URL.
- Cloudflare Tunnel makes the API reachable over the internet. Keep app
  authentication enabled, use strong admin credentials, and only publish the
  API hostname—not a hostname pointing at the whole laptop or database.

References: [Cloudflare Pages build configuration](https://developers.cloudflare.com/pages/configuration/build-configuration/),
[Pages single-page app behavior](https://developers.cloudflare.com/pages/configuration/serving-pages/),
[Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectivity-options/),
and [Cloudflare upload limits](https://developers.cloudflare.com/cache/concepts/default-cache-behavior/).
