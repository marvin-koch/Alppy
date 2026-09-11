# Alppy — implementation plan

Status: living document. Updated as milestones land.

## 1. Product in one paragraph

Alppy is a teacher-facing tool for Swiss compulsory school (Sek I / cycle 3). A teacher uploads
their textbook PDFs, builds an exercise sheet for a lesson, prints it, has students complete it on
paper, scans the copies back in, gets MCQ/true-false items auto-graded, reviews the detections, and
watches a five-band mastery matrix update. From that matrix the teacher generates **adaptive,
per-student sheets** combining textbook-retrieved exercises with AI-generated ones. The adaptive
sheet is the focal deliverable; everything else exists to make it possible and trustworthy.

## 2. Milestones

| M | Name | Contents | Demoable outcome |
|---|---|---|---|
| M0 | Foundation | monorepo, docker compose, CI, auth + tenancy, `packages/ui` tokens/recipes/themes, i18n, nav shell (F7) | Log in, switch class/subject/locale/theme |
| M1 | Corpus | classes/students/subjects CRUD, curriculum seed (LP21 + PER), PDF ingestion + chunk + embed, exercise extraction | Upload a PDF, see extracted exercises |
| M2 | Sheets | sheet builder with RAG proposals + provenance, print preview, server PDF with fiducials + UID grid, answer key (F1) | Download blank sheet + answer key |
| M3 | Scan | scan upload, fiducial registration, deskew, UID read, bubble detection, review UI with confidence, grading (F2) | Scan back in, review, confirm grades |
| M4 | Mastery | mastery model, five-band matrix, student profiles, curve (F3) | Matrix updates from confirmed grades |
| M5 | Adaptive | per-student gap targeting, retrieval + accent-marked AI generation, batch class export (F4) | One differentiated PDF for a whole class |
| M6 | Polish | empty/loading/error states, e2e + theme/locale screenshots, demo seed (1 class, 1 subject, 3 weeks), README, handover | Definition of done (§9 of brief) |
| M7 | Groups & feedback | ZPD stretch targeting, N personalised groups from one common sheet, per-student misconception notes as their own printed document (F9) | Correct a common sheet, get four group sheets and a feedback page each |
| M8 | Agenda | append-only `event` log, `/timeline` with facets and search, sheet lineage (`derived_from_id`) (F10) | See a term in order, and click back to any of it |

## 3. Domain model as implemented

The full model, table by table, is [`data-model.md`](data-model.md), and the ER
diagrams layer by layer are in [`er-model.md`](er-model.md); this is the
sketch. Tenancy: every row carries `school_id` (and `teacher_id` where ownership
is personal).
Every table has `id` (UUID), `created_at`, `updated_at`.

```
School ──< Teacher (locale, theme, contrast, motion, calm)
       ──< SchoolYear ──< Class (code "7B") ──< Student (uid "7B_15", first/last name)
       ──< Subject
Class ──<  Student   home_class_id                 (the class that MINTED the uid
      and the number: exactly one, NOT NULL, RESTRICT — deleting it is refused
      rather than cascading a term of evidence away. D69)
Class ──>< Student                                 (class_student — who SITS where.
      A pupil attends several of one teacher's classes, and a roster, a matrix,
      a tree and a printed pile all mean THIS set, never the home. D69)
Class ──>< Subject                                 (class_subject, ordered by
      first use — the Branches a class DECLARES it studies, not inferred; D57)
Curriculum (LP21 | PER) ──< Competency (hierarchical, code, subject, cycle)
Chapter (teacher grouping) ──>< Competency        (chapter_competency — what it
                                                   CREDITS, both curricula)
        ──> Competency  primary_competency_id      (where it SITS in the tree:
                                                    one node, resolved per school
                                                    from default_curriculum; NULL
                                                    only on the `unfiled` bucket.
                                                    D56, D60)
Source (uploaded PDF) ──< SourceChunk (text, page, embedding vector(1024))
                      ──< SourceSection (the book's own chapter: title, label,
                          page range, extracted_at — read on demand)
Exercise (type mcq|true_false|open, origin textbook|ai_generated|teacher,
          statement, options, answer_key, difficulty, source_chunk_id,
          source_section_id, page,
          label "NO64", title, figure_key + figure size in mm — a crop of
          the page, cut by the region detector; see decisions-log D40)
        ──>< Competency                            (exercise_competency)
        ──< ExerciseVariant (per-student generated)
Sheet (target class|student|group, layout_version, subject,
       chapter_id NOT NULL -> its home Theme, `unfiled` when nobody filed it (D60),
       derived_from_id -> the COMMON sheet this one answers)
     ──< SheetItem (ordered exercise ref, position, statement_override, expected_answer,
                    answer_box_lines 0..14 (presets 3|5|8|12), answer_box_fill lined|grid|blank)
     ──< AnswerBoxPlacement (student_uid × copy_page × item_index -> x/y/w/h mm,
                             measured at render time, replaced on re-render)
     ──< SheetInstance (bound to a student uid, its own item order/variants,
                        group_label, feedback_id)
MisconceptionNote (student × common sheet, notes[], approved_at — the gate)
Event (append-only: kind, occurred_at, actor, subject_type/subject_id, summary)
Scan (uploaded page images) ──< ScanPage ──< Detection (item, detected answer, confidence,
                                              crop_key, transcription, verdict_correct + machine_*)
Attempt (student × exercise × sheet_instance, correct, score, answered_at)
MasterySnapshot (student × competency × computed_at, score [0,1], band)
ModelCall (audit: provider, model, prompt hash, tokens, latency, cost, no PII)
```

**The teaching hierarchy**, which the navigation, the dashboards and the student
profile all read the same way:

```
Class  ──  Branch      = Subject, via class_subject
       ──  Competence  = the PARENT of a chapter's primary_competency
                         (or the primary itself when it is already top-level)
       ──  Theme       = Chapter, via primary_competency_id
       ──  Sheets      = Sheet.chapter_id
```

`GET /classes/{id}/tree` returns it with a rolled-up mastery band on every node
(`roll_up_mastery`, `docs/mastery-model.md` §7). The `unfiled` chapter is excluded
from the tree by `primary_competency_id IS NULL` and surfaced separately as
`unfiled_sheet_count`, so sheets nobody has filed stay findable without entering a
mastery number.

`open` exercises print a delimited **answer box** (height and fill chosen per `SheetItem`).
The render job measures where every box landed and writes one `AnswerBoxPlacement` per copy and
page; the scan job crops there, stores the crop beside the page image and leaves the detection
`PENDING`; a chained `GRADE_OPEN_ANSWERS` job sends each crop to a vision model, which returns a
transcription and a verdict against `Exercise.answer_text`. The grader scores only a verdict —
the model's or the teacher's — and nothing reaches mastery before the teacher confirms the pile.
Without a key the echo provider returns no verdict and the item is reported as skipped.

## 4. API surface (FastAPI, `/api/v1`)

**The list of routes is generated, not written here.**
[`packages/shared/src/api-routes.generated.ts`](../packages/shared/src/api-routes.generated.ts)
holds every `METHOD /path` the application serves, and what each one returns;
[`api-types.generated.ts`](../packages/shared/src/api-types.generated.ts) beside it holds
every shape that crosses the wire. Both come from `create_app().openapi()` via
`scripts/generate-api-types.py`, and CI regenerates and diffs them, so neither can drift
from the routers.

This section used to be a hand-maintained block of about thirty-five routes. The API
serves ninety-six. It had also gone quietly wrong in the usual way: it gave
`POST /adaptive/batch` the shape `-> job -> one PDF`, where the route answers with a
`SheetOut` and the render is a separate call. That is the failure a document which
repeats a source of truth eventually has, and the reason this is a pointer now
(audit 02, M11).

What is worth stating here is the *shape* of the surface, which the generated list cannot
say:

- **One error envelope.** Every failure crosses as `{error: {code, message, details,
  request_id}}`. The code is the contract; the sentence belongs to the client, which has
  one for every code the API can raise — `check-i18n.mjs` fails the build otherwise.
- **Ownership is resolved from data, never from a claim.** A route takes `ScopeDep`
  (school + teacher) and asks `get_class` / `get_student` / `taught_here`; a colleague's
  class reads as **404, never 403**, so a response cannot confirm that an id exists.
- **Nothing blocks a handler on a model call.** Anything that reaches a provider answers
  `202` with a `JobOut` and reports progress through `GET /jobs/{id}`.
- **Reads answer "now" unless asked otherwise.** `as_of` on the computed reads, `on` on
  the rosters, `school_year_id` on the lists — with `GET /school-years` to discover the
  ids (D87, audit 02 C3).
- **Collections that grow are paged** — `{items, total, offset, limit}`, where `total`
  counts the filtered set and not the page.

## 5. Screens

The 24 teacher-facing routes, as `apps/web/src/app/[locale]/` registers them.
Two more exist and are not screens: a catch-all that raises `notFound()` so an
unmatched path is answered in the teacher's own language, and `/_gallery`, the
component workbench, which is gated on fixture mode.

**`pnpm screens:check` fails if this list and the route tree disagree.** Unlike §4
this section is not generated, and deliberately: each line says what a screen is
*for*, which no generator can produce and which is the only reason to read the
section. So the prose stays written and the check guards the half that drifts
silently — the set of paths. This list had gone stale at eleven of twenty-four, and
two audits in a row asked whether it was still the record (audit 05 open question
7). It is; this is what keeps it so.

**Entry**

1. `/login`
2. `/` — teacher home: classes, disciplines, quick stats (last sheet, pending
   corrections, pupils needing attention)

**Classes and pupils**

3. `/classes` — the class index
4. `/classes/new` — create a class and paste its roster in one screen
5. `/classes/[classId]` — the class dashboard: programme beside the mastery
   matrix (five bands)
6. `/classes/[classId]/students` — the roster, with what each pupil needs
   attention on
7. `/classes/[classId]/roster` — paste more pupils, fix a name, remove a leaver
8. `/classes/[classId]/students/[studentId]` — profile: rings, curve, history
9. `/classes/[classId]/students/[studentId]/sheets/[sheetId]` — one pupil on
   one sheet, item by item
10. `/classes/[classId]/competences/[competencyId]` — one competency down the
    whole class
11. `/classes/[classId]/themes/[chapterId]` — one Theme: its sheets and what
    they showed
12. `/classes/[classId]/teaching` — who teaches which discipline here, and what
    the class studies

**Documents and sheets**

13. `/sources` — upload + ingestion status + extracted exercises
14. `/sheets` — every sheet for the class and discipline in scope
15. `/sheets/new` — the builder, document-first: source + chapter of that book,
    the exercises it holds (filtered and paged server-side), tick / reorder /
    edit / add your own, with the A4 preview behind a toggle. A second tab keeps
    the RAG path (intent, ranked proposals, provenance).
16. `/sheets/[sheetId]` — preview (blank + answer key), render, print

**Correction**

17. `/scans` — the piles, and which are still to review
18. `/scans/new` — photograph or upload a pile against the sheet it answers
19. `/scans/[scanId]` — the review overlay: the registered page beside the
    machine's reading, least-confident first

**Across the class**

20. `/results` — points per pupil per sheet
21. `/adaptive` — gap targeting, accent-marked AI items, batch export
22. `/timeline` — the agenda: every event in order, grouped by day, filterable
    by kind and searchable by title

**Settings**

23. `/settings` — language, theme, contrast, motion, calm, discreet; the
    establishment and its disciplines
24. `/settings/branches/[subjectId]` — one discipline's themes and competencies

## 6. Mastery model (documented fully in `docs/mastery-model.md`)

Two factors, per (student, competency) — weighted recent accuracy, then how much
we still trust it given how long ago the student last practised:

```
w_i      = exp(-ln(2) * age_days_i / HALF_LIFE_DAYS) * difficulty_weight_i
accuracy = Σ(w_i * correct_i) / Σ(w_i)
recency  = 1 if idle ≤ 0 else max(FLOOR, 2^(-idle / RECENCY_HALF_LIFE_DAYS))
score    = accuracy × recency                  ∈ [0,1]
```

`HALF_LIFE_DAYS = 21`, `RECENCY_HALF_LIFE_DAYS = 45`, `GRACE = 7`, `FLOOR = 0.55`.
Bands: ≥0.90 solid · 0.75–0.90 ok · 0.60–0.75 weak · <0.60 fading · no attempts →
none. Explainable, cheap to recompute, no BKT.

Targeting reads the bands weakest-first and treats `solid` as a **stretch**
target at lowest priority — one per sheet, and the whole sheet for a student who
has nothing else. Skipping it, as the first version did, sent a child who had
mastered everything to the difficulty-2 diagnostic: easier work than they could
already do (decisions-log D32).

The second factor is not optional: `accuracy` is scale-invariant under uniform
time decay, so without `recency` a perfect record would read as mastered forever
and the "fading" band would never fade (decisions-log D4).
`docs/mastery-model.md` is the authority on the constants.

## 7. Open assumptions

Tracked in `docs/decisions-log.md`; the ten most consequential are repeated in `docs/handover.md`.

### 7.1 Decisions that were correct by accident until somebody wrote them down

Each of these was already true in the code and true for a reason, and none of them was recorded as
a *decision* — so each read as a gap to whoever found it next, and the third audit found them all
again (2026-09-10).

**A Swiss 1–6 note is planned scope, not the current output.** Alppy reports points and mastery
bands, and converting those into a report-card note is today the teacher's act. That stays true for
now, but the answer to "will it ever?" is **yes, eventually** — so the mastery model and the barème
are to be designed with it in mind rather than around it. Two things it will need and does not have:
a per-school rounding convention (cantons differ, and half-points are not universal), and a stated
position on whether a note comes from the barème (points earned over points possible on one sheet)
or from mastery (a decayed estimate across competencies). They are not the same number and the
difference will be argued about, so it should be argued about before anything prints a `4.5`.

**`ClassKind` (migration 0026) is a placeholder, and nothing reads it.** It is a nullable
discriminator recording whether a class is a homeroom or a teaching group; NULL means "not
declared" and is explicitly **not** a synonym for `homeroom`, because every row predating the
column predates the question. It stays unread until the homeroom/teaching-group distinction is
actually needed by a screen — at which point the alternative (splitting the entity) should be
revisited rather than assumed away by the column already existing.

**A substitute teacher keeps what they marked** (D88). Reading a sheet is widened to anyone who has
ever taught that (class, branch); acting on one — printing, editing, billing a model call — stays
current-only. Two functions used to disagree about this in the same call stack.

**Anyone in the staffroom may approve an AI-generated exercise for print.** The flat staffroom is
deliberate (D85): membership *is* the permission model and there is no admin tier. Approval is not
an exception to that, and it is not intended to become one — but it is the single act that stands
between something a model wrote and something a child is handed, so since B21 it is *recorded* with
its author (`EventKind.EXERCISE_APPROVED`), as is editing an answer key after a sheet has been
printed (`EXERCISE_EDITED`). The permission model did not change; the acts became answerable.

**Cantonal scope is all 26 cantons.** `School.canton` is validated against the full list rather
than a pilot pair: a school in a canton nobody has piloted should be refused for being *wrong*,
never for being unexpected. This also sets the bit budget for any layout-v2 UID redesign — a canton
needs five bits there, which competes directly with the per-render nonce width, and that trade-off
is unresolved.

**Still genuinely open**, and each blocking something concrete: how long scan images may be kept
(the purge command refuses to run without a number — `docs/privacy.md` §4), and whether a
photograph of a child's handwriting may be processed outside CH/EU (`docs/privacy.md` §3).

## 8. Workstreams

(a) data model + migrations + API · (b) ingestion + RAG + extraction · (c) design system in
`packages/ui` · (d) print layout + PDF + scan detection + grading (co-designed, one owner) ·
(e) frontend screens · (f) QA + CI.

## 9. Responsive — phone and desktop (added at user request)

The teacher UI is used on a laptop at a desk **and** on a phone in the classroom (scanning copies
with the phone camera is an explicit workflow in F2). Mobile is not a degraded desktop.

- **Mobile-first.** Base styles target 360–430 px; breakpoints add complexity upward.
  Breakpoints: `sm 640` · `md 768` · `lg 1024` · `xl 1280`.
- **Navigation.** Below `md` the class/subject rail collapses into a slide-in drawer plus a bottom
  tab bar for the four primary destinations; at `md`+ it is a persistent left rail.
- **The mastery matrix** is the hard case: below `md` it scrolls horizontally inside its own
  `overflow-x:auto` container with a sticky student-name column. The page body never scrolls
  sideways.
- **Touch targets** are already the design floor (44 px min-height on `.ard-btn`, `.ard-input`).
  Detection-correction controls in the scan review get 44 px hit areas even when visually smaller.
- **Scan capture on mobile** uses `<input type="file" accept="image/*" capture="environment">` so
  the phone opens the camera directly.
- **Print preview** on a phone shows the A4 page scaled to fit (`transform: scale()` on a wrapper),
  never a horizontally scrolling page.
- **Tested**, not assumed: Playwright screenshot tests run every theme/locale combination at both
  390×844 (phone) and 1440×900 (desktop).
