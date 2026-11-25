# Retail Support Studio

Local-only, synthetic React UI. No authentication or real financial actions.

```powershell
npm ci --registry=https://packagefeedproxy.microsoft.io/npm/
npm run dev
npm run lint
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Node 22.12+ is recommended. Vite proxies `/api` to `http://127.0.0.1:8000`.
Browser tests start their own Vite server and mock all backend endpoints; no backend is needed.
Tests in `..\tests\e2e` import the runner through `testing\browser.ts` so dependencies
are resolved from this frontend package.

An opt-in, unmocked production smoke creates exactly one queued run per desk and
reads history/reviewer state. Use only a dedicated seeded synthetic database with
no worker running; it never approves proposals or calls Azure:

```powershell
$env:RETAIL_LIVE_BASE_URL = "http://127.0.0.1:58080"
npm run test:e2e -- live.spec.ts
Remove-Item Env:RETAIL_LIVE_BASE_URL
```

The live test is skipped by default, records console/network failures, and closes
only its browser connections (not the production containers).

The Docker image serves the production build on port 80. Its nginx proxy forwards
`/api` unchanged to `api:8000`, disables event buffering, and allows one-hour idle
reads (backend heartbeats keep streams active).
Base images are pinned by immutable digest. The build argument `NPM_REGISTRY`
defaults to the configured Microsoft mirror and can be overridden when necessary.

## Event and selection behavior

- Each desk independently saves its customer/run selection in local storage.
- Saved activity is keyed by run ID, sorted/deduplicated by durable integer event ID.
  A new connection supplies `?after=`; native EventSource reconnects use Last-Event-ID.
- Closing or switching a stream never cancels backend work. Cancellation is explicit.
- Run details refresh after events and every five seconds, including after reviewer actions.
- Summaries and evidence are rendered as text, never raw HTML or hidden reasoning.
- Delivery collects `delivery_checks_confirmed` explicitly in intake and clarification,
  defaulting to false and preserving the API scenario/run value, never inferring it
  from messages. Returns reasons use `damaged: description` or `defective: description`.
- Returns displays all twelve contract nodes and the default branching topology.
  Edges are a presentation model: the contract exposes node events, not an edge endpoint.
- Reviewer mode intentionally shows all synthetic customers. Exact amounts are cents
  formatted as USD; replacements show both quantity and the backend-provided amount.
- Intake and clarification enforce the API's 4,000-character message, 1,000-character
  reason, and 1–20 quantity limits. FastAPI validation details are displayed by field.
- Information updates retain omitted/null context on the server; existing order/item/
  reason fields cannot be cleared. If an order changes, choose its matching item.
- History displays the backend's latest 100 runs; no pagination API is available.

Storage is browser-local and optional when unavailable; clear site data to reset saved
selections/activity. The API remains the source of truth for runs and review decisions.
