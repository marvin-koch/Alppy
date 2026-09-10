# Entity–relationship model, layer by layer

**Status:** describes `main` at 2026-09-10 (migration head `0025_timestamp_defaults`).
**Authority:** the code, in this order — `apps/api/alppy/models/__init__.py` (tables),
`apps/api/alembic/versions/` (what actually ran on a database),
`apps/api/alppy/schemas/__init__.py` (the wire contract),
`apps/web/src/lib/api/types.ts` (what the client believes the wire contract is).
Where this document and those files disagree, the files win and this document is stale.

This is an **audit** document: it enumerates every table, every foreign key, every
cardinality and every delete rule, then follows the same objects up through the
domain, contract and UI layers. It complements rather than replaces
[`data-model.md`](data-model.md), which explains *why* the shapes are what they are
and is the better first read. This one is the map.

---

## 0 · How to read this

### 0.1 Notation

Diagrams are Mermaid `erDiagram`. Crow's-foot cardinality is read left-to-right:

```
A ||--o{ B     exactly one A  ⟶  zero or more B
A ||--|{ B     exactly one A  ⟶  one or more B
A }o--|| B     zero or more A ⟵  exactly one B
A }o--o{ B     many-to-many (always a physical join table here)
A ||--o| B     exactly one A  ⟶  zero or one B
```

Relationship labels name the **column**, not the English sentence, because the column
is what you grep for. A label in *italics* in the prose means the FK is nullable.

### 0.2 Three facts true of every table

1. **UUID v4 primary key**, generated in Python (`_pk()`), never a sequence. No table
   has a natural or composite primary key except the seven association tables, which
   have composite ones and no surrogate id.
2. **`created_at` / `updated_at`**, timezone-aware, `server_default now()`,
   `onupdate now()` (`TimestampMixin`). No exceptions.
3. **`school_id`**, `NOT NULL`, `ON DELETE CASCADE`, indexed (`SchoolScopedMixin`) —
   on all but three tables. The three exceptions are named in §3.

### 0.3 Inventory

36 tables plus `alembic_version`: **29 mapped classes** and **7 association tables**
declared as bare `Table()` objects.

| Group | Tables |
|---|---|
| Tenancy & people (§2.1) | `school`, `teacher`, `teacher_school`, `school_year`, `class`, `student`, `subject`, `class_subject`, `class_teacher_subject`, `class_student` |
| Curriculum (§2.2) | `competency`, `chapter`, `chapter_competency` |
| Corpus (§2.3) | `source`, `source_section`, `source_chunk`, `exercise`, `exercise_competency`, `exercise_variant` |
| Sheets & printing (§2.4) | `sheet`, `sheet_source`, `sheet_item`, `sheet_instance`, `answer_box_placement`, `misconception_note` |
| Scan & grading (§2.5) | `scan`, `scan_page`, `detection`, `attempt` |
| Mastery (§2.6) | `mastery_snapshot`, `mastery_branch_snapshot` |
| Operations & audit (§2.7) | `event`, `job`, `adaptive_proposal`, `model_call`, `prompt_log` |

---

## 1 · The layer map

Five layers hold the same objects at different altitudes. Each one is allowed to
depend downward only, and two of the boundaries are enforced mechanically.

```mermaid
flowchart TB
    subgraph UI["UI layer — apps/web"]
        direction LR
        Pages["24 route pages<br/>app · locale · **/page.tsx"]
        Hooks["75 TanStack Query hooks<br/>lib/api/queries.ts"]
        TS["Hand-mirrored DTO types<br/>lib/api/types.ts"]
        Pages --> Hooks --> TS
    end

    subgraph Contract["Contract layer — HTTP"]
        DTO["≈110 Pydantic models<br/>alppy/schemas/__init__.py"]
        Routers["12 routers<br/>alppy/api/v1/*.py"]
        Routers --> DTO
    end

    subgraph Domain["Domain layer — pure + service"]
        Services["20 services<br/>alppy/services/*.py"]
        Pure["Pure functions<br/>mastery/model.py · sheets/layout.py · scan/grading.py"]
        Services --> Pure
    end

    subgraph Data["Data layer"]
        PG[("PostgreSQL + pgvector<br/>36 tables")]
        S3[("Object storage<br/>PDFs · page images · crops · figures")]
        Redis[("Redis — arq queue")]
    end

    Tenancy["Tenancy — cross-cutting<br/>school_id argument + RLS policies"]

    TS -.->|"JSON over HTTP<br/>NO generated client (§8.1)"| Routers
    DTO --> Services
    Services --> PG
    Services --> S3
    Routers -->|"enqueue"| Redis --> Worker["arq worker<br/>7 job kinds"] --> Services
    Tenancy -.-> Services
    Tenancy -.-> PG
```

**Enforced boundaries.** `scripts/check-schema-drift.py` proves the migrations
reproduce the models; `scripts/check-rls.py` proves the tenancy layer is live on a
real Postgres; `scripts/export-layout.py` + `packages/shared/src/layout.generated.ts`
prove the web app's print geometry is the API's. **Unenforced:** the DTO ⟶ TypeScript
boundary — see §8.1.

---

## 2 · Data layer

### 2.1 Tenancy and people

```mermaid
erDiagram
    SCHOOL ||--o{ TEACHER : "home_school_id"
    SCHOOL }o--o{ TEACHER : "teacher_school"
    SCHOOL ||--o{ SCHOOL_YEAR : "school_id"
    SCHOOL ||--o{ SUBJECT : "school_id"
    SCHOOL_YEAR ||--o{ CLASS : "school_year_id"
    SCHOOL_YEAR ||--o{ STUDENT : "school_year_id"
    TEACHER ||--o{ CLASS : "head_teacher_id (RESTRICT)"
    CLASS ||--o{ STUDENT : "home_class_id (RESTRICT)"
    CLASS }o--o{ STUDENT : "class_student"
    CLASS }o--o{ SUBJECT : "class_subject (ordered)"
    CLASS ||--o{ CLASS_TEACHER_SUBJECT : "class_id"
    TEACHER ||--o{ CLASS_TEACHER_SUBJECT : "RESTRICT"
    SUBJECT ||--o{ CLASS_TEACHER_SUBJECT : "subject_id"

    SCHOOL {
        uuid id PK
        string name
        string canton "2 chars, nullable"
        enum default_curriculum "LP21 | PER"
    }
    TEACHER {
        uuid id PK
        uuid home_school_id FK "where the account is BASED"
        string email UK "uq_teacher_email, global"
        string password_hash
        enum locale "fr | de | en"
        string theme "null | light | dark"
        string contrast "null | high"
        string motion "null | off"
        string calm "null | on"
    }
    SCHOOL_YEAR {
        uuid id PK
        uuid school_id FK
        string label "2025/26"
        date starts_on
        date ends_on
        bool is_current
    }
    SUBJECT {
        uuid id PK
        uuid school_id FK
        string key UK "uq_subject_key(school_id, key)"
        jsonb labels "locale to text"
    }
    CLASS {
        uuid id PK
        uuid school_id FK
        uuid school_year_id FK
        uuid head_teacher_id FK "maitre de classe, NOT NULL"
        string code UK "uq_class_code(school, year, code)"
        string label "nullable"
    }
    STUDENT {
        uuid id PK
        uuid school_id FK
        uuid home_class_id FK "minted the uid, NOT NULL"
        uuid school_year_id FK
        string uid UK "uq_student_uid(school, year, uid) - 7B_15"
        int number "CHECK > 0"
        string first_name
        string last_name
    }
    CLASS_TEACHER_SUBJECT {
        uuid class_id PK "composite FK to class_subject"
        uuid teacher_id PK
        uuid subject_id PK
        timestamptz assigned_at
    }
```

**Cardinality and optionality**

| Relationship | Cardinality | Optional? | Delete |
|---|---|---|---|
| `school → teacher.home_school_id` | 1 : N | required | CASCADE |
| `teacher_school` | M : N | — | CASCADE both ends |
| `school → school_year` | 1 : N | required | CASCADE |
| `school_year → class` | 1 : N | required | CASCADE |
| `class.head_teacher_id → teacher` | N : 1 | required | **RESTRICT** |
| `student.home_class_id → class` | N : 1 | required | **RESTRICT** |
| `class_student` | M : N | — | CASCADE both ends |
| `class_subject` | M : N, ordered by `position` | — | CASCADE both ends |
| `class_teacher_subject` | M : N : N | — | teacher **RESTRICT**; composite FK → `class_subject` CASCADE |

**The two rules this sub-schema exists to enforce.**

- *Where a row sits* is a column; *what it belongs to* is a join table. `Teacher`
  has both (`home_school_id` + `teacher_school`), and so does `Student`
  (`home_class_id` + `class_student`) and `Class`
  (`head_teacher_id` + `class_teacher_subject`). Reading the column where the join
  table is meant is the bug class [`data-model.md` §2](data-model.md) enumerates.
- `class_teacher_subject` carries a **composite foreign key** to
  `class_subject(class_id, subject_id)`, so "you cannot be assigned a branch this
  class does not study" is a constraint, not a convention. It is only *enforced* on
  Postgres — the unit suite's SQLite does not enable `PRAGMA foreign_keys` — which is
  why `class_service.assign_branch` declares the subject first regardless.

**No temporal columns anywhere in this group.** `teacher_school.joined_at`,
`class_student.enrolled_at` and `class_teacher_subject.assigned_at` are provenance;
there is deliberately no `left_at` / `ended_at`. Leaving is a deleted row. The moment
an end date exists, every membership check on every request grows a temporal
predicate.

### 2.2 Curriculum

```mermaid
erDiagram
    COMPETENCY ||--o{ COMPETENCY : "parent_id (SET NULL)"
    SUBJECT ||--o{ CHAPTER : "subject_id"
    COMPETENCY ||--o{ CHAPTER : "primary_competency_id (SET NULL)"
    CHAPTER }o--o{ COMPETENCY : "chapter_competency"

    COMPETENCY {
        uuid id PK
        enum curriculum "LP21 | PER"
        string code UK "uq_competency_code(curriculum, code)"
        uuid parent_id FK "nullable, self"
        string subject_key "matches subject.key BY STRING"
        int cycle
        jsonb labels
        jsonb description
    }
    CHAPTER {
        uuid id PK
        uuid school_id FK
        uuid subject_id FK
        uuid primary_competency_id FK "NULL only on the unfiled bucket"
        string key UK "uq_chapter_key(school, subject, key)"
        jsonb labels
        int position
    }
```

Three things a reader has to know before touching this:

1. **`competency` is not school-scoped.** It is shared reference data: both Swiss
   curricula (LP21, PER) live in one table, distinguished by `curriculum`. It has no
   `school_id` and no RLS policy.
2. **`competency.subject_key` joins to `subject.key` by string**, not by foreign key —
   which is why `uq_subject_key(school_id, key)` is load-bearing. Two subjects keyed
   `mathematics` in one school would split the curriculum silently.
3. **`chapter.primary_competency_id` and `chapter_competency` answer different
   questions.** The column is where a Theme *hangs* in the navigation tree; the join
   table is every code it *credits*, legitimately across both curricula. The
   `unfiled` bucket is the one row with a NULL primary, and `tree_service` excludes it
   by `primary_competency_id IS NULL` — never by matching `key`, because a school may
   rename it.

The navigation tree is derived, not stored:
`Class → Branch (subject) → Competence (chapter.primary_competency.parent_id, or itself
when already top-level) → Theme (chapter) → Sheet`.

### 2.3 Corpus

```mermaid
erDiagram
    SUBJECT ||--o{ SOURCE : "subject_id"
    TEACHER ||--o{ SOURCE : "uploaded_by_id (SET NULL)"
    SOURCE ||--o{ SOURCE_SECTION : "source_id"
    SOURCE ||--o{ SOURCE_CHUNK : "source_id"
    SUBJECT ||--o{ EXERCISE : "subject_id"
    CHAPTER ||--o{ EXERCISE : "chapter_id (SET NULL, an INFERENCE)"
    SOURCE ||--o{ EXERCISE : "source_id (SET NULL)"
    SOURCE_SECTION ||--o{ EXERCISE : "source_section_id (SET NULL)"
    SOURCE_CHUNK ||--o{ EXERCISE : "source_chunk_id (SET NULL)"
    EXERCISE }o--o{ COMPETENCY : "exercise_competency"
    EXERCISE ||--o{ EXERCISE_VARIANT : "exercise_id"
    STUDENT ||--o{ EXERCISE_VARIANT : "student_id (nullable)"

    SOURCE {
        uuid id PK
        uuid school_id FK
        uuid subject_id FK
        uuid uploaded_by_id FK "nullable"
        string filename "what was uploaded"
        string title "what the teacher calls it"
        string publisher
        string isbn
        string url
        string storage_key "sources/{school}/{source}/{leaf}"
        string sha256 "indexed"
        int page_count
        enum status "job_status"
        text error "teacher-facing prose"
        text notice "a caveat on a SUCCESS"
    }
    SOURCE_SECTION {
        uuid id PK
        uuid source_id FK
        string title
        string label "the number the book prints"
        int page_from
        int page_to
        int position UK "uq_source_section_position(source_id, position)"
        timestamptz extracted_at "NULL = indexed, never transcribed"
        text extraction_notice
    }
    SOURCE_CHUNK {
        uuid id PK
        uuid source_id FK
        int page
        int position
        text text
        vector embedding "pgvector, dim from settings"
    }
    EXERCISE {
        uuid id PK
        uuid school_id FK
        uuid subject_id FK
        uuid chapter_id FK "nullable - a guess, never a filing"
        uuid source_section_id FK "nullable"
        int source_page
        string label "the book's code, e.g. NO64"
        string title
        string figure_key "crop in object storage"
        float figure_width_mm
        float figure_height_mm
        enum type "mcq | true_false | open"
        enum origin "textbook | ai_generated | teacher"
        string language "source language, NOT ui locale"
        text statement
        jsonb options
        int answer_index
        bool answer_bool
        text answer_text
        int difficulty "CHECK 1..5"
        timestamptz approved_at "gate: never printed without it"
        timestamptz discarded_at "kept, so the next run won't re-propose"
        jsonb generation_meta
    }
```

**`source_section` is not `chapter`, and the distinction is the whole design.** A
section is a fact about the *file* ("4 · Les fractions, p. 112–131"), always present,
needing no setup. A chapter is the teacher's own grouping mapped to curriculum codes,
and an exercise reaches one only by inference — which needs three things to be true at
once, so on a real textbook a large minority of `exercise.chapter_id` are NULL. That
NULL is why the builder ships a counted "Sans thème" row (DC-content-06).

**Indexes worth knowing:** `ix_exercise_source_section(source_section_id, source_page)`
is the builder's hot path; `ix_exercise_discarded` is **partial**
(`WHERE discarded_at IS NOT NULL`) and serves exactly one query — "what has this
teacher already rejected" — asked by the next generation run.

**`exercise_variant` is declared but never written.** See §8.2.

### 2.4 Sheets and printing

```mermaid
erDiagram
    CLASS ||--o{ SHEET : "class_id"
    SUBJECT ||--o{ SHEET : "subject_id"
    CHAPTER ||--o{ SHEET : "chapter_id (NOT NULL, RESTRICT)"
    TEACHER ||--o{ SHEET : "created_by_id (SET NULL)"
    SHEET ||--o{ SHEET : "derived_from_id (SET NULL)"
    SHEET }o--o{ SHEET : "sheet_source (ordered)"
    SHEET ||--o{ SHEET_ITEM : "sheet_id (cascade delete-orphan)"
    EXERCISE ||--o{ SHEET_ITEM : "exercise_id (RESTRICT)"
    SHEET ||--o{ SHEET_INSTANCE : "sheet_id"
    STUDENT ||--o{ SHEET_INSTANCE : "student_id"
    MISCONCEPTION_NOTE ||--o| SHEET_INSTANCE : "feedback_id (SET NULL)"
    SHEET ||--o{ ANSWER_BOX_PLACEMENT : "sheet_id"
    EXERCISE ||--o{ ANSWER_BOX_PLACEMENT : "exercise_id (SET NULL)"
    STUDENT ||--o{ MISCONCEPTION_NOTE : "student_id"
    SHEET ||--o{ MISCONCEPTION_NOTE : "based_on_sheet_id (SET NULL)"

    SHEET {
        uuid id PK
        uuid school_id FK
        uuid class_id FK
        uuid subject_id FK
        uuid chapter_id FK "the ONE Theme the teacher stated"
        uuid derived_from_id FK "the principal source sheet"
        string title
        enum target "class | student | group"
        string language
        text intent
        string layout_version "v1 - versioned WITH the detector"
        float default_points_correct "CHECK 0..20"
        float default_points_penalty "CHECK 0..20, a MAGNITUDE"
        string blank_pdf_key
        string answer_key_pdf_key
        string feedback_pdf_key "its OWN document, never extra pages"
        timestamptz rendered_at
    }
    SHEET_ITEM {
        uuid id PK
        uuid sheet_id FK
        uuid exercise_id FK
        int position UK "uq_sheet_item_position(sheet_id, position)"
        text statement_override
        int answer_box_lines "CHECK NULL or 0..14"
        enum answer_box_fill "lined | grid | blank"
        text expected_answer "falls back to exercise.answer_text"
        float points_correct "NULL = use sheet default"
        float points_penalty "NULL = use sheet default"
    }
    SHEET_INSTANCE {
        uuid id PK
        uuid sheet_id FK
        uuid student_id FK "UK uq_instance_student(sheet_id, student_id)"
        string student_uid "indexed, denormalised"
        jsonb item_plan "(exercise_id, variant_id, position) rows"
        int page_count
        string group_label "a printable LABEL, not a FK"
        uuid feedback_id FK "nullable"
    }
    ANSWER_BOX_PLACEMENT {
        uuid id PK
        uuid sheet_id FK
        uuid exercise_id FK "nullable"
        string student_uid "UK with copy_page, item_index"
        int copy_page "1-based, the student's own folio"
        int item_index "page-local 0..15"
        int box_lines
        enum box_fill
        float x_mm
        float y_mm
        float w_mm
        float h_mm
        string layout_version
    }
```

**`answer_box_placement` is the only table in the schema that stores measured
geometry.** A bubble sits where the layout fixes it, so the detector derives it from
the item index alone; a written-answer box sits under a statement whose height the
browser decides, so the only honest source is the render that went to the printer.
Written wholesale at render time and replaced on every re-render, keyed
`(sheet_id, student_uid, copy_page, item_index)` — exactly how a `Detection` is
resolved. Editing a `SheetItem` after printing therefore cannot move the rectangle the
scanner crops (DC-print-09).

**Two sheet-lineage relationships, deliberately.** `derived_from_id` is the *one*
principal source the feedback page prints; `sheet_source` is *every* sheet whose
corrected results justified this one, ordered, with `position = 0` asserted to be the
same row as `derived_from_id` (`sheet_service.create_adaptive_sheet`).

**`misconception_note` is neither a column on `Attempt` nor an `ExerciseVariant`.** It
is a synthesis over several wrong answers, addressed to the student, gated by
`approved_at` through the same module as a generated exercise (`services/approval.py`).

### 2.5 Scan and grading

```mermaid
erDiagram
    SHEET ||--o{ SCAN : "sheet_id (SET NULL)"
    TEACHER ||--o{ SCAN : "uploaded_by_id (SET NULL)"
    SCAN ||--o{ SCAN_PAGE : "scan_id (cascade delete-orphan)"
    STUDENT ||--o{ SCAN_PAGE : "student_id (SET NULL)"
    SHEET_INSTANCE ||--o{ SCAN_PAGE : "sheet_instance_id (SET NULL)"
    SCAN_PAGE ||--o{ DETECTION : "scan_page_id (cascade delete-orphan)"
    SHEET_ITEM ||--o{ DETECTION : "sheet_item_id (SET NULL)"
    EXERCISE ||--o{ DETECTION : "exercise_id (SET NULL)"
    TEACHER ||--o{ DETECTION : "corrected_by_id (SET NULL)"
    DETECTION ||--o| ATTEMPT : "detection_id (SET NULL)"
    STUDENT ||--o{ ATTEMPT : "student_id"
    EXERCISE ||--o{ ATTEMPT : "exercise_id (RESTRICT)"
    SHEET ||--o{ ATTEMPT : "sheet_id (SET NULL)"
    SCAN ||--o{ ATTEMPT : "confirmed_scan_id (SET NULL)"

    SCAN {
        uuid id PK
        uuid school_id FK
        uuid sheet_id FK "nullable"
        uuid uploaded_by_id FK "nullable"
        string storage_key "first file, kept for old rows"
        jsonb storage_keys "every uploaded file, in order"
        string layout_version "copied from the sheet ONCE"
        enum status "uploaded|processing|needs_review|confirmed|failed"
        timestamptz confirmed_at "never cleared on reopen"
        timestamptz reopened_at
        int confirmation_count "status + count = the derived label"
    }
    SCAN_PAGE {
        uuid id PK
        uuid scan_id FK
        int page_index "index in the UPLOAD"
        string image_key
        bool registered "four fiducials found, deskewed"
        jsonb registration_meta
        string detected_uid "indexed"
        float uid_confidence
        uuid student_id FK "nullable"
        uuid sheet_instance_id FK "nullable"
        bool wrong_class "a real UID from another class"
        bool discarded "kept for audit, ignored by confirm"
        int page_in_copy "which page of THAT student's copy"
    }
    DETECTION {
        uuid id PK
        uuid scan_page_id FK
        uuid sheet_item_id FK "nullable"
        uuid exercise_id FK "resolved from THIS copy's plan"
        int item_index "page-local"
        int printed_number "what the paper says"
        int detected_index "current value, teacher may overwrite"
        bool detected_bool "only meaningful on true_false"
        float confidence
        enum outcome "detected|low_confidence|blank|multiple|corrected|not_gradeable|pending"
        int machine_index "written ONCE, never updated"
        enum machine_outcome "written ONCE"
        float machine_confidence "written ONCE"
        jsonb fill_ratios "per-bubble, for the review overlay"
        jsonb bubble_boxes "normalised 0..1 frame coords"
        string crop_key "the answer box, Alppy's ink removed"
        text transcription
        text machine_transcription "written ONCE"
        bool verdict_correct
        bool machine_verdict_correct "written ONCE"
        string vision_model "audit trail, never the prompt"
        text reference_answer "what the grader judged against"
        uuid corrected_by_id FK "nullable"
        timestamptz corrected_at
    }
    ATTEMPT {
        uuid id PK
        uuid school_id FK
        uuid student_id FK
        uuid exercise_id FK
        uuid sheet_id FK "nullable"
        uuid sheet_instance_id FK "nullable"
        uuid detection_id FK "nullable"
        uuid confirmed_scan_id FK "which confirmation wrote this"
        bool correct "the ONLY column mastery reads"
        float score "the bareme - may be negative"
        int difficulty "copied from the exercise at write time"
        timestamptz answered_at
    }
```

**The unique constraint that keeps mastery honest.**
`uq_attempt_student_exercise_sheet(student_id, exercise_id, sheet_id)`. Mastery is a
weighted mean over attempts, so a duplicate silently doubles one lesson's weight
against every other. `confirm_scan` supersedes rather than inserts; the constraint is
the backstop that makes that a guarantee rather than an intention.

**Every machine reading is kept beside the teacher's.** Six columns
(`machine_index`, `machine_outcome`, `machine_confidence`, `machine_transcription`,
`machine_verdict_correct`) are written once at detection time and never updated. "The
teacher disagreed with the scanner" is the fact worth auditing, and it is
unrecoverable once overwritten.

**`attempt.score` and `attempt.correct` are two different quantities and must never
merge.** `score` carries the teacher's barème (signed, possibly > 1); `correct` is the
boolean the mastery model reads, and `mastery_service` selects only that column.

### 2.6 Mastery

```mermaid
erDiagram
    STUDENT ||--o{ MASTERY_SNAPSHOT : "student_id"
    COMPETENCY ||--o{ MASTERY_SNAPSHOT : "competency_id"
    STUDENT ||--o{ MASTERY_BRANCH_SNAPSHOT : "student_id"
    SUBJECT ||--o{ MASTERY_BRANCH_SNAPSHOT : "subject_id"

    MASTERY_SNAPSHOT {
        uuid id PK
        uuid school_id FK
        uuid student_id FK
        uuid competency_id FK
        timestamptz computed_at "invariant: one per student, comp, day"
        float score "CHECK 0..1"
        enum band "solid|ok|weak|fading|none"
        int attempts_count
        timestamptz last_attempt_at
    }
    MASTERY_BRANCH_SNAPSHOT {
        uuid id PK
        uuid school_id FK
        uuid student_id FK
        uuid subject_id FK
        timestamptz computed_at
        float score "CHECK 0..1"
        enum band
        int child_count "the denominator, never dropped"
        int assessed_child_count
    }
```

**Nothing reads either table to answer "what is this child's band".** Every read path
recomputes from `Attempt` rows, because the score decays with time — a matrix opened
on Friday must not show Monday's numbers. These two tables exist so a *history curve*
has points to draw and a dashboard has something cheap to sort by. Both are
historical questions, and history is the one thing recomputation cannot give you.

"One row per student, competency, day" is an **application** invariant
(`I-mastery-07`), held by `mastery_service.recompute_for_students`. There is no
unique constraint behind it — `ix_mastery_student_competency` is a plain index — so
a second writer of these tables would have nothing stopping it.

They are two tables rather than one with a nullable `competency_id`: making that
column optional would let "one row per student, competency, day" silently admit two
kinds of row.

`mastery_branch_snapshot` carries its own coverage (`assessed_child_count` /
`child_count`) because a branch band over one assessed competency and one over three
are different claims, and a cached number that dropped the denominator would be
exactly the dishonesty DC-content-07 forbids on screen.

Written by `mastery_service.recompute_for_students`, called from
`scan_service` at confirm and unvalidate time, and from the seed. Nowhere else.

### 2.7 Operations and audit

```mermaid
erDiagram
    JOB ||--o| ADAPTIVE_PROPOSAL : "job_id (UK, CASCADE)"
    JOB ||--o{ PROMPT_LOG : "job_id (SET NULL)"
    MODEL_CALL ||--o{ PROMPT_LOG : "model_call_id (SET NULL)"
    SHEET ||--o{ PROMPT_LOG : "sheet_id (SET NULL)"
    TEACHER ||--o{ EVENT : "actor_id (SET NULL)"
    CLASS ||--o{ EVENT : "class_id (CASCADE)"
    SUBJECT ||--o{ EVENT : "subject_area_id (SET NULL)"

    EVENT {
        uuid id PK
        uuid school_id FK
        enum kind "11 verbs, in the teacher's vocabulary"
        timestamptz occurred_at "NOT created_at"
        uuid actor_id FK "nullable"
        enum subject_type "source | sheet | scan | class"
        uuid subject_id "deliberately NOT a foreign key"
        uuid class_id FK "nullable"
        uuid subject_area_id FK "nullable"
        string summary "never PII - a title, a filename"
        jsonb detail "counts only, no free text"
    }
    JOB {
        uuid id PK
        uuid school_id FK
        enum kind "7 kinds"
        enum status "queued|running|succeeded|failed"
        float progress
        string message
        jsonb payload
        jsonb result
        text error "a CODE from FAILURE_CODES, never str(exc)"
        timestamptz started_at
        timestamptz finished_at
    }
    MODEL_CALL {
        uuid id PK
        uuid school_id FK
        string provider
        string model
        string purpose
        string prompt_name
        string prompt_version
        string prompt_sha256 "proves WHICH prompt without the content"
        int input_tokens
        int output_tokens
        int latency_ms
        float cost_estimate_chf
        bool ok
    }
    PROMPT_LOG {
        uuid id PK
        uuid school_id FK
        uuid model_call_id FK "the content-free twin"
        uuid job_id FK "nullable"
        uuid sheet_id FK "nullable"
        string request_id "a STRING - not every unit of work is a row"
        text system_text "off by default, swept, capped"
        text user_text
        text response_text
    }
    ADAPTIVE_PROPOSAL {
        uuid id PK
        uuid school_id FK
        uuid job_id FK "UK uq_adaptive_proposal_job"
        jsonb payload "~1 MB, read once, then stale"
    }
```

**`event.subject_id` is deliberately not a foreign key.** The log must outlive what it
describes — a deleted sheet does not un-happen — and one column cannot point at four
tables. The agenda resolves the title itself and degrades to `summary` when the row is
gone. Its only query is `ix_event_school_occurred(school_id, occurred_at)`.

**`model_call` and `prompt_log` are a deliberate pair, not a redundancy.**
`model_call` is content-free by construction, safe to keep indefinitely, and is what a
school shows an auditor to answer "did any of our data go to provider X". `prompt_log`
is the engineer's window: **off by default** (`ALPPY_AI_PROMPT_LOG_ENABLED`), written
**only after the PII gate passed**, and **swept**
(`ALPPY_AI_PROMPT_LOG_RETENTION_DAYS`, `python -m alppy.cli purge-prompt-logs`). A
prompt that fired `PiiLeakError` records the refusal and no content.

**`adaptive_proposal` is not `job.result`.** A class of 24 with 8 items each is close
to a megabyte of JSON, and the review screen polls the job every 900 ms; putting the
proposal in the status row would re-serialise it on every poll to answer a question
about progress.

### 2.8 The whole schema in one picture

Foreign keys only, association tables drawn as diamonds. Dashed edges are nullable.

```mermaid
flowchart LR
    subgraph T["Tenancy & people"]
        School --> Teacher
        School --- TS{{teacher_school}} --- Teacher
        School --> SchoolYear --> Class
        School --> Subject
        SchoolYear --> Student
        Teacher --> Class
        Class --> Student
        Class --- CS{{class_student}} --- Student
        Class --- CSu{{class_subject}} --- Subject
        Class --- CTS{{class_teacher_subject}} --- Teacher
        CTS --- Subject
    end

    subgraph C["Curriculum"]
        Competency --> Competency
        Subject --> Chapter
        Competency -.-> Chapter
        Chapter --- CC{{chapter_competency}} --- Competency
    end

    subgraph K["Corpus"]
        Subject --> Source --> SourceSection
        Source --> SourceChunk
        Subject --> Exercise
        Chapter -.-> Exercise
        SourceSection -.-> Exercise
        SourceChunk -.-> Exercise
        Exercise --- EC{{exercise_competency}} --- Competency
        Exercise --> ExerciseVariant
    end

    subgraph S["Sheets & printing"]
        Class --> Sheet
        Chapter --> Sheet
        Sheet -.-> Sheet
        Sheet --- SS{{sheet_source}} --- Sheet
        Sheet --> SheetItem --> Exercise
        Sheet --> SheetInstance --> Student
        Sheet --> AnswerBoxPlacement
        MisconceptionNote -.-> SheetInstance
        Student --> MisconceptionNote
    end

    subgraph G["Scan & grading"]
        Sheet -.-> Scan --> ScanPage --> Detection
        ScanPage -.-> Student
        ScanPage -.-> SheetInstance
        Detection -.-> SheetItem
        Detection -.-> Exercise
        Detection -.-> Attempt
        Student --> Attempt --> Exercise
        Scan -.-> Attempt
    end

    subgraph M["Mastery"]
        Student --> MasterySnapshot --> Competency
        Student --> MasteryBranchSnapshot --> Subject
    end

    subgraph O["Operations"]
        Job --> AdaptiveProposal
        Job -.-> PromptLog
        ModelCall -.-> PromptLog
        Teacher -.-> Event
        Class -.-> Event
    end
```

### 2.9 Referential integrity — the exceptions that matter

`ON DELETE CASCADE` is the module default (`models._fk`). Every departure from it is
deliberate, and each one protects a different thing:

| Foreign key | Action | What it protects |
|---|---|---|
| `student.home_class_id → class` | **RESTRICT** | Deleting a class must not delete a child who also sits elsewhere. `attempt`, `mastery_snapshot`, `sheet_instance` all cascade from `student` — this is the door in front of them |
| `class.head_teacher_id → teacher` | **RESTRICT** | A class must not evaporate with an account |
| `class_teacher_subject.teacher_id → teacher` | **RESTRICT** | Ownership is assignment-based; cascading would strip a class of its last owner — a roster of named children nobody can open, with no error anywhere |
| `sheet.chapter_id → chapter` | **RESTRICT** | Printed sheets must survive a Theme being deleted |
| `sheet_item.exercise_id → exercise` | **RESTRICT** | A printed sheet must survive a corpus edit |
| `attempt.exercise_id → exercise` | **RESTRICT** | Evidence must survive a corpus edit |
| `competency.parent_id` | SET NULL | A curriculum reshuffle orphans, it does not delete |
| `chapter.primary_competency_id` | SET NULL | …and a Theme with a NULL primary falls out of the tree, which is the `unfiled` semantics |
| `exercise.{chapter,source,source_chunk,source_section}_id` | SET NULL | Provenance is optional by construction |
| `sheet.derived_from_id`, `misconception_note.based_on_sheet_id`, `scan.sheet_id`, `attempt.{sheet,sheet_instance,detection,confirmed_scan}_id`, `scan_page.{student,sheet_instance}_id`, `detection.{sheet_item,exercise,corrected_by}_id`, `answer_box_placement.exercise_id`, `prompt_log.*`, `event.{actor,subject_area}_id`, `*.uploaded_by_id`, `sheet.created_by_id` | SET NULL | The record outlives what it points at |
| `sheet_source` (both ends) | CASCADE | SET NULL is unavailable on a composite PK: the lineage row goes with the sheet, so the chain shortens rather than dangling |
| `class_teacher_subject → class_subject` (composite) | CASCADE | An assignment must not outlive the declaration it hangs from |

**Cascade blast radius, worst case.** Deleting a `School` removes every one of the 26
scoped tables' rows for that tenant, plus its teachers (`home_school_id` CASCADE) and
every association row. Deleting a `Student` is the only operation allowed to destroy
evidence: it takes that child's attempts, snapshots, instances and variants with it.
Deleting a `Class` is **blocked** while any student is homed in it; unenrolling
(dropping one `class_student` row) destroys nothing.

### 2.10 The non-relational stores

| Store | Contents | Key / lifetime |
|---|---|---|
| Object storage (S3 / MinIO; local FS in CI) | uploaded PDFs, page images, answer-box crops, page-figure crops, rendered PDFs | see below |
| Redis | the arq queue and `keep_result = 3600 s` of job payload | ephemeral; `job` in Postgres is the durable record |

Storage key namespaces, all built server-side from server-side values
(`storage.storage_key`, which reduces any client filename to one safe segment):

```
sources/{school_id}/{source_id}/{filename}                  the uploaded book
figures/{school_id}/{source_id}/p{page:03d}-{label}.png     an exercise's figure crop
scans/{school_id}/{scan_id}/{index:03d}-{filename}          each uploaded photo/PDF
scan-pages/{school_id}/{scan_id}/page-{i:03d}.png           the registered page image
scan-pages/{school_id}/{scan_id}/page-{i:03d}-box-{j:02d}.png   one answer-box crop
sheets/{sheet_id}/{layout_version}/blank.pdf                ← note: no school segment
sheets/{sheet_id}/{layout_version}/answer-key.pdf
sheets/{sheet_id}/{layout_version}/feedback.pdf
sheets/{sheet_id}/{layout_version}/adaptive-batch[-answer-key].pdf
```

The `sheets/` namespace carries the **layout version** so an old scan stays resolvable
against the exact document it was printed from. It is also the one namespace whose
second segment is not `school_id` — see §8.3.

**Which columns hold keys:** `source.storage_key`, `exercise.figure_key`,
`scan.storage_key` + `scan.storage_keys[]`, `scan_page.image_key`,
`detection.crop_key`, `sheet.{blank,answer_key,feedback}_pdf_key`. Nothing else in the
schema references an object.

---

## 3 · Tenancy layer (cross-cutting)

Tenancy is **two independent layers**, and the second only works if the database roles
stay apart.

```mermaid
flowchart TB
    Cookie["session cookie<br/>(teacher_id, school_id)"] --> Dep

    subgraph L1["Layer 1 — application"]
        Dep["deps.get_membership<br/>SELECT on teacher_school"]
        Scope["Scope(school_id, teacher_id)"]
        Query["every service query takes<br/>school_id as a REQUIRED argument"]
        Dep --> Scope --> Query
    end

    subgraph L2["Layer 2 — Postgres RLS"]
        Bind["db/tenancy.py — the ONLY writer of the GUC<br/>set_config('app.current_school_id', …, is_local => true)"]
        Rebind["after_begin listener<br/>re-applies on every transaction"]
        Policy["tenant_isolation policy<br/>ENABLE + FORCE on 33 tables"]
        Bind --> Rebind --> Policy
    end

    Dep -->|"after the membership check,<br/>and nowhere else"| Bind
    Query --> Policy --> Rows[(rows)]

    Owner["ALPPY_ADMIN_DATABASE_URL<br/>schema owner: alembic, CLI"] -.->|"FORCE means<br/>not exempt"| Policy
    App["ALPPY_DATABASE_URL<br/>low-privilege runtime role"] --> Policy
```

**Coverage.** 26 school-scoped tables get `school_id = current_setting(...)`; 6
association tables get an `EXISTS` against their parent's own `school_id` — spelled
out rather than leaning on the parent's policy, so it works for a reason the reader
can see; `school` gets a two-armed policy (the current tenant **or** any school this
teacher is a member of) because login, `/auth/me` and `POST /auth/school/{id}` all
legitimately read across the boundary.

**Not covered, deliberately:** `competency` (shared reference data, no `school_id`),
`teacher` and `teacher_school` (identity, cross-tenant by definition). These three are
protected by application-level filtering only. See §8.4.

**Fail-closed, by construction.** The policies read
`nullif(current_setting('app.current_school_id', true), '')::uuid`, which is NULL when
nothing has been bound, and a comparison against NULL admits no rows. A handler that
takes `DbDep` without `TenantDep`/`ScopeDep` never gets the bind, and reads **nothing**
rather than everything. *A handler that finds an empty list where it expected rows has
forgotten `TenantDep`; it has not found a bug.*

**Two scopes, not one.** `Scope.school_id` is the *tenant* boundary (teaching material
is shared school-wide). `Scope.teacher_id` is the *ownership* boundary: a class is
personal, and `enrollment.owned_class_ids` resolves it as `head_teacher_id` **OR** a
`class_teacher_subject` row. Handlers that touch a class take `ScopeDep`; the rest
take `TenantDep`.

**The worker's exception.** `alppy_job_school(uuid)` is a `SECURITY DEFINER` function
with a pinned `search_path`, so a job can resolve its own tenant before it has one
(`worker/tasks.py:_bind_job_tenant`).

---

## 4 · Domain layer

### 4.1 Aggregates and their owning module

An "aggregate" here means: a cluster of tables that one module is allowed to write, so
that its invariants hold in one place.

| Aggregate root | Tables written | Owning module | Invariant it exists to hold |
|---|---|---|---|
| Class | `class`, `student`, `class_student`, `class_subject`, `class_teacher_subject` | `class_service` | A student shares the class's school **and** year; a branch is declared before it is assigned |
| Chapter/tree | `chapter`, `chapter_competency` | `chapter_service`, `tree_service` (read) | `unfiled` is excluded by NULL primary, never by key |
| Corpus | `source`, `source_section`, `source_chunk`, `exercise`, `exercise_competency` | `ingest/pipeline`, `sources` router | An exercise's chapter is an inference and never a filing |
| Sheet | `sheet`, `sheet_item`, `sheet_instance`, `sheet_source` | `sheet_service` | Items are replaced wholesale; `sheet_source[0] == derived_from_id` |
| Render | `answer_box_placement`, `sheet.*_pdf_key`, `sheet.rendered_at` | `sheets/render.py` | Boxes are **measured**, never recomputed |
| Scan | `scan`, `scan_page`, `detection` | `scan_processing`, `scan_service` | A page is registered against the layout it was *printed* with |
| Grading | `attempt`, `detection.verdict_*` | `scan_service.confirm_scan`, `scan/grading.py`, `open_answer_grading` | One attempt per (student, exercise, sheet); a blank is never penalised |
| Mastery | `mastery_snapshot`, `mastery_branch_snapshot` | `mastery_service` | Only `attempt.correct` is read; never pool attempts across competencies |
| Adaptive | `exercise` (generated), `misconception_note`, `adaptive_proposal` | `adaptive_service`, `feedback_service` | A model may revise a partition, never decide one; nothing prints unapproved |
| Agenda | `event` | `event_service.record` (8 call sites in app code) | Append-only; never PII in `summary` |
| AI audit | `model_call`, `prompt_log` | `ai/audit.py`, `ai/prompt_log.py` | `model_call` stays content-free; `prompt_log` is written only past the PII gate |

### 4.2 Module → table access matrix

Mechanically derived (a table name appearing in a module's source). Read it as
"which module could touch this", i.e. the blast radius of a schema change.

| Module | Tables referenced |
|---|---|
| `services/class_service` | school, teacher, school_year, subject, class, student, sheet, scan, teacher_school, class_subject, class_teacher_subject, class_student |
| `services/enrollment` | class, student, sheet, event, class_teacher_subject, class_student |
| `services/tree_service` | subject, class, competency, chapter, exercise, sheet, attempt, class_subject |
| `services/mastery_service` | class, student, competency, chapter, exercise, sheet, sheet_item, scan, scan_page, detection, attempt, mastery_snapshot, mastery_branch_snapshot, class_student, chapter_competency, exercise_competency |
| `services/sheet_service` | subject, student, chapter, exercise, sheet, sheet_item, sheet_instance, misconception_note, attempt, exercise_competency, sheet_source |
| `services/scan_processing` | student, sheet, sheet_item, sheet_instance, answer_box_placement, scan, scan_page, detection |
| `services/scan_service` | student, exercise, sheet, sheet_item, sheet_instance, scan, scan_page, detection, attempt, job |
| `services/open_answer_grading` | student, exercise, sheet, sheet_item, sheet_instance, answer_box_placement, scan, scan_page, detection, job |
| `services/adaptive_service` | student, competency, exercise, attempt, mastery_snapshot, job |
| `services/feedback_service` | student, exercise, misconception_note, detection, attempt |
| `services/results_service` | student, exercise, sheet, sheet_item, scan, scan_page, detection, attempt |
| `services/performance_summary` | sheet_instance, attempt, mastery_snapshot, exercise_competency |
| `services/retrieval` | competency, chapter, source, source_chunk, exercise, chapter_competency |
| `services/event_service`, `event_backfill` | event (+ source, source_section, sheet, scan, attempt for the backfill) |
| `services/approval` | teacher, exercise, misconception_note, attempt |
| `services/nouns_service` | every table carrying a renameable noun |

`mastery_service` is the widest reader in the codebase (16 tables) and the one with
the strictest rule about *which column* it may read.

### 4.3 The pure core

Three modules hold arithmetic and geometry with no database at all. They are the
reason the invariants are testable:

| Module | Inputs → outputs | Rule |
|---|---|---|
| `mastery/model.py` | `AttemptInput[]` → `MasteryResult` (`compute_mastery`), `MasteryResult[]` → `MasteryResult` (`roll_up_mastery`) | `roll_up_mastery` is the **only** aggregation above a competency. Attempts are bucketed per competency *first*; pooling raw attempts across competencies derives one recency from a mixture |
| `sheets/layout.py` | page geometry in millimetres | The single source of truth, mirrored into `print.css` and read by the detector. Changing a number is a **layout version bump** |
| `scan/grading.py` | detection + barème → score | The one place a penalty's sign is applied; a blank is never penalised, an ambiguous mark is never scored |

Four altitudes, one function:

```
Attempt[] ─▶ compute_mastery ─▶ a Competency's band (a leaf)
          ─▶ roll_up_mastery ─▶ a Sheet's band
                             ─▶ a Theme's band
                             ─▶ a Competence's band ─▶ a Branch's band
```

### 4.4 Invariants no DDL can express

These are the ones a reviewer has to enforce by reading. They are indexed as numbered
constraints in [`docs/design/constraints.md`](design/constraints.md) and per-feature
`§2 Invariants` tables; the schema-level ones are:

1. Mastery reads `attempt.correct`, never `attempt.score`.
2. Attempts are never pooled across competencies (across *students* is fine — that is
   `pool_by_competency`).
3. `unfiled` is excluded by `primary_competency_id IS NULL`, never by `key`.
4. A sheet is never auto-filed by inferring a Theme from its items.
5. No student name reaches a model provider — prompts carry `student.uid`;
   `ai/scrub.py` *raises* rather than redacting.
6. An AI-generated exercise or note is never printed without `approved_at`.
7. A crop never leaves the statement region (`ITEMS_TOP_MM..ITEMS_BOTTOM_MM`).
8. An answer box is cropped where it *printed* (`answer_box_placement`), never where
   it would print now.
9. A failure crosses to the client as a **code** (`job.error`), never `str(exc)`;
   `source.error` is the one field holding prose, written for a teacher.
10. `model_call` stays content-free.

---

## 5 · Contract layer (HTTP DTOs)

≈110 Pydantic models in `alppy/schemas/__init__.py`, served by 12 routers under
`/api/v1`. **The DTO graph is not the table graph**, and the places it deviates are
all deliberate.

```mermaid
erDiagram
    ClassTreeOut ||--o{ TreeBranchOut : branches
    TreeBranchOut ||--o{ TreeCompetenceOut : competences
    TreeCompetenceOut ||--o{ TreeThemeOut : themes
    TreeBranchOut ||--|| TreeMasteryOut : mastery
    TreeCompetenceOut ||--|| TreeMasteryOut : mastery
    TreeThemeOut ||--|| TreeMasteryOut : mastery

    SheetOut ||--o{ SheetItemOut : items
    SheetOut ||--o{ SheetInstanceOut : instances
    SheetOut ||--o{ SheetScanOut : "scans (NOT ScanOut)"

    ScanOut ||--o{ ScanPageOut : pages
    ScanPageOut ||--o{ DetectionOut : detections

    StudentProfileOut ||--|| StudentOut : student
    StudentProfileOut ||--o{ CompetencyMastery : "strengths / gaps / all"
    StudentProfileOut ||--o{ SheetTaken : sheets

    HomeOut ||--|| TeacherOut : teacher
    HomeOut ||--o{ ClassSummary : classes
    HomeOut ||--o{ SubjectOut : subjects
```

**Where the contract deviates from the schema, and why**

| DTO | Deviation | Reason |
|---|---|---|
| `ClassTreeOut` | A four-level nesting that exists in no table | The tree is *derived* from `class_subject` + `chapter.primary_competency_id` + `competency.parent_id`, walked in `tree_service` |
| `TreeMasteryOut` | Used unchanged at Theme, Competence, Branch **and Sheet** level | A rolled-up band is the same kind of object at every altitude, so it needs no second colour set, no second label set, no second reading of DC-colour-08. It carries `assessed_count` / `child_count`, because a band without its coverage is a dishonest claim (DC-content-07) |
| `SheetOut.competency_ids`, `.chapter_ids` | Derived per request from `SheetItem → Exercise`, never stored | A stored set is rewritten on every item edit, and between the edit and the rewrite it describes a sheet that no longer exists |
| `SheetOut.scans` uses `SheetScanOut`, not `ScanOut` | A projection, deliberately | `ScanOut` carries every page and every detection; a sheet with four piles would ship four page lists nobody asked for |
| `SheetOut.*_pdf_url` | A *URL*, where the table holds a *key* | Presigned and short-lived in production (900 s); the key never leaves the server |
| `ScanOut.revised` | Derived from `(status, confirmation_count)` | A fourth `ScanStatus` member would turn every `is CONFIRMED` check into a two-member test, and each one missed is a silently unlocked pile |
| `MasteryMatrixOut`, `StudentProfileOut` | Recomputed on read, never a snapshot table read | The score decays; a matrix opened on Friday must not show Monday's numbers |
| `StudentPointsOut.points_earned` | `float \| None`, not `0.0` | Nothing graded is **not** zero, and must never render as one |
| `AdaptiveProposeResponse` | Backed by `adaptive_proposal.payload`, keyed by job | ~1 MB, read once; putting it in `job.result` would re-serialise it on every 900 ms poll |
| every error | A **code**, never a message | `job.error` ∈ `services/job_failure.FAILURE_CODES`; the client owns the sentence (`apiErrorMessage`) |

---

## 6 · UI layer

### 6.1 The navigation object model

What the teacher sees is not what the tables are called. This mapping is the single
most common source of confusion in the codebase:

| In the UI | In the schema | Derived how |
|---|---|---|
| **Branch** | `subject` | `class_subject`, ordered by `position` |
| **Competence** | `competency` | `chapter.primary_competency.parent_id` (or itself, if already top-level) |
| **Theme** | `chapter` | `chapter.primary_competency_id IS NOT NULL` |
| **Sans thème / unfiled** | `chapter.key = 'unfiled'` | excluded from the tree by NULL primary; surfaced as a *counted row* |
| **Corrected sheet** | *no table* | a confirmed `scan` + the `attempt` rows it wrote |
| **Adaptive sheet** | *no table* | a `sheet` with `target ∈ {student, group}` |
| **Group** | *no table* | `sheet_instance.group_label`, a printable string recomputed per run |

```mermaid
flowchart LR
    Class -->|class_subject| Branch
    Branch -->|"chapter.primary_competency.parent"| Competence
    Competence -->|"chapter"| Theme
    Theme -->|"sheet.chapter_id"| Sheet
    Sheet -->|"sheet_instance"| Copy["one printed copy per student"]
    Copy -->|"scan_page.detected_uid"| Page["one scanned page"]
    Page --> Detection --> Attempt --> Band["a band, recomputed"]
```

### 6.2 Route → hook → data

24 route pages, 75 query/mutation hooks, one `apiRequest` client. Every screen ships
empty, loading (with a `shape`) and error states; errors render through
`apiErrorMessage(err, t)`, never `error.message`.

| Route | Hooks | Underlying tables |
|---|---|---|
| `/` | `useHome` | class, student, sheet, scan, mastery_snapshot |
| `/classes`, `/classes/new` | `useClasses`, `useCreateClass`, `useAddStudents` | class, student, class_student, school_year |
| `/classes/[id]` | `useClass`, `useClassMastery`, `useCurriculumTree`, `useStudents` | the tree walk + attempt |
| `/classes/[id]/roster`, `/students` | `useAddStudents`, `useClassMastery` | student, class_student |
| `/classes/[id]/students/[sid]` | `useStudentMastery`, `useCurriculumTree` | attempt, mastery_snapshot (history only) |
| `/classes/[id]/students/[sid]/sheets/[sheetId]` | `useStudentSheet` | detection, attempt, sheet_item, exercise |
| `/classes/[id]/teaching` | `useAssignBranch`, `useDeclareBranch`, `useReorderBranches`, `useClassTeachers`, `useColleagues` | class_subject, class_teacher_subject, teacher_school |
| `/classes/[id]/themes/[chapterId]` | `useCurriculumTree`, `useSheets` | chapter, sheet |
| `/classes/[id]/competences/[competencyId]` | `useClassMastery`, `useCurriculumTree` | competency, chapter_competency, attempt |
| `/sources` | `useSources`, `useUploadSource`, `useSourceExercises` | source, source_section, source_chunk, exercise |
| `/sheets`, `/sheets/new` | `useCreateSheet`, `useSourceSections`, `useChapters`, `useCurriculumTree` | sheet, sheet_item, exercise, chapter |
| `/sheets/[id]` | `useSheet`, `useRenderSheet`, `useMarkPrinted`, `useSheetMastery`, `useJob` | sheet, sheet_instance, answer_box_placement, job, event |
| `/scans/new`, `/scans` | `useUploadScan`, `useScans` | scan, scan_page, job |
| `/scans/[id]` | `useScan`, `useCorrectDetection`, `useAssignScanPage`, `useDiscardScanPage`, `useConfirmScan`, `useReopenScan` | scan, scan_page, detection, attempt, mastery_snapshot |
| `/results` | `useClassPoints`, `useStudents` | attempt, sheet, sheet_item (barème) |
| `/adaptive` | `useProposeAdaptive`, `useApproveAdaptive`, `useBatchAdaptive`, `useGenerateFeedback`, `useApproveFeedback`, … | adaptive_proposal, exercise, misconception_note, sheet, job |
| `/timeline` | `useTimeline` | event |
| `/settings`, `/settings/branches/[id]` | `useUpdatePreferences`, `useChapters`, `useUpdateChapter`, `useUpdateSource` | teacher (4 display switches), subject, chapter, source |
| `/login` | `useLogin` | teacher, teacher_school |

### 6.3 Domain components (`packages/ui/src/components/domain`)

The objects the schema exposes have exactly one rendering each, and the rules that
cannot be linted live in them:

| Component | Renders | Rule it carries |
|---|---|---|
| `MasteryBandTag` | `MasteryBand` + label | `label` is a **required** prop, so a caller cannot produce a bare coloured pill (DC-colour-08 / DC-content-07) |
| `MasteryCell`, `MasteryMatrix`, `Matrix` | `MasteryCell[]` | colour **and** label **and** tint density; a distinct underline in print |
| `MasteryCurve`, `BandHistogram` | `mastery_snapshot` history | the only consumers of a snapshot table |
| `MasteryMeter`, `ProgressRing` | a rolled-up band with coverage | coverage shown when incomplete, never when complete |
| `AiBadge` | `exercise.origin = ai_generated` | the **only** component allowed the mandarin accent (DC-colour-06) |
| `ProvenancePanel` | `source`, `source_page`, `label` | what makes a textbook item auditable against the book on the desk |
| `ScanReviewOverlay`, `ConfidenceBar` | `detection.fill_ratios`, `.bubble_boxes` | why the two JSONB columns exist |
| `AttemptList`, `PointsCell`, `PointsMatrix` | `attempt.score` | the barème side — never fed into a band |
| `OpenAnswerCard` (web) | `detection.crop_key`, `.transcription`, `.verdict_correct` | a verdict, never a heuristic |

---

## 7 · Lifecycles

```mermaid
stateDiagram-v2
    direction LR
    [*] --> uploaded : POST /scans
    uploaded --> processing : PROCESS_SCAN job
    processing --> failed : decode / registration error
    processing --> needs_review : detections written
    needs_review --> confirmed : confirm (writes Attempts, recomputes mastery)
    confirmed --> needs_review : reopen (supersedes, never deletes)
    note right of confirmed
        The label the teacher reads is DERIVED, not stored:
        needs_review + count 0  -> pending
        confirmed    + count 1  -> validated
        confirmed    + count >1 -> revised
        needs_review + count >0 -> reopened
    end note
```

| Object | States | Where |
|---|---|---|
| `Job` | `queued → running → succeeded \| failed` | `worker/tasks._run_job`. Failures are **recorded, not raised**, so arq never retries; `job.error` is a code from `FAILURE_CODES` |
| `Source` | `queued → running → succeeded \| failed`, plus `notice` on a *narrower-than-it-looks* success | `ingest/pipeline` |
| `SourceSection` | indexed → `extracted_at` set on first open | extraction is on demand: a book nobody teaches from costs nothing |
| `Exercise` | proposed → `approved_at` (printable) \| `discarded_at` (kept, never re-proposed) | `services/approval` |
| `MisconceptionNote` | generated → `approved_at` \| `discarded_at` | same module, same gate |
| `Sheet` | created → `rendered_at` (+ PDFs + `answer_box_placement`) → printed (an `Event`) → scanned | `sheets/render.py` |
| `Detection` | `detected \| low_confidence \| blank \| multiple \| not_gradeable \| pending` → `corrected` | `pending` is a cropped written answer awaiting the vision grader; a missing verdict is **skipped**, never a zero |

Job chaining: `PROCESS_SCAN` enqueues `GRADE_OPEN_ANSWERS` on completion
(`worker/tasks._chain_after`), so the review screen opens as soon as the marks are
read and the grades arrive while the teacher is already looking.

---

## 8 · Audit findings

Ordered by consequence. Each was verified by reading the named file at the stated
line; none was reproduced by running the system.

### 8.1 The API contract is mirrored by hand, and nothing checks it — **highest risk**

`apps/web/src/lib/api/types.ts` (1 162 lines, 116 exports) says in its own header that
it is "hand-mirrored from `apps/api/alppy/schemas/__init__.py`". Meanwhile
[`architecture.md` §1](architecture.md) states the client is "generated from the API's
served OpenAPI schema — never hand-written against assumptions", and
`packages/shared` contains only the generated *print layout* constants. There is no
OpenAPI generation step anywhere in `scripts/`, `package.json` or `turbo.json`.

So: a renamed or retyped Pydantic field compiles on both sides and fails at runtime,
in the browser, with no test in between. This is the one boundary in the repo whose
contract is claimed to be machine-checked and is not.

*Options:* generate the client (the honest reading of architecture.md), or add a CI
check that diffs the served OpenAPI document against `types.ts`, or amend
architecture.md to describe what actually ships. The first is the only one that
removes the class of bug.

### 8.2 `exercise_variant` is a table nothing writes

Declared at `models/__init__.py:686`, migrated, RLS-protected, and constructed in
**zero** places — application code, seed and tests alike. Its only reader is
`sheets/render.py:550`, reached when `sheet_instance.item_plan[].variant_id` is
non-null; both writers of `item_plan` (`sheet_service.py:208` and `:518`) hard-code
`"variant_id": None`. The per-student variant feature (F4) is designed but not built.

Harmless today, but it is schema that reads as live. Either annotate it as reserved for
F4 in the model docstring, or drop it and re-add it with the feature.

### 8.3 One storage namespace does not match the tenant check

`storage.storage_key()` builds `<kind>/<school_id>/<entity_id>/<leaf>`, and the local
file route enforces tenancy by comparing exactly that second segment
(`api/v1/health.py:83`: `parts[1] != str(school_id)` → 404). But rendered sheets use a
different builder (`sheets/render.py:296`) producing
`sheets/<sheet_id>/<layout_version>/<name>` — no school segment.

Consequence: under the **local** storage backend (CI, and a bare `pnpm dev` checkout
with `ALPPY_STORAGE_BACKEND=local`), a sheet PDF URL handed to the browser
(`/api/v1/files/sheets/…`) fails the segment check and 404s. Production is unaffected —
the S3 backend returns presigned URLs and never uses that route. The failure is
fail-closed, which is the right direction, but it is an inconsistency between two key
builders that a reader would not expect.

### 8.4 The RLS coverage check cannot see association tables

`scripts/check-rls.py:100` enumerates `Base.__subclasses__()` filtered by
`SchoolScopedMixin`. The seven association tables are bare `Table()` objects, not
mapped classes, so they are outside that loop: six of them got policies because
migration `0024` lists them explicitly in `LINKED_TABLES`, and a *new* association
table would ship with no policy while CI stayed green.

Related, and deliberate but nowhere enumerated: `teacher`, `teacher_school` and
`competency` have no RLS at all. For `competency` that is correct (shared reference
data). For `teacher` and `teacher_school` it is defensible — identity is cross-tenant
by definition, and `school`'s own policy reads `teacher_school` — but it means the
table holding every email and password hash is protected by application filtering
alone. Worth stating as an explicit exemption list in `0024`'s docstring and asserting
in `check-rls.py`, so it is a decision rather than an absence.

### 8.5 Three nullable FKs are typed as non-optional

```
models/__init__.py:487   source.uploaded_by_id: Mapped[uuid.UUID] = _fk(..., ondelete="SET NULL", nullable=True)
models/__init__.py:762   sheet.created_by_id:   Mapped[uuid.UUID] = _fk(..., ondelete="SET NULL", nullable=True)
models/__init__.py:1074  scan.uploaded_by_id:   Mapped[uuid.UUID] = _fk(..., ondelete="SET NULL", nullable=True)
```

The DDL is right (a record must outlive the account). The annotation says
`uuid.UUID`, so after a teacher is deleted these attributes are `None` while mypy
strict believes they cannot be — the one place in the schema where the type system is
actively wrong rather than merely silent. `Mapped[uuid.UUID | None]` is the fix and
costs nothing.

### 8.6 `__all__` omits `SourceSection`

Every other mapped class is listed at `models/__init__.py:1435`. No import breaks today
(`from alppy.models import SourceSection` resolves regardless), but a star-import would
miss it, and the omission reads as "not really a table".

### 8.7 `scan_page` has no uniqueness on `(scan_id, page_index)`

Re-running `PROCESS_SCAN` for a scan would append a second set of pages rather than
replace the first. This is safe today for two reasons that are both accidents of other
decisions: the job is enqueued once per upload, and `worker/tasks._run_job` records
failures instead of raising, so arq's retry never fires. The one re-read path in use,
`scan_processing.redetect_page:631`, does delete its stale detections first. A unique
constraint would make the safety a property of the schema rather than of the worker.

---

## 9 · Verifying this document

Everything above is derived from the code and can be re-derived:

```bash
# The tables, exactly as the models declare them
grep -n "^class \|^[a-z_]* = Table(" apps/api/alppy/models/__init__.py

# The migrations reproduce the models (needs a DISPOSABLE Postgres: drops public)
ALPPY_DATABASE_URL=postgresql+psycopg://... python scripts/check-schema-drift.py

# Row-level security is enabled, FORCED, has a policy, and actually isolates
ALPPY_DATABASE_URL=postgresql+psycopg://OWNER:...@host/db python scripts/check-rls.py

# The wire contract, as served
pnpm dev && curl -s localhost:8000/api/v1/openapi.json | jq '.components.schemas | keys'

# The print geometry the web app and the detector share
python scripts/export-layout.py --check
```

**When you change the schema:** model first, hand-written migration second
(the docstring explains *why*; the ops already say *what*), `check-schema-drift.py`
third, then the feature's `§2 Invariants` table and
[`decisions-log.md`](decisions-log.md). Then update §2 and §8 of this file.

---

## See also

- [`data-model.md`](data-model.md) — why each shape is what it is; read it first
- [`architecture.md`](architecture.md) — stack, request/job lifecycle, data flows
- [`mastery-model.md`](mastery-model.md) — the decay model and the roll-up rules
- [`curriculum.md`](curriculum.md) — LP21/PER coexistence, per-school primaries
- [`privacy.md`](privacy.md) — what may leave the database, and toward whom
- [`design/constraints.md`](design/constraints.md) — the numbered `DC-*` rules
