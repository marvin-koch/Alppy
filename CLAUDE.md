# CLAUDE.md — working in this repository

Alppy is a teacher-facing tool for Swiss compulsory school (Sek I / cycle 3).
Read [`docs/plan.md`](docs/plan.md) for what it does and
[`DESIGN.md`](DESIGN.md) before touching any UI — with
[`docs/design/constraints.md`](docs/design/constraints.md) beside it, which numbers the
rules that are load-bearing and names what enforces each one.

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
python -m alppy.cli purge-prompt-logs # enforce ALPPY_AI_PROMPT_LOG_RETENTION_DAYS
```

---

## Where things live

| Path | What |
|---|---|
| `apps/web` | Next.js App Router, TypeScript, Tailwind v4, next-intl |
| `apps/api` | FastAPI, SQLAlchemy 2, Alembic, Pydantic |
| `apps/api/alppy/models/__init__.py` | **Every table.** Read [`docs/data-model.md`](docs/data-model.md) before changing one — three columns look like their neighbouring join table and are not |
| `apps/api/alppy/sheets/layout.py` | **Print geometry — the single source of truth** |
| `apps/api/alppy/scan/` | OpenCV registration, bubble detection, grading |
| `apps/api/alppy/ingest/regions.py` | Exercise regions cut from the page geometry (label, crop, `SUITE ▶`) |
| `apps/api/alppy/scan/answer_box.py` | A written-answer box cut from the registered page, Alppy's own ink removed |
| `apps/api/alppy/services/open_answer_grading.py` | The vision grader job: one call per crop, nothing left pending |
| `apps/api/alppy/mastery/model.py` | The mastery model, pure functions (`roll_up_mastery` is the only aggregation above a competency) |
| `apps/api/alppy/services/tree_service.py` | `Class → Branch → Competence → Theme`, with a band on every node |
| `apps/api/alppy/ai/` | Provider-agnostic AI layer, versioned prompts, PII gate |
| `packages/ui/src/design/` | Tokens, base, motion, print, recipes |
| `packages/shared` | Types generated from the OpenAPI document |

---

## Rules that lint cannot catch

These are the ones a reviewer has to enforce by reading. The design half of this list
is indexed as numbered constraints in
[`docs/design/constraints.md`](docs/design/constraints.md), with what enforces each one
and the symptom you would see if it broke — cite the id (`DC-colour-06`) in code where a
line exists because of a rule. The `DC-*` tags below point into it.

**The mandarin accent (`--c-accent-*`) means exactly one thing: AI-generated
content.** *(DC-colour-06)* It marks an exercise a model wrote. If it starts appearing on a
"new" badge or a call-to-action it stops meaning anything, and the teacher loses
the one signal telling them which items need a second look. Only `AiBadge` and
components explicitly marking generated content may use it.

**Caveat (`--font-hand`) appears at most once per page.** *(DC-type-02)* It is the chalk — an
accent on one word of a title, or a handwritten equation. Twice on a page and it
is a typeface instead of a gesture.

**Card and Panel are different objects, not two sizes of the same one.** *(DC-shape-01)* A card
is a *separate object*: radius `lg`, solid edge, shadow. A panel is a
*subdivision of the object you are already in*: radius `md`, border, no shadow.
Shadows everywhere flattens the hierarchy into noise.

**Never colour alone.** *(DC-colour-08)* Every state band carries colour **and** a text label
**and** a differing tint density. On paper it also carries a distinct underline
style. The photocopier is black and white, and roughly one boy in twelve is
colour-blind.

**Violet is ink, not a brand colour.** *(DC-colour-05)* It marks action. It is never decorative.

**Never pure black.** *(DC-colour-07)* Text is `--c-ink-900` (`#1B1735`). Pure black exists only
in high contrast and in print.

**Student-facing text never goes below `body-l` (1.125 rem).** *(DC-type-01)* A product
constraint, not a preference.

**`layout.py` and `print.css` describe the same geometry, and the detector reads
it.** *(DC-print-07)* Changing a number is a **layout version bump**, not a tweak — old scans
must keep registering against the layout they were printed with.

**No student name ever reaches a model provider.** Prompts carry the UID
(`7B_15`). `alppy/ai/scrub.py` is the gate and it *raises* rather than redacting,
because a leak is a caller bug. See [`docs/privacy.md`](docs/privacy.md).

**AI-generated exercises are never printed without teacher approval** *(DC-content-05)*
(`Exercise.approved_at`).

**`ModelCall` is content-free, and stays that way.** It is what a school shows an
auditor to answer "did any of our data go to provider X". The full prompt and
response go to `PromptLog` — a separate table, off by default, capped, swept, and
written only *after* the PII gate passed. A blocked prompt records the refusal and
no content: the string that fired `PiiLeakError` is the one carrying a name.

**A model may revise a partition; it never decides one.** `cluster_students` is the
default, the seed and the fallback. An answer that drops a child, seats one twice or
misses the requested count is rejected, not repaired — the rule has to be one a
teacher can state to a parent.

**Batched generation must keep a plan's failure its own.** A content failure is
isolated per plan; a whole-call failure retries the chunk *once*, split into
single-plan calls. Removing that split silently makes one provider hiccup cost the
whole class.

**A Theme sits under ONE Competence and credits many.** `Chapter.primary_competency_id`
is where a chapter *sits* in `Class → Branch → Competence → Theme → Sheet`; the
`chapter_competency` many-to-many is what it *credits*. They are not
interchangeable — rolling mastery up through the m2m would leak a chapter's
evidence into a curriculum branch its primary never belongs to. The primary is
resolved **per school** from `School.default_curriculum`, which is what lets Sion
and Chur share one chapter (D56, `docs/curriculum.md` §3.1).

**The `unfiled` bucket is excluded by `primary_competency_id IS NULL`, never by its
`key`.** A school may relabel it; a rename must not readmit sheets nobody has filed
into a mastery number. And a sheet is never auto-filed by inferring a Theme from its
items: `Exercise.chapter_id` is itself a guess, and promoting a guess into a filing
the teacher never confirmed is what `approved_at` exists to prevent (D60).

**A rolled-up band never travels alone.** *(DC-content-07)* A Theme, Competence or
Branch band always carries its written label, and carries its coverage — assessed
over total — whenever that coverage is *incomplete*. Green over one assessed
competency and green over three look identical otherwise. Showing "3 sur 3" as well
is not more honest, only louder: it says nothing the band does not, and it crowds
out the theme names. `MasteryBandTag` takes `label` as a *required* prop so a caller
cannot produce a bare coloured pill by omitting an argument.

**Never pool attempts across competencies.** `roll_up_mastery` combines
`MasteryResult`s, each already carrying its own recency. Concatenating the raw
attempts instead derives one recency from the mixture, so a competency practised
last week launders the staleness of one last touched in June — in the model whose
whole purpose is fading. Pooling across *students* is fine and is what
`mastery_service.pool_by_competency` does (D58, `docs/mastery-model.md` §7).

**The builder's Theme picker always shows a counted "Sans thème" row, even at zero.**
*(DC-content-06)* `Exercise.chapter_id` is null on a large minority of a real
textbook, so `chapter_id=none` is a real sentinel, distinct from the parameter being
absent. `ExercisePicker` used to keep "nothing is unreachable" by having no theme
filter at all; now that Theme is its root, that row is what keeps the promise (D59).

**A written answer is graded on a verdict, never on a heuristic.** The vision
grader (`alppy/scan/open_grading.py`, installed through `register_grader`)
scores only what carries a verdict — the model's or the teacher's. Pending,
unreadable and offline all produce no attempt and are counted as skipped. Do
not add text matching, and never let a missing verdict become a zero.

**The expected answer is optional, and the model is told which case it is
in.** `SheetItem.expected_answer` (the teacher's, for this sheet) falls back
to `Exercise.answer_text` (the book's); when both are empty the grader sends
`NO_EXPECTED_ANSWER` and the model works the answer out first, returning it
as `reference`, which is kept on the detection for the teacher to see. Never
substitute a placeholder string for a missing answer — v1 did, and the model
judged against the placeholder.

**An answer box is cut where it printed, never where it was estimated.** *(DC-print-09)* The
render job measures every box in Chromium and writes `AnswerBoxPlacement`;
the scan job crops at those rows. Never recompute a box from the current
`SheetItem` rows: an edit after printing would move what the scanner crops.

**The mark and the mastery signal are two different quantities.**
`Attempt.score` carries the teacher's barème — it may be negative, or larger
than one. `Attempt.correct` is the boolean the mastery model reads, and
`mastery_service` selects only that column. Never feed `score` into mastery: a
marking scheme must not be able to rewrite what the model believes a child
knows. Sheet totals floor at zero; per-item scores stay signed in the record.

**A blank is never penalised, and an ambiguous mark is never scored.** Every
grader settles both before the barème is consulted, so no value a teacher can
type reaches them. `scan.grading.score_for` is the one place a penalty's sign
is applied — the columns store a magnitude, so 0.25 and -0.25 cannot come to
mean two different things.

**A cross reads as a mark, and it is recognised by shape, not by ink.** A
hand-drawn X covers about a quarter of a bubble, well under `FILL_MARKED`.
`_cross_score` counts four lobes in the angular ink profile and returns exactly
0 when it does not find them, so `_mark_strength` collapses to the fill ratio
for every bubble that is not crossed. Keep that gate: it is what makes the
change provably invisible to every mark the degradation suite already covers.

**A crop never leaves the statement region.** *(DC-print-10)* The PII gate reads text only;
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
