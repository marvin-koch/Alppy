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

# Both checks below DROP THE PUBLIC SCHEMA of the database they are given, so
# both refuse anything that is not visibly disposable: a throwaway database
# name, ALPPY_ENV of ci|local, and loopback unless you name the dedicated
# variable (alppy/db/disposable.py). Do NOT hand them ALPPY_DATABASE_URL or
# ALPPY_ADMIN_DATABASE_URL — those are the database the app is serving, and
# reading them is what used to make this a data-loss risk.
createdb alppy_drift alppy_rls

# Migrations reproduce the models. The unit tests build their schema with
# create_all() from the models, so they structurally cannot catch this.
ALPPY_ENV=local \
ALPPY_DISPOSABLE_DATABASE_URL=postgresql+psycopg://user:pw@localhost:5432/alppy_drift \
  python scripts/check-schema-drift.py

# Row-level security: same disposable-Postgres shape, same blind spot. SQLite has
# no roles and no policies, so the unit tests cannot see a policy that was never
# created, a FORCE left off, or the API pointed back at the owning role. This one
# wants the OWNER's credentials — against a database of its own, never the app's.
ALPPY_ENV=local \
ALPPY_DISPOSABLE_DATABASE_URL=postgresql+psycopg://OWNER:pw@localhost:5432/alppy_rls \
  python scripts/check-rls.py

python -m alppy.cli backfill-events   # rebuild the agenda from existing timestamps
python -m alppy.cli purge-prompt-logs # enforce ALPPY_AI_PROMPT_LOG_RETENTION_DAYS
python -m alppy.cli purge-access-log  # enforce ALPPY_ACCESS_LOG_RETENTION_DAYS (read audit)
python -m alppy.cli purge-scan-images # enforce ALPPY_SCAN_IMAGE_RETENTION_DAYS (400 days)
python -m alppy.cli purge-model-calls # enforce ALPPY_MODEL_CALL_RETENTION_DAYS (3 years)
python -m alppy.cli reap-jobs         # fail RUNNING jobs that stopped reporting
python -m alppy.cli health-signals    # override rate, confidence deciles, registration failures

# All six are ALSO on the worker's own schedule (alppy/worker/cron.py) — the
# CLI form is what an operator runs to check, and it is the same code.

# Accounts (D12). There is no e-mail transport and no role, so provisioning is
# a command; the one thing a teacher does for themselves is Settings -> Password.
python -m alppy.cli list-schools
python -m alppy.cli create-teacher --email a@b.ch --first-name A --last-name B --school "<id>"
python -m alppy.cli set-password --email a@b.ch      # prints a generated one, once
python -m alppy.cli grant-school  --email a@b.ch --school "<id>"
python -m alppy.cli revoke-school --email a@b.ch --school "<id>"   # an UPDATE, never a DELETE
python -m alppy.cli list-teachers [--school "<id>"]

make lock                             # re-resolve apps/api/uv.lock + requirements.lock

# Regenerate the PER from CIIP's own API. Needs network; the output is
# COMMITTED, because `docker compose up` must work without one.
python scripts/fetch-per-curriculum.py
```

---

## Where things live

| Path | What |
|---|---|
| `apps/web` | Next.js App Router, TypeScript, Tailwind v4, next-intl |
| `apps/api` | FastAPI, SQLAlchemy 2, Alembic, Pydantic |
| `apps/api/alppy/models/__init__.py` | **Every table.** Read [`docs/data-model.md`](docs/data-model.md) before changing one — §2 lists the columns that look like their neighbouring join table and are not |
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
| `apps/api/alppy/worker/cron.py` | **The schedule.** Every retention window and the stale-job reaper |
| `apps/api/alppy/services/health_signals.py` | Override rate, confidence deciles, registration failures — per school |
| `apps/web/src/lib/config.ts` | The web half of `core/config.py`: every env read, validated once, throws at import |
| `apps/api/alppy/services/account_service.py` | Creating a teacher, passwords, staffroom membership (D12) |
| `infra/fly/` | Deployment definitions — **drafts, nothing provisioned** |
| `docs/runbook/` | Deploy, rollback, restore, secret rotation, worker drain, stuck batch, onboarding |
| `docs/data-protection/` | Subprocessors, DPIA outline, breach procedure |

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

**A partial index needs `sqlite_where` as well as `postgresql_where`.** The
dialect kwarg is *dropped* on other dialects, and the suite builds its schema
with `create_all` on SQLite — so a partial UNIQUE index silently becomes an
absolute one in the only place it ever runs. `uq_class_student_open` spent a
release forbidding a pupil from rejoining a class they had left, which is the
exact case 0027 widened the key to allow (D88).

**A curriculum row belongs to an EDITION, and says whether it is official.**
`uq_competency_code` is `(curriculum, edition_id, code)`. A revised curriculum
lands beside the old one rather than overwriting the rows past bands were
computed from — so never "fix" a competency in place; add an edition and move
what points at it. `is_official` separates what a publisher wrote from what we
invented, and an official row carries a `source_ref` that can be checked.
`scripts/fetch-per-curriculum.py` regenerates the PER from CIIP's own API; the
result is committed, because `docker compose up` has to work with no network.

**Some vocabularies are closed, and a lookup table would be a lie.**
`stream` is a table because a canton must be addable without a migration.
`MasteryBand`, `CurriculumKind` and `Locale` stay enums because a new member
needs a colour token, a glyph, a print style, a seeded curriculum or a message
catalogue — a row that nothing can render is worse than a migration (D88).

**A membership is an interval, and `on` is a required argument.** `class_student`,
`class_teacher_subject` and `teacher_school` carry `valid_from`/`valid_to`, and
leaving is an `UPDATE`, never a `DELETE` (D87). Every subquery in
`services/enrollment.py` takes `on: date` **with no default** — that is not
ceremony, it is what stops a read path keeping the old meaning while the table
underneath it starts returning history, and it is what the renames in 0019 and
0021 bought by renaming. Two reads deliberately take no `on` and point opposite
ways: `ever_enrolled_student_ids` feeds the PII scrub list and must be a
*superset* (a pupil who left in February still wrote their name on the October
copy in the pile), and `ever_shared_student_ids` gates *reading* a pupil's past
on the teacher's window having **overlapped** theirs — not "ever", which would
hand a teacher who arrived in March a pupil who left in October. Acting on a
pupil (rename, re-enrol, delete) stays gated on a CURRENT membership.

**Widening a key is not the same as keeping it unique.** Each of those three
tables carries a partial unique index on the open row (`uq_class_student_open`
and siblings). Without it two rows differing only in `valid_from` are both
open — one child counted twice in every roster join and every matrix column.
It is also why `enroll` is no longer `ON CONFLICT DO NOTHING`.

**`Person` is who a pupil is; `Student` is one year of them.** `attempt`,
`mastery_snapshot`, `mastery_branch_snapshot` and `misconception_note` hang off
`person_id`. The print and scan path stays on the year-bound row —
`sheet_instance`, `answer_box_placement.student_uid`, `scan_page.student_id`,
`exercise_variant.student_id` — because a UID is a fact about one year's paper
and must not change meaning (D87). The two id spaces are deliberately disjoint,
so confusing them is a foreign-key violation rather than a silent success.
Deleting a `Student` no longer destroys evidence; deleting a `Person` does, and
`delete_student` does both.

**Tenancy has two layers now, and the second one only works if the roles stay
apart.** Every query still takes `school_id` as a required argument — that is the
first layer and it does not change. Underneath it, row-level security keyed on
`app.current_school_id` (D84). Postgres does not apply a policy to a table's
owner, so the API connecting as the schema owner leaves every policy in place and
inert, which looks exactly like a working deployment. `ALPPY_DATABASE_URL` is the
low-privilege role, `ALPPY_ADMIN_DATABASE_URL` is the owner, and
`alppy/db/tenancy.py` is the **only** writer of the GUC — bound in
`get_membership` after the `teacher_school` check and nowhere else. An unbound
session sees nothing rather than everything; a handler that reads an empty list
where it expected rows has forgotten `TenantDep`, not found a bug.

**No student name ever reaches a model provider.** Prompts carry the UID
(`7B_15`). `alppy/ai/scrub.py` is the gate and it *raises* rather than redacting,
because a leak is a caller bug. See [`docs/privacy.md`](docs/privacy.md).

**AI-generated exercises are never printed without teacher approval** *(DC-content-05)*
(`Exercise.approved_at`).

**Every retention window is enforced by `worker/cron.py`, and nowhere else.**
Four correct, tested CLI commands existed and nothing ran any of them, so every
window was a promise kept by somebody remembering. A window with no cron entry
is not a window. The purges are nightly and never `run_at_startup` — a worker
restarting six times during a deploy must not purge six times — and the reaper
runs every five minutes *and* at startup, because a worker coming back from a
crash is exactly when there are stale `RUNNING` rows refusing a teacher's
confirmation. `test_worker_cron.py` pins the set.

**The override rate is a comparison, never a count of `CORRECTED`.**
`correct_detection` stamps `CORRECTED` whether the teacher agreed or disagreed,
so counting outcomes measures attention and reports it as error. `Detection`'s
write-once `machine_*` columns are the other half of the comparison and are the
only reason the question can be asked at all — never overwrite them.

**A rate-limit bucket in this process is worth N times its stated value for N
workers.** `ALPPY_RATE_LIMIT_BACKEND` decides where it lives and the startup
validator refuses `api_workers > 1` on `memory`. Do not "simplify" that guard
away: the failure it prevents is invisible — the limit is still configured, still
enforced, and worth four times what it says.

**A spend cap bounds what can be STARTED.** `AiBudget` sits beside `AiRateLimit`
at the API boundary, not inside `AiClient.complete` — that object is deliberately
usable with no database, and a check at the point of the call abandons a class
set half-graded.

**No log line identifies a pupil.** The access line carries the route, not the
row: `core/logging.py:scrub_path` replaces identifiers by SHAPE, so a route
added next year is covered without anybody remembering, and the route survives
because that is the line's whole diagnostic value. `test_log_hygiene.py` is what
keeps it true. The one deliberate exception is `privacy.erasure`, which carries
a `person_id` and a UID and never a name — it exists to OUTLIVE the database,
because after a restore every erasure since the restore point has to be
re-applied and a record inside the restored database is gone with it.

**An error tracker's `before_send` is the load-bearing part.** A default-configured
tracker sends the request body, which on this API is transcriptions of what a
named child wrote and presigned links to photographs of their handwriting. See
`core/observability.py`; session replay is absent, not sampled at zero.

**A failure crosses to the client as a code; the client owns the sentence.** An
exception's own text is never assigned to a field a browser reads. `Source.error`
holds prose written for a teacher (`ingest/pipeline.py:_teacher_facing_error`),
`Job.error` holds a value from `services/job_failure.py:FAILURE_CODES`, and a
screen renders `apiErrorMessage(err, t)` — never `error.message`, which
`api/client.ts` says plainly is for the console. `str(exc)` in any of those three
is a SQLAlchemy failure's SQL, an `OSError`'s server paths, or a bucket and its
endpoint, on a screen that is regularly projected onto a classroom wall (D86).

**The CSP nonce is why the locale layout is `force-dynamic`.** Next stamps the
nonce onto its own inline scripts only while rendering, so a prerendered shell
serves a dozen un-nonced `__next_f.push` blocks and never hydrates. Do not
"optimise" that export away without re-measuring the built HTML. The theme script
is allowed by hash instead, and `theme-script.test.ts` is what keeps the hash and
the script from drifting (D86).

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
