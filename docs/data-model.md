# The data model

**Status:** describes `main` as of 2026-09-10 · **Authority:** `apps/api/alppy/models/__init__.py`

Every table in Alppy, what it means, and — the part that is easy to get wrong —
**which of two similar-looking facts each column carries.** Five times in this
schema a row both *sits* somewhere and *belongs to* several things, and each
time the two are a column and a join table. Confusing them is how a chapter's
evidence leaks into a curriculum branch it never belonged to, how a child's
answers get thrown away as another class's paper, or how a co-teacher is locked
out of the class they teach.

For the diagrams — every table, every foreign key, every cardinality and delete rule,
followed up through the domain, contract and UI layers — see
[`er-model.md`](er-model.md).

For the rules a reviewer has to enforce by reading, see the `§2 Invariants`
table of each [`docs/features/`](features/) folder. For *why* a shape is what it
is, see [`decisions-log.md`](decisions-log.md).

---

## 1 · The shape, in one picture

```
School ──< Teacher        home_school_id              WHERE AN ACCOUNT IS BASED: the
                                                      school `login` mints its first
                                                      cookie for. One, NOT NULL   (D74)
School ──>< Teacher       teacher_school              WHERE THEY MAY WORK: every
                                                      staffroom. The TENANT of a
                                                      request comes from the SESSION,
                                                      checked against this        (D74)
       ──< SchoolYear ──< Class ──< Student
       ──< Subject                                    "Branch" in the UI

Class  ──< Student        home_class_id               WHERE A PUPIL SITS: the class
                                                      that MINTED uid ("7B_15") and
                                                      number. One, NOT NULL, RESTRICT
Class ──>< Student        class_student               WHO SITS WHERE: every class a
                                                      pupil attends. A roster, a
                                                      matrix, a tree and a printed
                                                      pile all mean THIS set   (D69)
Class ──>< Subject        class_subject               the Branches a class DECLARES
                                                      it studies, ordered      (D57)
Class ──> Teacher         head_teacher_id             WHO THE CLASS BELONGS TO: the
                                                      maître de classe. One, NOT NULL,
                                                      RESTRICT                 (D73)
Class ──>< Teacher×Subject class_teacher_subject      WHO TEACHES WHAT HERE. Ownership
                                                      is head teacher OR any row here
                                                      (`owned_class_ids`)      (D73)

Curriculum (LP21 | PER) ──< Competency                hierarchical, shared, not
                                                      school-scoped            (D11)

Chapter ──> Competency    primary_competency_id       WHERE A THEME SITS in the tree.
                                                      NULL only on `unfiled`   (D56)
Chapter ──>< Competency   chapter_competency          WHAT IT CREDITS — both curricula
                                                      at once                  (D56)

Source ──< SourceChunk (text + embedding) ──< SourceSection (the book's own chapters)
Exercise ──>< Competency  exercise_competency         what mastery reads through
Exercise ──> Chapter      chapter_id (nullable)       an INFERENCE, never a filing

Sheet  ──> Class, Subject
       ──> Chapter        chapter_id     NOT NULL     the ONE home Theme the teacher
                                                      STATED. `unfiled` when they did
                                                      not choose               (D60)
       ──> Sheet          derived_from_id             WHERE THE LINEAGE HANGS: the
                                                      principal source         (D70)
       ──>< Sheet         sheet_source                WHAT IT ANSWERS: every sheet
                                                      whose results justified it (D70)
       ──< SheetItem ──> Exercise                     the printed list, in order
       ──< SheetInstance ──> Student                  ONE PRINTED COPY, with its own
                                                      item_plan and group_label
       ──< AnswerBoxPlacement                         where each box ACTUALLY printed

Scan ──> Sheet ──< ScanPage ──< Detection ──> SheetItem, Exercise
Attempt ──> Student, Exercise, Sheet, SheetInstance, Detection, Scan
MasterySnapshot ──> Student, Competency                one row per (student, comp, DAY)
MasteryBranchSnapshot ──> Student, Subject             one row per (student, BRANCH, day).
                                                       A CACHE for the curve: no read path
                                                       answers a band from it        (D78)
```

---

## 2 · The six "sits vs belongs" splits

This is the shape the schema repeats, and the single most important thing to
understand before changing it. Each time: **a column answers "which one", a join
table answers "which ones", and they are different questions.**

| Row | Sits (column) | Belongs to (join table) | What breaks if you conflate them |
|---|---|---|---|
| `Chapter` | `primary_competency_id` — one node, resolved per school from `School.default_curriculum` | `chapter_competency` — every code it credits, across curricula | Rolling mastery up through the m2m leaks a chapter's evidence into a Branch its primary never belongs to (D56) |
| `Student` | `home_class_id` — the class that minted `uid` and `number` | `class_student` — every class they attend | Reading the column where enrollment is meant flags a co-enrolled pupil's paper as foreign, and `scan_processing` then **discards every detection on it**, silently (D69) |
| `Sheet` | `derived_from_id` — the principal source, printed on the feedback page | `sheet_source` — the whole evidence set | A sheet whose feedback page names one parent while its lineage draws another (D70) |
| `Class` | `head_teacher_id` — the maître de classe, who pastes the roster and mints the UIDs | `class_teacher_subject` — every teacher×branch taught here | Deriving the Branch nav from staffing makes a branch vanish the moment its teacher is unassigned, and makes its order depend on who is looking (D73) |
| `Teacher` | `home_school_id` — where the account is based, and what `login` mints a cookie for | `teacher_school` — every staffroom they work in | Reading the column where the tenant is meant makes a teacher who switched school go on reading the old one (D74) |
| `Student` | `person_id` — the durable identity, one per pupil per school | — (the *year* is the column here: one `student` row per person per school year) | Hanging evidence off the year-bound row resets a pupil's record every August, in the model whose whole purpose is decay; a repeating pupil is a stranger to the system (D87) |

**Why not the join table alone?** Because something always needs exactly one
answer: the navigation tree needs one parent per Theme, the UID needs one class,
the feedback page needs one source, a class needs one maître de classe, and
`login` needs one school to mint a cookie for. "The row with position 0" is a worse way to
ask for that than a foreign key — it demotes a constraint to a convention.

---

## 3 · Where the same word means two things

| Word | In the UI | In the schema |
|---|---|---|
| Branch | the subject a class studies | `Subject` |
| Theme | the teacher's grouping | `Chapter` |
| Competence | a curriculum node | `Competency` (the *parent* of a Chapter's primary) |
| Corrected sheet | the copies you marked | **no table** — a confirmed `Scan` plus the `Attempt`s it wrote |
| Adaptive sheet | the differentiated batch | **no table** — a `Sheet` with `target ∈ {student, group}` |

The last two are deliberate. A `CorrectedSheet` entity would duplicate what
`Scan.confirmed_at` and `Attempt` already say; an `AdaptiveSheet` table would
fork every code path that prints, scans or grades a sheet, so that half of them
would eventually only handle one kind.

---

## 4 · Two quantities that must never merge

**A mark is not a band.** `Attempt.score` carries the teacher's barème — it may
be negative, or larger than one. `Attempt.correct` is the boolean the mastery
model reads, and `mastery_service` selects only that column. A marking scheme
must not be able to rewrite what the model believes a child knows
(`I-mastery-08`).

**Mastery is computed, not stored.** `MasterySnapshot` exists for the history
curve and for adaptive targeting, but every read path recomputes from
`Attempt`s: the score decays with time, so a matrix opened on Friday must not
show Monday's numbers.

Four altitudes, one function:

```
Attempt[]  ─▶ compute_mastery      ─▶ a Competency's band      (a leaf)
           ─▶ roll_up_mastery      ─▶ a Sheet's band           (D72)
                                   ─▶ a Theme's band
                                   ─▶ a Competence's, a Branch's
```

Attempts are bucketed **per competency first**, and only the results combined.
Pooling raw attempts across competencies derives one recency from a mixture, so
a competency practised last week launders the staleness of one last touched in
June — in the model whose whole purpose is fading (`I-mastery-10`). Pooling
across *students* is fine and is what `pool_by_competency` does.

---

## 5 · What is derived, and why nothing stores it

| Question | Answered by | Why not a column |
|---|---|---|
| What does this sheet cover? | `SheetItem → Exercise → exercise_competency` | A stored set is rewritten on every item edit, and between the edit and the rewrite it describes a sheet that no longer exists (D71) |
| Which pupils are in this class? | `class_student` | — |
| How did the class do on this sheet? | `roll_up_mastery` over the sheet's competencies | It decays; see §4 |
| What was this child's Branch band in June? | `mastery_branch_snapshot` | The only question recomputation cannot answer — the score decays, so yesterday's number is not derivable from today's attempts (D78) |
| Is this pile corrected? | `Scan.confirmed_at` / `confirmation_count` | A fourth `ScanStatus` member would turn every `is CONFIRMED` check into a two-member test, and each one missed is a silently unlocked pile (D48) |

---

## 6 · Delete behaviour

Most foreign keys are `ON DELETE CASCADE`. The exceptions are the ones that
protect evidence, and each is deliberate:

| Column | Action | Because |
|---|---|---|
| `Student.home_class_id` | **RESTRICT** | Deleting a class used to delete its students, and `Attempt`, `MasterySnapshot` and `SheetInstance` all cascade from there — a term of evidence gone for a child who also sat in another class (D69) |
| `Class.head_teacher_id` | RESTRICT | A class must not evaporate with an account |
| `class_teacher_subject.teacher_id` | **RESTRICT** | Ownership is assignment-based, so cascading would strip a class of its last owner — a roster of named children nobody can open, with no error anywhere (D73) |
| `class_teacher_subject` → `class_subject` | CASCADE | An assignment must not outlive the declaration it hangs from; the composite FK is what makes `class_subject` provably the superset (D73) |
| `teacher_school` (both ends) | CASCADE | The row is only the *fact* of a membership |
| `Sheet.chapter_id`, `SheetItem.exercise_id`, `Attempt.exercise_id` | RESTRICT | Printed sheets, scans and attempts must survive a chapter or exercise being deleted |
| `class_student` (both ends) | CASCADE | The row is only the *fact* of an enrollment; removing it removes nothing else |
| `Student.person_id` | CASCADE | A person's every year of enrolment goes with them — which is what keeps erasure possible once the evidence moved off the year-bound row (D87) |
| `Attempt`, `MasterySnapshot`, `MasteryBranchSnapshot`, `MisconceptionNote` → `Person` | CASCADE | Since 0028 these hang off the person, not the year |

**Unenrolling is not deleting, and since 0027 it is not a delete either.** It
stamps `valid_to` on one `class_student` row: the pupil, their UID, their
attempts and their snapshots all survive, and so does the *fact that they were
in that class*, which a deleted row could not express. They stop appearing in
that class's current roster, matrix and tree; a read that passes a past `on`
still finds them, and the teacher who marked their October sheets can still
open their profile in June. It is refused on the home class.

**Deleting a `Person` is the only operation allowed to destroy evidence.**
Deleting a `Student` no longer is — it cannot be, or a pupil's record would
vanish every August — so `nouns_service.delete_student` removes the student and
then the person, once no other year still refers to them (D87).

---

## 7 · The identifier the paper carries

`Student.uid` (`7B_15`) is the only student identifier that is ever printed or
sent to a model provider ([`privacy.md`](privacy.md)). It is minted once, from
the **home** class's code and the pupil's number, and unique per
`(school_id, school_year_id)`.

It does **not** move with enrollment. That is what lets a pupil join a second
class without orphaning every sheet already sitting in a pile on the desk, and
it is why `home_class_id` survived D69 rather than being replaced by the join
table (`I-platform-09`).

It does **not** survive the school year either, and that is the reason `person`
exists. A UID is a fact about one year's paper: the class code in it changes
when the pupil changes class, so it cannot be the thing a two-year mastery
record hangs from. The whole print and scan path therefore stays on the
year-bound `student` row — `sheet_instance`, `answer_box_placement.student_uid`,
`scan_page.student_id`, `exercise_variant.student_id` — while `attempt`,
`mastery_snapshot`, `mastery_branch_snapshot` and `misconception_note` hang off
`person` (D87).

---

## 7bis · How things are named

Unstated for a long time, which is the whole of audit finding L5: the
convention was consistent and nobody had written it down, so every migration
re-derived it by reading its neighbours.

`Base.metadata` carries it (`db/base.py`), and Alembic autogenerate uses it, so
a constraint created without an explicit name still gets the right one — but
every migration spells names out anyway, because a RENAME has to reproduce what
the convention *would* have produced or the drift gate reports a spurious
difference for ever.

| Kind | Pattern | Example |
|---|---|---|
| Index | `ix_%(column_0_label)s` | `ix_attempt_person_answered` |
| Unique | `uq_%(table_name)s_%(column_0_name)s` | `uq_student_uid` |
| Check | `ck_%(table_name)s_%(constraint_name)s` | `ck_school_year_label` |
| Foreign key | `fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s` | `fk_student_person_id_person` |
| Primary key | `pk_%(table_name)s` | `pk_attempt` |

Three habits sit on top of it, and none is enforceable by a convention:

- **A partial index says what it is partial on, not just what it covers.**
  `uq_class_student_open` is unique over `(class_id, student_id)` *where the
  membership is open*; the name carries the predicate because the columns
  cannot.
- **Tables are singular** (`scan_page`, `class_student`), and `class` needs
  quoting in every raw statement because it is a SQL keyword. This is why the
  RLS migration writes `ALTER TABLE "class"` rather than bare.
- **An association table is named for its two ends, in the order the composite
  primary key uses**: `class_student`, `chapter_competency`,
  `misconception_note_competency`.

---

## 8 · Changing the schema

1. Change the model in `apps/api/alppy/models/__init__.py`.
2. Write the migration by hand in `apps/api/alembic/versions/`. The docstring
   explains **why**, not what — the ops already say what.
3. Prove the migration reproduces the model, on a **disposable** Postgres:

```bash
ALPPY_DATABASE_URL=postgresql+psycopg://... python scripts/check-schema-drift.py
```

The unit tests build their schema with `create_all()` from the models, so they
structurally cannot catch drift. That is what this script is for.

4. If the change touches a rule a reviewer has to enforce by reading, it goes in
   the feature's `§2 Invariants` table **first**, then in that feature's
   `decisions.md` with a `D`-number, then in
   [`decisions-log.md`](decisions-log.md).
