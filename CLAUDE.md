# CLAUDE.md — working in this repository

Alppy is a teacher-facing tool for Swiss compulsory school (Sek I / cycle 3).
Read [`docs/plan.md`](docs/plan.md) for what it does and
[`DESIGN.md`](DESIGN.md) before touching any UI.

## The brand library is shipped, not described — use it

`docs/design/` holds the real **"Craie Alpine"** identity: the manual
(`Alppy-identite-visuelle.pdf`, 8 A3 plates), the philosophy note, and
`alppy-brand-assets/brand/` with `logo/` (26 files), `icons/` (48 pictograms),
`illustrations/` (7), `mastery/` (5 band glyphs) and `alppy-mastery-tokens.css`.

**Import those files. Do not redraw them.** Where the shipped assets disagree
with prose anywhere else in the repo, including DESIGN.md, **the assets win**:

- The mark is **"Le sourire"** — two slopes meeting at a summit with a smile in
  the valley, forming an **A**, on a violet rounded slate. Not a slate crossed
  by a chalk stroke.
- **The mark carries no mandarin accent.** The accent is functional inside the
  product; putting it in the logo spends it on decoration.
- **Pictogram stroke is 2.2 — never 2, never 3.**
- `--c-mastery-ok` is **`#86CF5B`**, and every band ships a `-glyph` colour at a
  constant luminance of 0.46 with a *computed* background opacity, so the ramp
  stays monotonic in greyscale. That calibration is the whole point: the sheets
  get photocopied. Do not re-derive these by eye.
- Band glyphs are disc 4/4, 3/4, 2/4, 1/4 and a dashed ring — the third channel.

---

## Commands

```bash
docker compose up                  # whole stack + demo seed, one command
pnpm dev                           # web + api in dev (needs postgres/redis/minio up)
pnpm build | lint | typecheck | test
pnpm test:e2e                      # Playwright
pnpm i18n:check                    # fails on a key missing from any locale

PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests -q
.venv/bin/ruff check apps/api && .venv/bin/mypy --config-file apps/api/pyproject.toml apps/api/alppy

# Migrations reproduce the models. Needs a DISPOSABLE Postgres: it drops the
# public schema. The unit tests build their schema with create_all() from the
# models, so they structurally cannot catch this.
ALPPY_DATABASE_URL=postgresql+psycopg://... python scripts/check-schema-drift.py

python -m alppy.cli backfill-events   # rebuild the agenda from existing timestamps
```

---

## Where things live

| Path | What |
|---|---|
| `apps/web` | Next.js App Router, TypeScript, Tailwind v4, next-intl |
| `apps/api` | FastAPI, SQLAlchemy 2, Alembic, Pydantic |
| `apps/api/alppy/sheets/layout.py` | **Print geometry — the single source of truth** |
| `apps/api/alppy/scan/` | OpenCV registration, bubble detection, grading |
| `apps/api/alppy/ingest/regions.py` | Exercise regions cut from the page geometry (label, crop, `SUITE ▶`) |
| `apps/api/alppy/scan/answer_box.py` | A written-answer box cut from the registered page, Alppy's own ink removed |
| `apps/api/alppy/services/open_answer_grading.py` | The vision grader job: one call per crop, nothing left pending |
| `apps/api/alppy/mastery/model.py` | The mastery model, pure functions |
| `apps/api/alppy/ai/` | Provider-agnostic AI layer, versioned prompts, PII gate |
| `packages/ui/src/design/` | Tokens, base, motion, print, recipes |
| `packages/shared` | Types generated from the OpenAPI document |

---

## Rules that lint cannot catch

These are the ones a reviewer has to enforce by reading.

**The mandarin accent (`--c-accent-*`) means exactly one thing: AI-generated
content.** It marks an exercise a model wrote. If it starts appearing on a
"new" badge or a call-to-action it stops meaning anything, and the teacher loses
the one signal telling them which items need a second look. Only `AiBadge` and
components explicitly marking generated content may use it.

**Caveat (`--font-hand`) appears at most once per page.** It is the chalk — an
accent on one word of a title, or a handwritten equation. Twice on a page and it
is a typeface instead of a gesture.

**Card and Panel are different objects, not two sizes of the same one.** A card
is a *separate object*: radius `lg`, solid edge, shadow. A panel is a
*subdivision of the object you are already in*: radius `md`, border, no shadow.
Shadows everywhere flattens the hierarchy into noise.

**Never colour alone.** Every state band carries colour **and** a text label
**and** a differing tint density. On paper it also carries a distinct underline
style. The photocopier is black and white, and roughly one boy in twelve is
colour-blind.

**Violet is ink, not a brand colour.** It marks action. It is never decorative.

**Never pure black.** Text is `--c-ink-900` (`#1B1735`). Pure black exists only
in high contrast and in print.

**Student-facing text never goes below `body-l` (1.125 rem).** A product
constraint, not a preference.

**`layout.py` and `print.css` describe the same geometry, and the detector reads
it.** Changing a number is a **layout version bump**, not a tweak — old scans
must keep registering against the layout they were printed with.

**No student name ever reaches a model provider.** Prompts carry the UID
(`7B_15`). `alppy/ai/scrub.py` is the gate and it *raises* rather than redacting,
because a leak is a caller bug. See [`docs/privacy.md`](docs/privacy.md).

**AI-generated exercises are never printed without teacher approval**
(`Exercise.approved_at`).

**A written answer is graded on a verdict, never on a heuristic.** The vision
grader (`alppy/scan/open_grading.py`, installed through `register_grader`)
scores only what carries a verdict — the model's or the teacher's. Pending,
unreadable and offline all produce no attempt and are counted as skipped. Do
not add text matching, and never let a missing verdict become a zero.

**An answer box is cut where it printed, never where it was estimated.** The
render job measures every box in Chromium and writes `AnswerBoxPlacement`;
the scan job crops at those rows. Never recompute a box from the current
`SheetItem` rows: an edit after printing would move what the scanner crops.

**A crop never leaves the statement region.** The PII gate reads text only;
what keeps a name out of an image is geometry. `measure_answer_boxes` refuses
a box outside `ITEMS_TOP_MM..ITEMS_BOTTOM_MM`. Keep it that way.

---

## Conventions

- **Commits:** Conventional Commits, small and focused. `main` always builds.
- **TypeScript:** strict, no `any`. **Python:** mypy strict, no bare
  `# type: ignore` — always with a reason.
- **No colour literals** outside `tokens.css` and `print.css` (CI fails on it).
  Those two are exempt because the print block *overwrites* tokens rather than
  bypassing them.
- **No icon library, no font CDN.** Icons are drawn in `packages/ui/src/icons`;
  fonts are self-hosted via `@fontsource-variable`.
- **i18n:** three catalogues (`fr` default, `de`, `en`) kept in sync by CI. No
  string literals in components. Exercise content follows the language of the
  source material, never the UI locale.
- **Responsive:** mobile-first. The product is used on a phone in the classroom
  and a laptop at a desk. Touch targets ≥ 44 px.
- **Every screen ships empty, loading (with a `shape`) and error states.**
- **Nothing blocks a request handler on a model call.** Long work goes to the
  arq worker and reports progress through `Job`.

---

## Assumptions log

Decisions taken without asking are recorded in
[`docs/decisions-log.md`](docs/decisions-log.md). Add to it rather than leaving a
choice implicit in a diff.
