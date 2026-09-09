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

The full model, table by table, is [`data-model.md`](data-model.md); this is the
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

```
POST   /auth/login                 POST /auth/logout        GET /auth/me
PATCH  /teachers/me/preferences    (locale, theme, contrast, motion, calm)

GET    /classes                    POST /classes            GET /classes/{id}
GET    /classes/{id}/students      POST /classes/{id}/students   (roster paste)
GET    /subjects                   GET  /curricula/{kind}/competencies
GET    /chapters                   POST /chapters

POST   /sources                    (upload PDF -> job)      GET /sources/{id}
GET    /sources/{id}/status        GET /sources/{id}/sections
GET    /sources/{id}/exercises     (section/chapter/type/difficulty/q, paged, faceted)
POST   /sources/{id}/sections/{sid}/extract   -> job   (read one chapter on demand)
POST   /exercises                  PATCH /exercises/{id}

POST   /sheets/propose             (class, subject, chapters[], intent) -> ranked exercises + provenance
POST   /sheets                     PATCH /sheets/{id}       GET /sheets/{id}
POST   /sheets/preview             (an UNSAVED draft, rendered; persists nothing)
POST   /sheets/{id}/render         -> job -> blank.pdf + answer-key.pdf
GET    /sheets/{id}/preview        (server-rendered HTML using the same print.css)

POST   /scans                      (upload pages -> job)
GET    /scans/{id}                 GET /scans/{id}/detections
PATCH  /scans/{id}/detections/{d}  (teacher correction)
POST   /scans/{id}/confirm         -> Attempts -> mastery recompute

GET    /classes/{id}/mastery       (matrix: students × competencies, band + score)
GET    /students/{id}/mastery      (profile: strengths, gaps, trend)
POST   /adaptive/propose           (class or student, gap targeting)
POST   /adaptive/batch             -> job -> one PDF, one .print-page per physical page

GET    /jobs/{id}                  GET /health
```

Frontend consumes `packages/shared`, generated from the served OpenAPI schema — never from
assumptions.

## 5. Screens

1. `/login`
2. `/` teacher home — classes, subjects, quick stats (last sheet, pending corrections, students needing attention)
3. `/classes/[classId]` — roster + mastery matrix (five bands)
4. `/classes/[classId]/students/[studentId]` — profile: rings, curve, history
5. `/sources` — upload + ingestion status + extracted exercises
6. `/sheets/new` — builder, document-first: source + chapter of that book, the exercises it holds
   (filtered and paged server-side), tick / reorder / edit / add your own, with the A4 preview
   behind a toggle. A second tab keeps the RAG path (intent, ranked proposals, provenance).
7. `/sheets/[id]` — print preview (blank + answer key), download
8. `/scans/new` + `/scans/[id]` — upload, then review overlay with confidence bars
9. `/adaptive` — gap targeting, accent-marked AI items, batch export
10. `/settings` — locale, theme, contrast, motion, calm
11. `/timeline` — the agenda: every event in order, grouped by day, filterable
    by kind and searchable by title

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
