# Hosting the web app on Cloudflare (free tier)

**This is the deployment we use for the moment.** `apps/web` runs on Cloudflare
Workers at no cost; the API runs somewhere else. This document says how, why the
line falls where it does, and what would make us move it.

See [D25](decisions-log.md) for the short version.

---

## 1 · What is hosted here, and what is not

Only the Next.js app. That is not a preference — the API cannot run on
Cloudflare at all, let alone for free:

| `apps/api` needs                                            | Why Cloudflare cannot host it                                                                        |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `opencv-python-headless`, `pymupdf`, `pillow-heif`, `numpy` | Workers' Python is Pyodide. No native wheels — and `alppy/scan/` _is_ native code.                   |
| Playwright / headless Chromium (`sheets/render.py`)         | Browser Rendering is a paid binding, and Chromium does not fit in a Worker regardless.               |
| Postgres + **pgvector**                                     | Cloudflare has no Postgres. Hyperdrive is a connection pooler, and it is paid.                       |
| Redis + the long-running **arq worker**                     | Nothing on the free plan runs a persistent process. Containers start at the $5/mo Workers Paid plan. |

So the deployment is split:

```
                    ┌──────────────────────────────────────┐
  teacher's         │  Cloudflare Workers (free)           │
  browser  ────────▶│  apps/web — Next.js via OpenNext     │
                    │                                      │
                    │  /_next/static/*  ──▶ Workers Assets │  served before the
                    │  /fr, /de, /en    ──▶ Worker (SSR)   │  Worker even runs
                    │  /api/v1/*        ──┐                │
                    └─────────────────────┼────────────────┘
                                          │  rewrite, same origin
                                          ▼
                    ┌──────────────────────────────────────┐
                    │  a host that runs containers         │
                    │  apps/api + arq worker               │
                    │  Postgres/pgvector · Redis · S3      │
                    └──────────────────────────────────────┘
```

The API half is **not** free. Fly.io, Render or Railway will run the container;
budget roughly $5–10/month, because OpenCV plus Chromium want on the order of a
gigabyte of RAM. Postgres with pgvector is free-tier-able on Neon or Supabase,
Redis on Upstash. Object storage is the one piece Cloudflare _does_ give away —
**R2** is S3-compatible, so it drops into the existing `boto3` paths in place of
MinIO, with a free storage allowance and no egress charge.

## 2 · Why the API is proxied instead of called directly

`next.config.ts` already carried this seam before Cloudflare existed in the
repo: _"The API lives behind the same origin in production (one reverse proxy),
so the browser sends the session cookie without CORS."_ The Worker is now that
reverse proxy.

The browser calls a relative `/api/v1` (`src/lib/api/client.ts`), the Worker
rewrites it to `ALPPY_API_ORIGIN`, and as far as the browser is concerned there
is one origin. That matters more here than it usually would:

- `alppy_session` is `HttpOnly`, `SameSite=Lax`, `Secure`, and set with **no
  `Domain` attribute** (`api/v1/auth.py`) — host-only by design. Same-origin
  keeps it working untouched.
- No preflight on any request, and no `ALPPY_CORS_ORIGINS` to keep in sync.
- Nothing in the front end has to know where the API lives.

**The fallback** — if you would rather point the browser straight at the API —
is already supported: set `NEXT_PUBLIC_API_BASE_URL` to the absolute API URL and
add the Worker's origin to `ALPPY_CORS_ORIGINS`. You then owe the cookie a
`SameSite=None; Secure`, which means editing `auth.py`. Prefer the proxy.

## 3 · One-time setup

```bash
pnpm install
npx wrangler login                    # or set CLOUDFLARE_API_TOKEN
```

Pick the Worker name in [`apps/web/wrangler.jsonc`](../apps/web/wrangler.jsonc)
(`alppy-web` → `alppy-web.<subdomain>.workers.dev`). A custom domain needs the
zone on Cloudflare; the free plan is enough, and it brings TLS with it.

## 4 · Deploying

```bash
# from the repo root
ALPPY_API_ORIGIN=https://api.example.ch pnpm preview:cf   # workerd, locally
ALPPY_API_ORIGIN=https://api.example.ch pnpm deploy:cf    # build + ship
```

`ALPPY_API_ORIGIN` is **baked in at build time** — Next compiles `rewrites()`
into the routes manifest, it is not read at runtime. Changing the API's address
is a rebuild, not a variable edit. Two consequences worth knowing before you are
debugging them at 23:00:

- **Omit it and the Worker serves the app with no API behind it.** Every request
  becomes a 404 against the Worker itself.
- **The origin must not carry a port.** `https://api.example.ch:8443` breaks the
  build's route compiler, which reads `:8443` as a path parameter and fails with
  `Expected "8443" to be a string`. Use a hostname on 443.

## 5 · What the free tier actually gives

Measured on this app, not quoted from a pricing page:

| Free-plan limit               | This app                                             |
| ----------------------------- | ---------------------------------------------------- |
| Worker bundle ≤ 3 MiB gzipped | **1.03 MiB** (`wrangler deploy --dry-run`)           |
| 100 000 Worker requests/day   | HTML and `/api/v1/*` only                            |
| Static assets: unmetered      | 67 files — JS chunks, the self-hosted fonts, `mock/` |
| 10 ms CPU per invocation      | SSR pages are shells; the data arrives client-side   |

`run_worker_first` is left at its default, so a request for
`/_next/static/...` is answered from Workers Assets **without invoking the
Worker** and never touches the daily budget. Page views and proxied API calls
do. A teacher loading twenty screens a day costs ~20 requests, so the ceiling is
not the thing to worry about.

## 6 · Verified, and not yet verified

Confirmed in local workerd (`wrangler dev`) against the real build:

- `/` → 307 → `/fr/login?from=%2F` — locale routing and the session gate both
  survive the edge runtime, which was the open question about `middleware.ts`.
- `/fr/login` renders (200), `/de/classes` without a cookie redirects to
  `/de/login?from=…`.
- A request to `/api/v1/auth/me` reaches the API **with the path intact and the
  `alppy_session` cookie forwarded**.
- Static chunks serve with the right content type.

Not yet exercised against a real backend, so check it on the first deploy:
**a full login round-trip** — specifically that the API's `Set-Cookie` survives
the rewrite back to the browser and that the `Secure` flag is present
(`ALPPY_ENV` must be `staging` or `production`, or the API will not set it).

## 7 · When to revisit

- **The Worker outgrows 3 MiB gzipped.** There is 2 MiB of headroom today. A
  large server-side dependency would eat it; the paid plan raises it to 10 MiB.
- **A screen starts rendering data on the server.** Today every screen fetches
  through TanStack Query in the browser, which is why
  [`open-next.config.ts`](../apps/web/open-next.config.ts) configures no
  incremental cache. Server-rendered data means adding an R2 or KV cache here.
- **The API becomes free to host somewhere.** It will not; the scanner is the
  reason.
- **Swiss data residency is required.** [`privacy.md`](privacy.md) treats
  location of processing as a live constraint. Cloudflare's free plan gives no
  regional guarantee, and the Worker only serves the UI shell — but it does
  proxy every API call, so a school demanding CH-only processing changes this
  decision, not just the API's host.
