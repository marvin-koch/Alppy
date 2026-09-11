# Subprocessors

**Status: a maintained draft.** This is the artefact a cantonal IT department or
a DPO asks for first, and it should be answerable in one document rather than
assembled under pressure. It is **not** a DPA, a processing register or a privacy
notice — see [`README.md`](README.md) for what those are and why none of them is
drafted here.

**Update this whenever a vendor changes.** A subprocessor table that is accurate
on the day it is written and stale a term later is worse than none, because it
is presented as current. The change and the table entry belong in the same pull
request.

Last reviewed: **2026-09-11**, against `main`.

---

## 1 · Who processes what

Statuses are honest about the difference between "configured in code",
"deployed", and "does not exist". Several rows are **undecided**, which is a
decision not taken rather than an omission.

| # | Service | Role | Data touched | Processing | At rest | Status |
|---|---|---|---|---|---|---|
| 1 | **Cloudflare Workers** | Web app and reverse proxy for `/api/v1/*` | Every API request and response **transits**; nothing stored | Global anycast — **no regional guarantee on the free plan** | none (transit only) | Deployed |
| 2 | **Fly.io** (proposed) | API + arq worker containers | Everything | Zurich (`zrh`) — US company | n/a | **Drafted, not provisioned** (`infra/fly/`) |
| 3 | **PostgreSQL + pgvector** | Roster, attempts, mastery, detections, audit | Names, UIDs, grades, teacher accounts | Undecided (Fly managed, proposed) | Undecided | Not provisioned |
| 4 | **Object storage** (S3-compatible) | **Scanned pages, answer-box crops, rendered and source PDFs** | **Photographs of minors' handwriting** | Undecided | Undecided | Not provisioned |
| 5 | **Redis** | Job queue and transient job status | UIDs and job metadata; no names | Undecided | ephemeral | Not provisioned |
| 6 | **OpenAI** | Generation and **vision grading** | Prompts (UID, never a name) **and answer-box crops** | United States | `store=False` is now passed on the grading call | **Selectable; not the default** |
| 7 | **Anthropic** | Same | Same | United States | Vendor terms | Selectable |
| 8 | **Offline providers** (`echo` / `hash`) | Same, deterministically | Nothing leaves the process | n/a | n/a | **The default, and a complete stand-in** |
| 9 | **GitHub Actions** | CI, and the nightly golden set | Repository; a real provider key on the golden-set job | United States | n/a | Deployed |
| 10 | Error tracking | — | — | — | — | Wired and **inert** (`core/observability.py`); no vendor chosen |
| 11 | Backups | — | — | — | — | **Do not exist** |
| 12 | CDN | — | — | — | — | Does not exist |
| 13 | E-mail | — | — | — | — | Does not exist — no password reset, no notifications |
| 14 | Analytics | — | — | — | — | Does not exist. **Nothing tracks teachers.** |
| 15 | Log aggregation | — | — | — | — | Does not exist; logs are JSON on stdout |

---

## 2 · Where minors' handwriting is, specifically

The most sensitive artefact in the system, and the one a DPO will ask about by
name. It has three locations, not one:

1. **In the object store, at rest.** `ScanPage.image_key` (whole pages) and
   `Detection.crop_key` (answer boxes). Kept for
   `ALPPY_SCAN_IMAGE_RETENTION_DAYS` — **400 days**, a school year plus one
   term — and swept nightly at 03:30 by the worker's own schedule. Before
   2026-09-11 both halves were missing: the default was 0, meaning forever, and
   nothing ran the purge.
2. **In transit to a model provider, on every written answer** — but only when
   one is configured. The shipped default is `echo`, which sends nothing.
3. **At rest on the provider's side** — now refused explicitly: the OpenAI
   grading call passes `store=False`, so the request and response are not kept
   for the vendor's default 30 days.

**Not** in `ModelCall`. The audit row hashes the image into the prompt hash and
stores neither the image nor the text. `PromptLog` can hold prompt *text* when
a school explicitly enables it: off by default, capped, swept, school-scoped,
and written only after the PII gate has passed.

**What keeps a name out of a crop is geometry, not inspection.**
`measure_answer_boxes` refuses a box outside `ITEMS_TOP_MM..ITEMS_BOTTOM_MM`,
the printed sheet carries a UID and no name, and the crop is cut at the
rectangle the renderer *measured* for that copy rather than one recomputed
later. The residual risk — a pupil writing their own name inside the answer box
— is real, documented, and not mitigated by anything technical.

---

## 3 · Transfers outside Switzerland

> **Not a legal conclusion.** This is the current factual position. Whether each
> vendor is certified under the Swiss–U.S. Data Privacy Framework, and whether
> SCCs plus a transfer impact assessment are additionally required for this data
> class, is a question for counsel and is not answered anywhere in this
> repository.

| Transfer | Destination | Safeguard today |
|---|---|---|
| Every API request, via the Worker | Cloudflare, no regional guarantee | None specific. No DPA reviewed. |
| Generation prompts (UIDs, exercise text) | OpenAI / Anthropic, US | None. No DPA. **Not active — the default provider is offline.** |
| **Answer-box crops (minors' handwriting)** | OpenAI, US | `store=False`. **No DPA.** **Not active — the default provider is offline.** |
| CI | GitHub, US | Repository only; the golden set sends synthetic crops with a real key |

Given that the data subjects are minors and the payload is a school assessment
in their own handwriting, the conservative reading is that any of these would be
a high-sensitivity transfer.

**The two exits exist and cost no engineering.** `ALPPY_AI_CHAT_PROVIDER=echo`
is the current default: the product runs, written answers produce no attempt and
are counted as *skipped* — never a wrong zero — and MCQ and true/false grading is
unaffected. Or point the same setting at a regional or self-hosted vision model.
That the provider is one setting rather than a rewrite is the main payoff of the
AI layer's design, and it is what makes "do not transfer anything until there is
a DPA" a position that can actually be held.

---

## 4 · What has to happen before a transfer is switched on

Engineering can do none of these.

1. A **DPA** with the chosen vendor, reviewed by whoever handles this for the
   business.
2. Confirmation of the vendor's **Swiss–U.S. DPF certification**, or SCCs plus a
   transfer impact assessment.
3. Zero-retention confirmed **on the account**, not only in the request.
   `store=False` is what this code sends; it is not proof of what the vendor
   keeps.
4. The transfer named in the **privacy notice** the school hands to parents.
5. This table updated in the same change that flips the setting.
