# Deploying the API, the worker and their data services

> **Status: a draft that has never been run.** No account exists, no app has
> been created, nothing below has been executed. `infra/fly/fly.toml` and
> `infra/fly/fly.staging.toml` are the configuration this describes, and they
> are drafts in the same sense. Everything marked **[you]** needs a person with
> a credit card and an identity; everything else is in the repository already.
>
> This is the missing half of [`deploy-cloudflare.md`](deploy-cloudflare.md),
> which covers the Next.js app and says of this half only that "Fly.io, Render
> or Railway will run the container" — a sentence, not a configuration (audit
> 07, D4).

---

## 1 · What runs where

```
                    ┌──────────────────────────────────────┐
  teacher's         │  Cloudflare Workers (free)           │
  browser  ────────▶│  apps/web — Next.js via OpenNext     │
                    │  /api/v1/* ──┐  rewrite, same origin │
                    └──────────────┼───────────────────────┘
                                   ▼
                    ┌──────────────────────────────────────┐
                    │  Fly.io, region zrh (Zurich)         │
                    │                                      │
                    │  process "app"    — uvicorn          │
                    │  process "worker" — arq              │   one image, two
                    │                                      │   process groups
                    │  Managed Postgres 16 + pgvector      │
                    │  Upstash Redis (AOF on)              │
                    │  Tigris / R2 — S3-compatible bucket  │
                    └──────────────────────────────────────┘
```

**Why Fly, for an MVP.** It runs a persistent process, which the arq worker
needs and Cloudflare's free tier cannot provide; it is what the existing deploy
document already assumed; and it has a Zurich region, so the machines and
volumes are in Switzerland.

**The honest limit of that choice.** Fly is a US company. The data is in
Zurich; the control plane is not. A cantonal IT department asking about the
CLOUD Act gets a better answer from Exoscale or Infomaniak, both Swiss-owned
with Swiss datacentres. This is a pilot decision, and what keeps it cheap to
reverse is that everything Fly-specific is in two files.

---

## 2 · Before anything else **[you]**

| # | Act | Why it cannot be scripted here |
|---|---|---|
| 1 | Create the Fly account and organisation | Identity and payment |
| 2 | Choose the production domain | HSTS, the cookie and CORS all name it |
| 3 | Decide the vision-grading provider, or leave it `echo` | A DPA is a signature, not a setting — see [`data-protection/subprocessors.md`](data-protection/subprocessors.md) |
| 4 | Read [`runbook/`](runbook/) end to end once | Three of its six procedures cannot be trusted until you have run them |

---

## 3 · Provision, in this order

The order matters: the app refuses to boot without the credentials, so creating
it first gives you a crash loop and a confusing first impression.

### 3.1 Postgres **[you]**

pgvector is not optional — `alppy/services/retrieval.py` is built on it.

```bash
fly postgres create --name alppy-db --region zrh --vm-size shared-cpu-2x --volume-size 10
fly postgres connect -a alppy-db
```

Then, **as the owner**, run `infra/postgres/init.sql`. It creates the second
role, and the second role is the whole of D84: the API connects as `alppy_app`,
which has no DDL and no `BYPASSRLS`, so a query that forgets its
`.where(school_id == ...)` returns nothing instead of another school's roster.
Postgres does not apply a policy to a table's owner — an API connected as the
owner leaves every policy in place and inert, which looks exactly like a
working deployment. `_refuse_unsafe_deployment` refuses to boot when
`ALPPY_ADMIN_DATABASE_URL` is unset or names the same role as
`ALPPY_DATABASE_URL`, which is what stops that state being reachable by saying
nothing.

**Backups.** Fly's managed Postgres takes daily snapshots; set the retention
window deliberately rather than accepting a default — see
[`runbook/restore-from-backup.md`](runbook/restore-from-backup.md), and note
that an untested restore is not meaningfully different from no backup.

### 3.2 Redis **[you]**

```bash
fly redis create --name alppy-redis --region zrh
```

Turn **append-only on** (`appendonly yes`, `appendfsync everysec`). Redis holds
the arq queue: with RDB snapshots alone, an unclean stop loses up to a minute of
enqueued jobs, and what a teacher sees is a scan that never finishes. The
development compose file already sets this; a managed Redis needs it set again.

### 3.3 Object storage **[you]**

Any S3-compatible bucket — Tigris (Fly's own) or Cloudflare R2, which is free
for this volume and has no egress charge.

Two buckets, not one: `alppy-scans` and `alppy-staging-scans`. A staging
instance is refused at startup unless `ALPPY_PRODUCTION_S3_BUCKET` is set and
differs from `ALPPY_S3_BUCKET`.

**Versioning is deliberately off** (`infra/minio/init-bucket.sh`), which means
a delete is a delete — which is what makes `purge-scan-images` a real erasure
and also means there is no undo. Object storage has no backup today (D10);
that is an open item, not a solved one.

### 3.4 The app

```bash
fly apps create alppy
fly secrets set -a alppy \
  ALPPY_SECRET_KEY="$(openssl rand -hex 32)" \
  ALPPY_DATABASE_URL="postgresql+psycopg://alppy_app:...@...:5432/alppy" \
  ALPPY_ADMIN_DATABASE_URL="postgresql+psycopg://alppy:...@...:5432/alppy" \
  ALPPY_REDIS_URL="redis://..." \
  ALPPY_S3_ENDPOINT_URL="https://..." \
  ALPPY_S3_BUCKET="alppy-scans" \
  ALPPY_S3_ACCESS_KEY="..." \
  ALPPY_S3_SECRET_KEY="..." \
  ALPPY_CORS_ORIGINS='["https://app.alppy.ch"]' \
  ALPPY_HEALTH_DETAIL_TOKEN="$(openssl rand -hex 16)"

fly deploy -c infra/fly/fly.toml
```

`fly deploy` runs `release_command` — `alembic upgrade head` — on one machine,
and only proceeds if it succeeds. That is the deploy-time migration step, and
it is why the compose entrypoint's migrate-on-start is explicitly a compose
convenience (D13).

### 3.5 The first teacher **[you, and awkwardly]**

There is no account-provisioning endpoint (D12). Today the only way to create a
teacher is `python -m alppy.cli seed`, which creates the *demo* teacher. Real
onboarding is manual database work. This is a known gap and it is the first
thing an establishment will need.

---

## 4 · What the startup validator will refuse

Not a checklist to work through — the app tells you. `ALPPY_ENV=production`
refuses to boot on: the development secret key (or that key in the fallback
list), the development S3 key, a local-filesystem storage backend, a wildcard or
localhost CORS origin, demo mode, a localhost database, a staging bucket equal
to production's, an `ALPPY_ADMIN_DATABASE_URL` that names the same role as
`ALPPY_DATABASE_URL`, and more than one uvicorn worker on in-process rate-limit
buckets. Every problem is reported together rather than one restart at a time.

---

## 5 · Verify, in this order

```bash
fly status -a alppy                                   # both process groups up
curl -fsS https://api.alppy.ch/api/v1/health          # {"status":"ok", ...}
curl -fsS -H "X-Alppy-Health-Token: $TOKEN" \
     https://api.alppy.ch/api/v1/health/detail        # database/redis/storage
curl -sI https://api.alppy.ch/api/v1/health | grep -i strict-transport
curl -sf https://api.alppy.ch/api/v1/openapi.json     # MUST 404 in production
fly logs -a alppy | grep cron.start                   # the schedule is alive
```

That last one matters more than it looks: it is the only external evidence that
the retention windows are being enforced at all (D2).

---

## 6 · What this document does not yet cover, and why

| Gap | Status |
|---|---|
| **Object-store backup** (D10) | No backup, no versioning, no deletion protection. Open. |
| **A tested restore** (D1) | [`runbook/restore-from-backup.md`](runbook/restore-from-backup.md) is written and has never been executed. Until it has, treat the backup as unproven. |
| **Error tracking** (D8) | The SDK wiring is in the repository and inert; it needs a vendor account. See [`runbook/`](runbook/) and `alppy/core/observability.py`. |
| **Account provisioning** (D12) | §3.5. |
| **A staging environment** (D11) | `infra/fly/fly.staging.toml` exists and has never been deployed. |
| **Real paper** (M9) | The print → scan → grade loop has never been run on a physically printed, physically filled, phone-photographed sheet. This is the single most load-bearing pre-launch task and it is not something a test can do. |
