# Phase 1 audit — Database design & setup

**Scope:** the data layer of Alppy as it stands on `main` at 2026-09-10, migration head
`0025_timestamp_defaults`.
**Method:** read-only. Every migration `0001`–`0025` read in order; `apps/api/alppy/models/__init__.py`
(1483 lines) read in full; the live development Postgres (`alppy-postgres-1`, pgvector/pg16)
introspected read-only. No schema was created, altered or dropped, and
`scripts/check-schema-drift.py` / `scripts/check-rls.py` were **not** run because both drop the
`public` schema and the only Postgres available holds real development data — a read-only
equivalent was used instead (§Evidence).
**PER alignment** was checked against the CIIP's own published print PDFs, not from memory
(`PER_print_MSN_31.pdf`, `PER_print_MSN_34.pdf`, `bdper.plandetudes.ch`, © CIIP 2010).

Two parameters in the audit brief were left as placeholders and are treated as open questions:
**cantonal scope** ("Vaud + Genève, or all Romandie") and **stack** — the latter is answered by the
repo: **PostgreSQL 16 + pgvector, SQLAlchemy 2.0 + Alembic**, not Prisma/Drizzle/TypeORM.

---

## 1 · Verdict

**Yes — build Phase 2 on it, but fix two things first, and neither is a schema-shape problem.**

This is an unusually well-built data layer. Tenancy is enforced twice (a required `school_id`
argument in every service *and* Postgres row-level security with `FORCE`, a fail-closed GUC, and a
separate low-privilege role); the machine's reading and the teacher's override are kept in separate
columns on `detection` so a correction never destroys what it replaced; `attempt.score` and
`attempt.correct` are deliberately different quantities; delete rules are argued case by case rather
than defaulted; and every non-obvious decision carries a written rationale that turns out, on
checking, to be accurate. The migration chain is linear, every migration is reversible, backfills
carry the date of the thing they describe rather than `now()`, and the three renames (`0019`, `0021`)
were done as renames precisely so that unreviewed read sites would fail loudly. I found no
cross-tenant read path, no cascade that destroys student work by accident, and no place where an
exception's text reaches a teacher's screen.

The two blocking problems are both about **time**, and both get more expensive every day the product
runs rather than at some future refactor:

1. **No membership is time-bounded.** `class_student`, `class_teacher_subject` and `teacher_school`
   each record a start (`enrolled_at`, `assigned_at`, `joined_at`) and no end, and leaving is
   implemented as `DELETE`. The decision is deliberate and documented — but in Cycle 3, where pupils
   are streamed into maths levels *across* homerooms and move between them mid-year, it means the
   composition of a teaching group is a snapshot that overwrites itself. Every unenrolment between
   now and the fix destroys a fact that cannot be recovered afterwards.
2. **A pupil's identity does not survive the summer.** `student.school_year_id` is `NOT NULL` and
   `uq_student_uid` is keyed on it, so 2026/27 needs a *new* `student` row with a new UUID; `attempt`
   and `mastery_snapshot` hang off `student.id`. For a product whose mastery model is explicitly
   about decay over months, the longitudinal record resets each August and a repeating pupil is a
   stranger to the system. There is no rollover path in the codebase at all.

Neither requires reshaping what exists — both are additive (a `person` identity above the year-bound
row; `valid_from`/`valid_to` on three join tables). Both are far cheaper now, with one school's demo
data, than after the first real August.

Everything else is a Medium or below: five unindexed FKs, seventeen redundant indexes, a missing
pgvector index, and a curriculum tree that is two levels deep where the PER is five. The curriculum
gap (§H1–H3) is not a *soundness* problem but it is the one that will limit what Phase 2's adaptive
engine can actually reason about, so it belongs in the same planning conversation.

---

## 2 · Findings

Ordered within each severity by cost-to-fix-later, descending.

| ID | Sev | Area | Summary | Evidence |
|---|---|---|---|---|
| C1 | Critical | Temporality | No membership relation is time-bounded; leaving a group is a `DELETE` | `models/__init__.py:245-265`, `services/class_service.py:430-448` |
| C2 | Critical | Identity | Pupil identity is year-bound; no person above `student`, no rollover path | `models/__init__.py:325-352`, `services/class_service.py:98-105` |
| H1 | High | PER | Curriculum tree is 2 levels; PER is 5. No per-year progression, no attentes fondamentales | `seed/data/competencies.json`, CIIP `PER_print_MSN_31.pdf` |
| H2 | High | PER / streaming | PER's own `Niv. 1/2/3` differentiation is unrepresentable; cantonal streaming has no home | CIIP PDF ll. 92–104; `models/__init__.py:267-291` |
| H3 | High | PER | No curriculum version, and no flag separating official CIIP codes from invented ones | `models/__init__.py:361-380`, `docs/curriculum.md` §5 |
| H4 | High | Migration hygiene | The drift gate is structurally blind to `server_default` drift — the class `0025` just fixed | `scripts/check-schema-drift.py:64` |
| H5 | High | nLPD / retention | No retention or erasure for scanned handwriting; `delete_student` orphans every image | `services/nouns_service.py:396`, `core/config.py:228` |
| H6 | High | Indexes | No vector index on `source_chunk.embedding`; every retrieval is a seq scan | live `pg_indexes`; `services/retrieval.py:661` |
| H7 | High | Audit | No read audit trail for student records; the write log covers 11 verbs only | `models/enums.py:130-165` |
| H8 | High | School year | No uniqueness on year label or `is_current`; Aug 1–Jul 31 hardcoded for every canton | `models/__init__.py:160-167`, `services/class_service.py:98-105` |
| M1 | Medium | Indexes | 5 FK columns unindexed, incl. both `competency_id` join directions | metadata scan (§Evidence) |
| M2 | Medium | Indexes | 17 redundant single-column indexes fully covered by a composite prefix | live `pg_indexes` |
| M3 | Medium | Normalization | `misconception_note.competency_ids` is a JSONB array of UUID strings, no FK | `models/__init__.py:1004` |
| M4 | Medium | Constraints | `uq_attempt_*` includes nullable `sheet_id`; the anti-double-count backstop has a NULL hole | `models/__init__.py:1222-1226` |
| M5 | Medium | Enums | 12 Postgres `ENUM` types; a routine change needs `ALTER TYPE` | `models/enums.py`, `0018` |
| M6 | Medium | Modelling | Booleans that should be timestamps; discarding a scan page records no actor or time | `models/__init__.py:1121-1136` |
| M7 | Medium | Keys | UUIDv4 PKs on the five high-insert tables; `uq_attempt_*` blocks time partitioning later | `db/base.py:26`, `models/__init__.py:62-64` |
| M8 | Medium | Swiss structure | No `établissement` vs `site`; canton is a nullable `String(2)` with no rules table | `models/__init__.py:75-90` |
| M9 | Medium | MER | `Source` cannot express edition, per-year volume, artefact type or cantonal adoption | `models/__init__.py:480-509` |
| M10 | Medium | Delete rules | Deleting a `subject` cascades to `chapter` while `sheet.chapter_id` is RESTRICT | ON DELETE inventory (§Evidence) |
| L1 | Low | Scan identity | No QR; identity is an OCR'd UID bubble grid — enumerable, no per-print-run id | `sheets/layout.py:208`, `scan/detector.py:571` |
| L2 | Low | Co-teaching | Multiple teachers per group supported; roles and substitutes are not | `models/__init__.py:197-244` |
| L3 | Low | Hygiene | `0025` is applied to the dev database but untracked in git | `git status`, live `alembic_version` |
| L4 | Low | Query shape | Leading-wildcard `ILIKE` on `event.summary` and three `exercise` columns | `services/event_service.py:138`, `api/v1/sources.py:367` |
| L5 | Low | Naming | Convention is consistent but unstated; `class` needs quoting everywhere | migrations passim |

---

## 3 · Detailed findings

### Critical

---

#### C1 · No membership relation is time-bounded

**What is wrong.** Three join tables carry a start and no end:

| Table | Start column | End column | Leaving is |
|---|---|---|---|
| `class_student` | `enrolled_at` | — | `DELETE` (`class_service.py:443-448`) |
| `class_teacher_subject` | `assigned_at` | — | `DELETE` (`unassign_branch`) |
| `teacher_school` | `joined_at` | — | `DELETE` |

The models say so explicitly and give the reason (`models/__init__.py:250-254`): *"Provenance, not a
state machine — there is deliberately no `left_at`: the moment one exists every roster read grows a
temporal predicate and every test needs an injectable clock."* That is a real cost and the reasoning
is honest. It is also, for this domain, the wrong trade.

**Why it matters here.** Take Léa, 10e année in Sion. Her homeroom is 10VG3; for maths she is in the
niveau-2 group, `Class` code `10-MAT-N2`, taught by M. Rossier. In October she sits three worksheets
in that group. In February her results improve and she moves to niveau 3.

The move is `DELETE FROM class_student WHERE class_id = <N2> AND student_id = <Léa>`. From that
moment:

- `mastery_service.class_matrix` builds its roster from `_student_ids_for_class`
  (`mastery_service.py:258-267`), which reads current enrolment. Léa vanishes from the niveau-2
  matrix — including from the columns showing October, which she sat.
- `mastery_service._owned_student` (`mastery_service.py:578-596`) gates a pupil's profile on a
  **current** enrolment in a class the caller owns. M. Rossier, who taught Léa for six months and
  marked those three sheets, now gets a 404 on her profile.
- Her three `attempt` rows still exist and are still correctly attributed — `attempt.student_id`,
  `attempt.sheet_id` and `sheet.class_id` all resolve — so the data is not lost. It is simply
  unreachable through every class-grained read path the product has.
- Nothing anywhere records that Léa was ever in niveau 2. In June, asked to justify her orientation
  decision to a parent, M. Rossier cannot reconstruct the group she was assessed in.

The same shape hits teachers: a `remplaçant` covering maternity leave from March to May is
`class_teacher_subject` rows added in March and deleted in May, after which the sheets they created
(`sheet.created_by_id`, SET NULL, survives) sit in a class they can no longer open, and no record
says they ever taught there.

**The fix.** Add `valid_from date NOT NULL` / `valid_to date NULL` to all three tables, make the
"current" predicate `valid_to IS NULL OR valid_to > :on`, and turn `unenroll`/`unassign_branch` into
an `UPDATE ... SET valid_to = :today`. The primary keys must widen to include `valid_from` so a pupil
can rejoin the same group later — that is the composite-uniqueness point in the brief (#27), and it
is why doing this *before* re-enrolment is a supported operation is much easier.

**Migration risk.** Now: near zero. The tables are small, every existing row backfills as
`valid_from = enrolled_at/assigned_at/joined_at, valid_to = NULL`, and the change is provably
behaviour-preserving for exactly the reason `0019` and `0021` were — after the backfill every row is
open, so the current-membership predicate selects precisely what the unqualified read selected. The
work is in the read paths (`enrollment.owned_class_ids`, `_student_ids_for_class`, `_owned_student`,
`class_service.list_students`), which is a bounded, greppable set.
After launch: the schema change is just as easy, but **every membership ended between now and then is
gone** — there is no column holding the fact and no log to reconstruct it from. This is the single
finding in this audit whose cost is a function of elapsed time rather than of code size.

---

#### C2 · A pupil's identity does not survive the school year

**What is wrong.** `Student` is a year-bound row, not a person:

```
student.school_year_id  uuid  NOT NULL          # models/__init__.py:348
uq_student_uid (school_id, school_year_id, uid) # models/__init__.py:334
```

`class_service.add_students` writes `school_year_id=school_class.school_year_id`
(`class_service.py:494`) and `enroll` refuses a pupil whose year differs from the class's
(`class_service.py:419`). So the 2026/27 roster is a new set of `student` rows with new UUIDs.
`attempt.student_id`, `mastery_snapshot.student_id`, `mastery_branch_snapshot.student_id`,
`misconception_note.student_id` and `sheet_instance.student_id` all point at the year-bound row.

There is no `person`, `pupil` or equivalent above it, no `previous_student_id`, and — checked
directly — **no school-year endpoint of any kind** (`grep -rn "SchoolYear" apps/api/alppy/api/v1/`
returns nothing) and no rollover command in `alppy.cli` (`_seed`, `_backfill_events`,
`_purge_prompt_logs` only). What happens in August 2027 is undefined by the code.

**Why it matters here.** Alppy's mastery model is explicitly a decay model — `docs/mastery-model.md`
and the `FADING` band exist because knowledge goes stale, and CLAUDE.md is emphatic that recency
must not be laundered across competencies. The one interval over which decay matters most is the
summer holiday. On the current schema, the September 2027 view of a 11e-année pupil is empty: their
two prior years of evidence belong to two other `student` rows that nothing joins to them.

Concretely: Noah repeats his 10e année. In 2026/27 he is `student` A with uid `10VG3_07`; in 2027/28
he is `student` B with uid `10VG2_11`. Alppy will propose him adaptive work as though he had never
seen the material he failed — which is the exact opposite of what an adaptive engine is for, and the
teacher has no way to tell the system otherwise.

**The fix.** Introduce a school-scoped `person` (or `pupil`) row holding the durable identity —
names, and nothing else — and demote `student` to what it already is: a year-bound *enrolment record*
carrying `uid`, `number`, `home_class_id`, `school_year_id` and a `person_id`. Point the longitudinal
tables (`attempt`, `mastery_snapshot`, `mastery_branch_snapshot`) at `person_id`; leave the printing
and scanning path (`sheet_instance`, `answer_box_placement`, `scan_page.detected_uid`) on the
year-bound row, because a UID is a fact about one year's paper and must not change meaning.

Note this is the same split the codebase has already performed twice and named — D56 for `Chapter`,
D69 for `Student` — *where a row sits is a column, what it belongs to is a join*. C2 is the third
instance of that pattern, applied to time rather than to hierarchy.

**Migration risk.** Now: one migration, mechanical. Every existing `student` gets a `person` row 1:1
(`INSERT INTO person SELECT gen_random_uuid(), school_id, first_name, last_name FROM student`), the
FK is added, backfilled and tightened, and the three longitudinal FKs are repointed — with exactly
one person per student, every existing query returns what it returned before. Same provable
behaviour-preservation as `0019`.
After the first rollover: you have two unlinked rows per repeating or continuing pupil and **no key
that joins them** — not the uid (it changes with the class), not the name (homonyms, spelling,
marriage of a name in a roster paste). Re-linking becomes a manual, per-school, per-pupil
reconciliation with a real error rate against children's records. Do this before August.

---

### High

---

#### H1 · The PER hierarchy is modelled two levels deep; the PER has five

**What is wrong.** `Competency` is a self-referencing tree (`parent_id`,
`models/__init__.py:378-380`) and the schema does not limit depth — `docs/curriculum.md` §1 says so.
But the seeded PER data is two levels and the second is invented:

```
$ python -c "…"   # over seed/data/competencies.json
total 34   Counter({'LP21': 18, 'PER': 16})
depth dist Counter({2: 22, 1: 12})
```

Verified against the CIIP's own print PDF (`PER_print_MSN_31.pdf`, © CIIP 2010, extracted with
`pdftotext -layout`), the real structure is:

| PER level | Example | In the schema? |
|---|---|---|
| Domaine | MSN | No — implied by the `MSN` prefix in the code string |
| Objectif d'apprentissage | `MSN 31 – Poser et résoudre des problèmes pour modéliser le plan et l'espace` | Yes, level 1 |
| **Composante** | `1 … en définissant des figures planes et des solides par certaines de leurs propriétés géométriques` (numbered 1–8) | **No** |
| **Progression des apprentissages**, per year | three columns: `9e année` / `10e année` / `11e année`, grouped by champ thématique (`Figures géométriques planes`, `Solides`, `Transformations géométriques`, `Repérage dans le plan et dans l'espace`) | **No** |
| **Attentes fondamentales** | `Au cours, mais au plus tard à la fin du cycle, l'élève… reconnaît, nomme, décrit et construit : droites parallèles, …` | **No** |

What occupies level 2 instead is a local invention — `MSN 31.1 Figures planes, transformations et
isométries`, `MSN 31.2 Théorème de Pythagore…`, `MSN 34.1 Aires et périmètres…`. To the repo's
credit, `docs/curriculum.md` §5 states this outright: *"the PER does not officially subdivide below
MSN 31–MSN 35 at cycle 3; that second level is our own grouping."*

**One of those inventions is also misfiled.** `MSN 31.2` is *Théorème de Pythagore et relations
métriques dans le triangle rectangle*, parented to `MSN 31` (Espace). In the official PER, Pythagore
is in **MSN 34** — *Mobiliser la mesure pour comparer des grandeurs*, composante 5 (*"… en mobilisant
quelques procédures de calcul de longueur (théorèmes de Thalès, de Pythagore,…)"*), appearing in the
**10e** and **11e année** progression columns (`PER_print_MSN_34.pdf`, ll. 114–116, 216–222, 267–269).
The seeded chapter `plane_geometry_pythagoras` therefore has `primary_competency_code.PER = "MSN
31.2"` (`seed/data/chapters.json`), and CLAUDE.md repeats the pairing as an example. Because
`primary_competency_id` is what `tree_service` rolls mastery up through, a pupil's Pythagoras
evidence is credited to the *Espace* branch instead of *Grandeurs et mesures* — the precise leak
CLAUDE.md's own rule about the primary vs. the m2m exists to prevent, arriving through the data
rather than through the join.

**Why it matters here.** The brief's own reason is right and worth making concrete. A 9e-année pupil
and an 11e-année pupil both carry attempts against `MSN 34.2`. The PER says volumes of a cone are
11e-année, `Niv. 2 | 3` content; the schema cannot say that, so the adaptive engine cannot tell
"has not learned this yet" from "has forgotten this", and will propose remediation for material the
9e class has not been taught. Prerequisite reasoning — the thing a flat model cannot do — needs the
progression rows, because in the PER the prerequisite relation *is* the year ordering within a champ
thématique.

**The fix.** Deepen the seed rather than the schema: the tree already supports arbitrary depth. Add
`Competency.kind` (`domaine` / `objectif` / `composante` / `progression` / `attente`) and
`Competency.year` (`9H`/`10H`/`11H`, nullable — only progression rows carry one), then seed the real
five levels from the CIIP PDFs, which extract cleanly with `pdftotext -layout`. Move Pythagore under
`MSN 34` and re-point `plane_geometry_pythagoras`.

**Migration risk.** Now: two nullable columns plus a re-seed. Because `chapter_competency` and
`exercise_competency` join on ids, re-parenting a competency does not orphan anything, and `chapter`
rows are per-school and regenerable.
After launch: `attempt` → `exercise_competency` → `competency` means every historic attempt is
credited through the tagging you are about to change. Re-parenting Pythagore after a term of real
marking silently rewrites what every affected pupil's *Espace* and *Grandeurs* bands say — including
bands already shown to parents. The fix is the same size; the blast radius is not.

---

#### H2 · The PER's own niveau differentiation is unrepresentable, and cantonal streaming has no home

**What is wrong.** Two related gaps, and the first is the one that is easy to miss.

*The PER itself is stratified.* Throughout the cycle-3 progression and the attentes fondamentales,
content is annotated by niveau — verified verbatim from the CIIP PDF:

```
– polygones réguliers Niv. 1s | 2 | 3                        (MSN 31, l. 92)
– médiane, centre de gravité Niv. 2 | 3                      (MSN 31, l. 99)
– cercle de Thalès Niv. 3                                    (MSN 31, l. 104)
… reconnaît et nomme Niv. 1 | 2 / reconnaît, nomme et décrit Niv. 3 : cube, …   (MSN 31, l. 265)
Utilisation du théorème de Pythagore Niv. 1 8                (MSN 34, l. 216)
```

So `MSN 34` does not mean one thing. For a niveau-1 pupil the fundamental expectation is to *use*
Pythagoras in the plane; for niveau 3 it extends to space. Alppy stores one `competency` row per
code, one `mastery_snapshot` per `(student, competency)`, and one band. A niveau-1 pupil who has met
every expectation the PER sets for them and a niveau-3 pupil who has met two thirds of theirs are
scored against the same target and rendered with the same green.

*Cantonal streaming is not modelled at all.* There is no entity, column or enum for VP/VG and niveaux
1/2 (Vaud), R1/R2/R3 (Genève), niveaux I/II (Valais), or their equivalents. The only place a level
can be recorded is `Class.code`, `String(10)`, free text (`models/__init__.py:291`) — which is how
`10VG3` gets in, as an opaque string nothing can branch on. To the question the brief actually asks —
*can a new canton be added without a schema change?* — the answer is: yes, because nothing about
cantonal structure is in the schema to begin with. That is not the same as being supported.

**Why it matters here.** Mme Berger teaches maths in a Vaud établissement, one niveau-1 group and one
niveau-3 group. Both are `Class` rows with a `code` she typed. She opens the class matrix for each.
The bands are computed by identical code against identical competency rows, so the niveau-1 group
reads as uniformly weaker — not because the pupils are behind their own curriculum, but because the
system is measuring both against an undifferentiated merge of three curricula. The one signal the
product exists to give her is systematically biased against the pupils who most need it read
correctly. And `MasteryBand` is a Postgres `ENUM` (M5), so this cannot be patched by adding a band.

**The fix.** Two pieces, and they are separable.
For the PER: a `niveau` column on the progression/attente rows added in H1 (nullable, multi-valued —
`Niv. 1s | 2 | 3` is a set), and a `niveau` on the teaching group, so the roll-up compares a pupil
against the expectations that apply to them.
For cantonal streaming: a lookup table — `stream(id, canton, code, label, position)` — seeded per
canton and referenced from the teaching group, rather than an enum. `School.canton` already exists to
key it. This is the brief's #5 test, and a lookup table passes it where a `DB ENUM` would not.

**Migration risk.** Now: additive, nullable, no backfill needed — an unset niveau means "the whole
objective", which is today's behaviour exactly. After launch: the columns are still additive, but
every band computed before the fix was computed against the wrong target, and mastery snapshots are
a *cache with history* (`mastery_branch_snapshot` exists to draw curves). Those historic points
cannot be recomputed correctly, so the curve keeps a visible discontinuity at the fix date.

---

#### H3 · No curriculum version, and nothing separates official codes from invented ones

**What is wrong.** `Competency` carries `curriculum` (`LP21` | `PER`), `code`, `subject_key`, `cycle`,
`labels`, `description` (`models/__init__.py:325-341`) — and no edition, no publication year, no
validity range, and no provenance flag. Two consequences:

1. **Version.** The PDFs the seed is built from are © CIIP **2010**. Curricula are revised. A
   worksheet authored in 2026 against `MSN 33.2` and a worksheet authored in 2031 against a revised
   `MSN 33.2` are indistinguishable in the database, and `uq_competency_code (curriculum, code)`
   guarantees there can only ever be one row for a code — so a revision must *overwrite* the row that
   historic attempts are credited through. This is the brief's #12, and the answer is: not supported,
   and actively prevented by the unique constraint.
2. **Provenance.** By `docs/curriculum.md` §5's own accounting, of the 16 PER rows the five objectives
   (`MSN 31`–`35`) are verified and **eleven of the sixteen are the repo's own inventions**, some
   ("Approximate") with reconstructed wording. They sit in the same table, same column, same format
   as verified CIIP text, with nothing in the *database* marking which is which — only prose in a
   markdown file. A teacher reading `MSN 31.2 — Théorème de Pythagore` in the UI is being shown what
   looks like an official CIIP reference for their canton's legally-mandated curriculum. It is not
   one, and (per H1) it is filed under the wrong objective.

**Why it matters here.** The PER is a legal reference; a Vaud teacher's *bulletin* comments and
orientation decisions cite it. Showing an invented code in official notation is a credibility
problem the first time a *conseil de direction* checks one against `plandetudes.ch` and does not find
it. And with no version column, the first CIIP revision forces a choice between rewriting history and
forking the table.

**The fix.** Add `Competency.edition` (e.g. `"CIIP-2010"`) and widen the unique constraint to
`(curriculum, edition, code)`; add `Competency.is_official boolean NOT NULL` (or better,
`source_ref text` — the URL the wording came from) and render invented nodes distinctly, or
renumber them out of CIIP notation entirely (`ALPPY 31.2` rather than `MSN 31.2`).

**Migration risk.** Now: two columns, a widened unique constraint, a re-seed; nothing points at a
competency except by id, so renumbering `code` is safe. After launch: widening a unique constraint on
a table that historic `attempt`s are credited through is still mechanical, but renumbering a code
that a teacher has read, cited in a report, or filed a chapter under is a user-visible change to
something they were told was official.

---

#### H4 · The drift gate cannot see the class of bug that migration 0025 exists to fix

**What is wrong.** `scripts/check-schema-drift.py` — the gate CLAUDE.md names as *"the thing to run
before believing a migration reproduces the models"* — configures the comparison as:

```python
context = MigrationContext.configure(conn, opts={"compare_type": True})   # :64
```

`compare_server_default` is absent, so it defaults to `False` and Alembic does not diff server
defaults at all.

Migration `0025_timestamp_defaults` (untracked, see L3) was written because `prompt_log`,
`adaptive_proposal` and `mastery_branch_snapshot` were created without the `server_default=func.now()`
that `TimestampMixin` declares, which made SQLAlchemy omit the column from the INSERT and produced a
`NotNullViolation` on the first row ever written — "every `PROPOSE_ADAPTIVE` job reached 'proposal
built' at 0.9 and then died there". Its own docstring says *"`scripts/check-schema-drift.py` against a
disposable Postgres is what catches this class."* It does not. It cannot. The bug shipped and was
found in production behaviour, not by the gate.

**Evidence.** Running the same `compare_metadata` call read-only against the live database with the
option enabled returns seven differences the CI gate reports as clean:

```
DIFFS: 7
('modify_default', None, 'event',              'summary',                …)
('modify_default', None, 'misconception_note', 'competency_ids',         …)
('modify_default', None, 'scan',               'confirmation_count',     …)
('modify_default', None, 'scan_page',          'wrong_class',            …)
('modify_default', None, 'scan_page',          'discarded',              …)
('modify_default', None, 'sheet',              'default_points_correct', …)
('modify_default', None, 'sheet',              'default_points_penalty', …)
```

All seven are the *opposite* direction to `0025`: the database has a `server_default` that the model
does not declare, left behind by migrations `0003`/`0006`/`0007`/`0014` which used one to backfill a
new `NOT NULL` column and never dropped it. Those seven are individually harmless — the models supply
a Python-side `default=` so the value is always sent — but they are the noise that hides the next
`0025`, which is precisely the argument migration `0008` makes for having the gate at all.

**Why it matters here.** The whole justification for `check-schema-drift.py` is that the unit tests
build their schema with `create_all()` from the models and *"structurally cannot catch this"*. That
argument is correct and the gate is the compensating control. A compensating control with a hole in
the exact shape of the last production bug is worse than none, because it is trusted.

**The fix.** `opts={"compare_type": True, "compare_server_default": True}`, then clear the seven —
either by declaring the defaults on the models (they are genuinely there) or by dropping them in a
new migration. Declaring them on the models is the smaller change and the more honest one: the
database really does have those defaults.

**Migration risk.** Now: a one-line change to a script plus a model-side declaration; no DDL needed if
you declare rather than drop. After launch: identical — this one does not get more expensive, it just
keeps not catching things. It is High because of what it is *guarding*, not because of its own cost.

---

#### H5 · No retention or erasure path for scanned handwriting

**What is wrong.** The only retention mechanism in the system is for prompt text:
`ai_prompt_log_retention_days: int = 30` (`core/config.py:228`) swept by
`python -m alppy.cli purge-prompt-logs`. There is nothing equivalent for:

- `scan_page.image_key` — the photograph of a page of a child's answer sheet.
- `detection.crop_key` — the cut-out of one written answer, "Alppy's own ink removed".
- `exercise.figure_key`, `sheet.blank_pdf_key` / `answer_key_pdf_key` / `feedback_pdf_key`.

No column expresses a retention period or a delete-after date; `grep` for object deletion across
`apps/api/alppy` returns only the prompt-log purge. And `nouns_service.delete_student` — the endpoint
whose own docstring calls it *"the only operation in Alppy allowed to destroy evidence"* — is:

```python
db.delete(student)   # nouns_service.py:396
db.flush()
```

The DB cascade removes `attempt`, `mastery_snapshot`, `sheet_instance`, `misconception_note`,
`exercise_variant` and `class_student`. **It touches object storage not at all.** Every scanned page
and every answer-box crop of that child stays in the bucket, now orphaned — no row points at it, so
nothing can find it to delete later either.

Related: there is no anonymisation path. `Student` has `first_name` / `last_name` and no
`anonymised_at`. The brief's #38 asks whether a pupil can be deleted *without destroying class-level
statistics*: no. The only two options are keep everything, or cascade-delete the evidence.

**Why it matters here.** These are minors' data under the revised FADP, and a scanned answer sheet is
about the most sensitive artefact the product handles — handwriting, plus whatever a 13-year-old
wrote in the margin. The repo knows this: `core/config.py:122-132` refuses a staging deployment
pointed at the production bucket precisely because *"a scanned answer sheet is a photograph of a
child's handwriting with their name written at the top, and no gate reads it — what keeps it safe is
that it is only ever in one place."* That reasoning is right, and it makes the absence of any exit
from that one place the gap.

A parent exercises a deletion request in 2027. The school runs `DELETE /students/{id}?confirm=10VG3_07`.
The rows go; the child's handwriting stays in MinIO indefinitely, and the class's mastery statistics
change retroactively because their attempts were cascaded away.

**The fix.** Three separable pieces:
1. `scan.retain_until` / a school-level `scan_retention_days` setting, plus a
   `python -m alppy.cli purge-scans` sweeping images and crops — the exact shape
   `purge-prompt-logs` already established, which is the argument for it.
2. Make `delete_student` enumerate and delete the pupil's storage objects before `db.delete`.
3. Add anonymisation as the *default* answer: `student.anonymised_at`, names nulled, `uid` retained,
   attempts and snapshots kept. Class statistics survive; the person is no longer identifiable. Keep
   hard delete for the cases that genuinely need it.

**Migration risk.** Now: one column, one setting, one CLI command; no existing data is at stake
because nothing has been deleted yet. After launch: the schema work is unchanged, but every scan
accumulated in the meantime is un-attributed by the time you go looking — you will be reconciling
bucket keys against `scan_page` rows to find out what may be deleted, for a data class where guessing
wrong in either direction is bad.

---

#### H6 · No vector index on `source_chunk.embedding`

**What is wrong.** `SourceChunk.embedding` is `Vector(_EMBED_DIM)` (1024, per ADR 0001) and
`retrieval.py:661` orders by `SourceChunk.embedding.cosine_distance(...)`. The live database has four
indexes on that table and none of them is a vector index:

```
pk_source_chunk              btree (id)
ix_source_chunk_school_id    btree (school_id)
ix_source_chunk_source_page  btree (source_id, page)
ix_source_chunk_source_id    btree (source_id)
```

`grep -rn "ivfflat\|hnsw"` across `apps/api/alembic/versions/` and `apps/api/alppy/` returns nothing.
Every similarity search is therefore a sequential scan with a 1024-dimensional distance computed per
row, over every chunk in the tenant.

**Why it matters here.** A 400-page textbook produces thousands of chunks; a school's shelf is
several books per subject. Retrieval runs inside adaptive proposal generation, which the review
screen polls every 900 ms while it runs (`models/__init__.py:1341-1345`). This is invisible on the
demo seed and becomes the dominant cost on the first real shelf — and the runtime role carries
`statement_timeout = '15s'` (`infra/postgres/init.sql`), so past a certain corpus size the symptom is
not slowness but a hard failure inside a job.

**The fix.** An HNSW index for cosine distance:
`CREATE INDEX ON source_chunk USING hnsw (embedding vector_cosine_ops)`. Note it should be created
`CONCURRENTLY` outside the migration's transaction on any populated deployment. Since queries are
always tenant-filtered, measure whether a partial or composite arrangement beats the plain HNSW
before committing to one.

**Migration risk.** Now: trivial and fast — the table is small. After launch: still just an index, but
building HNSW over a large populated table is slow and memory-hungry, and doing it inside an Alembic
transaction will lock writes for the duration. That is a scheduled-maintenance job rather than a
deploy.

---

#### H7 · No audit trail for reads of student records

**What is wrong.** The `event` log is genuinely good — append-only, `occurred_at` separate from
`created_at`, an actor, a deliberately non-FK `subject_id` so the log outlives what it describes
(`models/__init__.py:987-1063`). But it is a *product agenda*, not an audit log, and `EventKind`
(`models/enums.py:130-165`) has exactly eleven members, all write verbs:
`source_imported`, `chapter_read`, `sheet_created`, `sheet_rendered`, `sheet_printed`,
`scan_uploaded`, `scan_confirmed`, `scan_reopened`, `adaptive_proposed`, `adaptive_exported`,
`feedback_written`, `feedback_approved`.

Not recorded anywhere: any **read**. Opening a pupil's profile, exporting a class matrix, viewing a
scanned page, listing a roster — none leaves a trace. Also not recorded: several *writes* that
matter — a teacher correcting a detection (`detection.corrected_by_id`/`corrected_at` hold it on the
row, but no event), discarding a scan page (M6 — no actor, no time at all), deleting a pupil,
enrolling or unenrolling one, assigning a branch.

**Why it matters here.** Under cantonal school data rules and the FADP, the question a school has to
be able to answer is "who looked at this child's record". Alppy's own tenancy design makes reads
broad on purpose and correctly: `_owned_student` deliberately widens to any teacher co-enrolled with
the pupil (`mastery_service.py:585-590`), so in a co-taught 10e année five or six adults can open a
named child's every answer. That is the right product decision. It is also exactly why the read needs
a trace — the wider the legitimate access, the less an access-control list tells you after the fact.

The repo already holds this value elsewhere: `ModelCall` exists *"to answer 'did any of our data go
to provider X'"*, content-free and kept indefinitely. There is no equivalent for the larger and more
routine exposure, which is a colleague reading the roster.

**The fix.** A separate `access_log` table — deliberately not more `EventKind` members, because the
agenda is teacher-facing prose and this is not: `(id, school_id, teacher_id, subject_type,
subject_id, action, occurred_at, request_id)`, append-only, its own retention. Write it from the same
dependency that already resolves the membership (`deps.get_membership`), which is the one place that
knows both the actor and the tenant.

**Migration risk.** Now: one new table, no backfill, no change to existing rows. After launch: the
table is just as easy to add, but you cannot reconstruct who read what before it existed — and the
first time anyone asks the question it will be about a period in the past.

---

#### H8 · The school year has no uniqueness and a hardcoded national calendar

**What is wrong.** Three things, all in the same small area.

*No uniqueness.* `school_year` has a surrogate PK, one index on `school_id`, and **no unique
constraint at all** (verified against the model metadata). Nothing prevents two rows labelled
`2025/26` in one school, and nothing prevents two rows with `is_current = true`.

*The resolver picks arbitrarily.* `class_service.current_school_year` does:

```python
select(SchoolYear).where(school_id==…).where(is_current.is_(True))
    .order_by(SchoolYear.starts_on.desc())
).scalars().first()          # class_service.py:117-122
```

With two current years it silently returns the later-starting one. Since `Class` and `Student` both
carry `school_year_id`, and `uq_class_code` / `uq_student_uid` are keyed on it, a duplicate year
splits a school's roster into two invisible halves that satisfy every constraint.

*One calendar for every canton.* `_school_year_bounds` (`class_service.py:98-105`):

```python
"""Swiss school years run August to July."""
start_year = today.year if today.month >= 8 else today.year - 1
return (f"{start_year}/{str(start_year+1)[-2:]}", date(start_year,8,1), date(start_year+1,7,31))
```

The entity is first-class and carries real `starts_on` / `ends_on` dates — which is the right shape,
and better than the brief feared. But the only way a row is ever created is this function, and there
is **no SchoolYear endpoint** (`grep -rn "SchoolYear" apps/api/alppy/api/v1/` → nothing). So a school
cannot set its own calendar, and every canton gets 1 August – 31 July.

**Why it matters here.** The dates are not decorative: `SchoolYear` is what partitions rosters and
UIDs, and (via C2) what partitions a pupil's whole history. A Genève établissement whose year the
canton defines differently from a Valais one cannot say so. And because rollover is automatic and
silent — the first request after 1 August creates a new year — a teacher logging in on 3 August 2027
finds their classes gone, with no action having been taken by anyone and no way to correct it.

**The fix.** `UNIQUE (school_id, label)` and a partial unique index
`CREATE UNIQUE INDEX ON school_year (school_id) WHERE is_current` — the second is the one that makes
the resolver's `.first()` honest. Then a small CRUD surface for the year, and per-school (or
per-canton, once `School.canton` is load-bearing) default bounds instead of the hardcoded August.
Consider replacing `is_current` with a derivation from `starts_on`/`ends_on` and today (M6), which
removes the flag-consistency problem rather than constraining it.

**Migration risk.** Now: two constraints; the demo data satisfies both. After launch: adding a partial
unique index to a table that has already accumulated two `is_current` rows fails, and resolving it
means deciding which of two half-rosters is real — per school, by hand.

---

### Medium

**M1 · Five FK columns are unindexed.** From a scan of `Base.metadata` for FK columns that are not the
leading column of any index:

```
chapter_competency.competency_id   -> competency.id   (CASCADE)
exercise_competency.competency_id  -> competency.id   (CASCADE)
class_subject.subject_id           -> subject.id      (CASCADE)
class_teacher_subject.subject_id   -> class_subject.subject_id (CASCADE)
competency.parent_id               -> competency.id   (SET NULL)
```

The first two matter most and for the same reason: both association tables have a composite PK whose
btree only answers the `chapter_id`- or `exercise_id`-first direction, and the *reverse* direction is
the one the product actually asks. "Which exercises serve this competency" is the adaptive engine's
core lookup; "which chapters credit this competency" is the mastery roll-up's. Both are seq scans on
the join table today. This is the same argument the codebase already made — and acted on — for
`ix_class_student_student_id` and `ix_class_teacher_subject_teacher`; these two were simply missed.
`competency.parent_id` is a 34-row reference table and is a non-issue at current scale, listed for
completeness. Fix: three indexes; trivial now and trivial later.

**M2 · Seventeen redundant indexes.** Queried from the live database: every one is a single-column
index whose column is the leading column of a composite index or unique constraint on the same table,
e.g. `ix_attempt_student_id` (student_id) inside `ix_attempt_student_answered` (student_id,
answered_at); `ix_source_chunk_source_id` inside `ix_source_chunk_source_page`; and eleven
`ix_*_school_id` each inside a composite that already starts with `school_id`. Most originate from
`SchoolScopedMixin`'s `index=True` (`db/base.py:56-62`) meeting a later composite. Each costs write
throughput and memory on the tables that grow. Full list in the Evidence appendix. Worth clearing in
one pass before the tables get large — after launch, dropping an index on a hot table is still easy
but wants `CONCURRENTLY`.

**M3 · `misconception_note.competency_ids` is an unconstrained JSONB array of UUID strings**
(`models/__init__.py:1004`): `competency_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)`.
No FK, no referential integrity, no join. This is a genuine repeating group in the brief's #22 sense
and the only one I found that is not deliberate — contrast `sheet_instance.item_plan`,
`detection.fill_ratios` / `bubble_boxes` and `scan.storage_keys`, which are frozen render- or
detection-time records where JSONB is the right answer and is argued as such in the model. A
competency reference should be a join table (`misconception_note_competency`) like the two that
already exist; as it stands, deleting a competency leaves dangling ids and nothing can query
"which notes touch this competency".

**M4 · The duplicate-attempt backstop has a NULL hole.** `uq_attempt_student_exercise_sheet`
(`models/__init__.py:1222-1226`) exists because *"mastery is a weighted mean over attempts, so a
duplicate silently doubles one lesson's weight."* Correct — but `attempt.sheet_id` is nullable and
`ON DELETE SET NULL`, and in Postgres NULLs are distinct in a unique index. Two attempts for the same
`(student, exercise)` with `sheet_id IS NULL` do not collide. Latent today (no sheet-delete endpoint
exists), but the guarantee is weaker than the comment claims. Fix: `NULLS NOT DISTINCT` (PG15+) on
the constraint, or a partial unique index for the NULL case.

**M5 · Twelve Postgres `ENUM` types where cantonal variation is expected.** `MasteryBand`,
`CurriculumKind`, `Locale`, `SheetTarget`, `ExerciseOrigin`, `ScanStatus`, `DetectionOutcome`,
`EventKind`, `JobKind`, `JobStatus`, `EventSubject`, `AnswerBoxFill` are all DB-level enums. Adding a
member needs `ALTER TYPE ... ADD VALUE`, which cannot share a transaction with DDL that uses it —
migration `0018` already had to work around this with a bare `op.execute("COMMIT")`, and `0019`'s
docstring explains why copying that is dangerous. Given the domain, `CurriculumKind` (a third
curriculum), `MasteryBand` and `Locale` (Italian-speaking Grisons/Ticino) are the plausible business
changes. Fix: for those three specifically, a lookup table; the operational enums (`JobStatus`,
`ScanStatus`) are correct as enums and should stay.

**M6 · Booleans that should be timestamps.** The codebase's own convention is excellent —
`approved_at`, `discarded_at`, `confirmed_at`, `reopened_at`, `rendered_at`, `extracted_at`,
`corrected_at` — which makes the exceptions stand out: `scan_page.registered`,
`scan_page.wrong_class`, `scan_page.discarded` (`models/__init__.py:1121-1136`) and
`school_year.is_current`. `discarded` is the one that matters: a teacher discards a scanned page and
the system records neither who nor when, on a row the model's own comment says is *"kept for audit"*.
Contrast `detection`, where the whole machine/teacher split exists because *"the teacher disagreed
with the scanner is the fact worth auditing"*. Fix: `discarded_at` / `discarded_by_id`; `registered_at`;
and derive `is_current` from the dates.

**M7 · UUIDv4 primary keys on the five high-insert tables.** `_pk()` uses `default=uuid.uuid4`
(`models/__init__.py:62-64`). Random keys mean every insert into `attempt`, `detection`, `scan_page`,
`event` and `source_chunk` lands in a random btree page — write amplification and index bloat that
grow with the table. Two consequences for the brief's #34: (a) UUIDv7 (time-ordered) would fix the
locality with no API change, since both are 128-bit and the column type is unchanged; (b) time
partitioning later is *blocked* on `attempt`, because a partitioned table's unique constraints must
include the partition key and `uq_attempt_student_exercise_sheet` has no time column — partitioning
by `answered_at` would require widening that constraint, which is a change to the anti-double-count
guarantee. Non-enumerable in URLs, so the other half of #24 is fine. Decide now whether `attempt` is
ever partitioned; the constraint is cheap to widen today and awkward once it is enforcing something.

**M8 · `établissement` vs `site`, and canton as data.** `School` is `(id, name, canton String(2)
nullable, default_curriculum)` (`models/__init__.py:75-90`). There is one entity where the Swiss
domain has two: the legal/administrative *établissement* and the physical *site/bâtiment*, and
multi-site establishments are common in Romandie. Nothing today needs the distinction — no room
booking, no timetabling — so this is correctly deferred rather than wrong, but it should be a
conscious deferral: adding `site` later means deciding, per existing school, which rows belong to
which building. Separately, `canton` exists as data (good, and it is what H2's `stream` table would
key on) but is **nullable and unused** — nothing branches on it, and there is no `canton` table
carrying the rules (grading scale, calendar, streaming vocabulary) that would make it load-bearing.

**M9 · The MER model is thinner than the domain.** `Source` carries `title`, `publisher`, `isbn`,
`url`, `filename`, `language`, `page_count` (`models/__init__.py:480-509`) — a good start, and
deliberately unvalidated so a teacher typing a cover is not argued with. Missing for *moyens
d'enseignement romands*: **edition/year** (the brief's point — exercise numbering shifts between
editions, and `exercise.source_page` + `exercise.label` are the citation), the **per-year volume**
structure (a MER title spans 9e/10e/11e), the **artefact type** within a year (livre/théorie,
fichier, aide-mémoire — currently three separate uploads with nothing relating them), and any
**cantonally-adopted vs teacher-supplied** flag. `SourceSection` handles book → chapter → page well.
So: an Alppy exercise can cite *this PDF, this page, this label*, but not *this edition* — and the
citation does not survive a new edition, it silently points at the wrong exercise.

**M10 · Deleting a `subject` has contradictory delete rules.** `chapter.subject_id` is CASCADE and
`sheet.chapter_id` is RESTRICT. So `DELETE FROM subject` tries to cascade away the chapters, which the
sheets refuse — the delete fails with a constraint error naming `chapter`, not `subject`. Meanwhile
`sheet.subject_id` is itself CASCADE, so the outcome depends on the order Postgres evaluates the two
paths. There is no subject-delete endpoint (`POST /subjects` and `PATCH /subjects/{id}` only), so this
is latent; it should be resolved deliberately before one is added, most likely by making
`chapter.subject_id` RESTRICT to match.

---

### Low

**L1 · There is no QR code.** The brief assumes one; the product does not use one. Identity is a
printed **UID bubble grid** — `layout.uid_cell_centre_mm(slot, row)` (`sheets/layout.py:208`) draws
it, `detector.read_uid_grid` (`scan/detector.py:571`) reads it, and the result lands in
`scan_page.detected_uid` with `uid_confidence`. Against the brief's #21: the identifier is
`Student.uid`, e.g. `7B_15` — **guessable and enumerable by construction**, it is not unique per print
run (there is no print-run entity; `answer_box_placement` is keyed `(sheet_id, student_uid,
copy_page, item_index)` and *replaced* on every re-render), so reprints deliberately collide and the
newest render wins. For the actual threat model this is defensible: the sheet is paper, the UID is
printed next to the child's name, and a grid is robust to a photocopy in a way a QR is not. But it
means the identifier carries no authenticity — anyone can fill in any UID grid — and a reprint after
an edit invalidates the crop geometry of the earlier print, which is exactly what
`AnswerBoxPlacement` exists to prevent for the *current* print. Worth an explicit product decision
rather than leaving it implicit.

**L2 · Co-teaching is supported; roles and substitutes are not.** `class_teacher_subject`
(`models/__init__.py:197-244`) has PK `(class_id, teacher_id, subject_id)`, so several teachers can
hold the same branch in the same class — the brief's #6, first half, is a genuine yes, and the
composite FK to `class_subject` makes "you cannot be assigned a branch this class does not study" a
constraint rather than a convention, which is nicely done. Missing: a **role** (titulaire / appui /
remplaçant / co-enseignant) and, per C1, any validity period. So a support teacher and the titular
teacher are indistinguishable, and a `remplaçant` is modelled by adding a row in March and deleting
it in May.

**L3 · `0025_timestamp_defaults.py` is untracked but applied.** `git status` lists it as `??`; the
live database reports `alembic_version = 0025`. The fix for a production-affecting bug exists only in
one working tree. Commit it.

**L4 · Leading-wildcard `ILIKE`.** `event.summary` (`services/event_service.py:138`) and
`exercise.statement` / `label` / `title` (`api/v1/sources.py:367-369`) use `%needle%`, which no btree
can serve. Both are pre-narrowed by an indexed predicate (school + `occurred_at`; one section), and
`sources.py:358` says so deliberately. Fine at current scale; `pg_trgm` GIN indexes are the answer
when it stops being.

**L5 · The naming convention is consistent but nowhere stated.** The de facto rule, as measured: **all
identifiers — tables, columns, constraints, indexes — are English**; French exists only as *data*, in
`labels`/`description` JSONB and the i18n catalogues. Domain nouns are anglicised rather than
borrowed (`class` for classe, `subject` for Branch, `chapter` for Theme), which does mean the schema
vocabulary and the UI vocabulary differ — `Chapter` is "Theme" on screen, `Subject` is "Branch" — a
mapping a new reader has to learn from `docs/data-model.md`. Constraint and index names come from
`NAMING_CONVENTION` in `db/base.py:13-20` and are consistent. One wart: `class` is a reserved word in
enough contexts that every migration quotes it (`"class"`), and the model class is `Class`. Write the
rule down; it is a good rule that currently exists only as a habit.

---

## 4 · Reconstructed ER model (as it currently stands)

Reconstructed from the migration chain `0001`→`0025` applied in sequence and cross-checked against
the live database. 36 tables + `alembic_version`: 29 mapped classes, 7 association tables.
Split into two diagrams for legibility; `student`, `sheet` and `exercise` appear in both.

**Legend.** `TENANT` = carries `school_id NOT NULL` (`SchoolScopedMixin`). Delete rule shown on the
relationship label as `C` (CASCADE), `R` (RESTRICT), `N` (SET NULL). Italic FKs are nullable.

### 4.1 Tenancy, curriculum and corpus

```mermaid
erDiagram
    school ||--o{ school_year : "school_id C"
    school ||--o{ subject : "school_id C"
    school ||--o{ teacher : "home_school_id C"
    school }o--o{ teacher : "teacher_school (joined_at, no end)"

    school_year ||--o{ class : "school_year_id C"
    school_year ||--o{ student : "school_year_id C"

    teacher ||--o{ class : "head_teacher_id R"
    class ||--o{ student : "home_class_id R"
    class }o--o{ student : "class_student (enrolled_at, no end)"
    class }o--o{ subject : "class_subject (position)"
    class_subject ||--o{ class_teacher_subject : "composite FK C"
    teacher ||--o{ class_teacher_subject : "teacher_id R"

    competency ||--o{ competency : "parent_id N"
    competency ||--o{ chapter : "primary_competency_id N"
    chapter }o--o{ competency : "chapter_competency"
    subject ||--o{ chapter : "subject_id C"

    subject ||--o{ source : "subject_id C"
    source ||--o{ source_section : "source_id C"
    source ||--o{ source_chunk : "source_id C"
    source ||--o{ exercise : "source_id N"
    source_section ||--o{ exercise : "source_section_id N"
    source_chunk ||--o{ exercise : "source_chunk_id N"
    chapter ||--o{ exercise : "chapter_id N"
    exercise }o--o{ competency : "exercise_competency"
    exercise ||--o{ exercise_variant : "exercise_id C"
    student ||--o{ exercise_variant : "student_id C"

    school {
        uuid id PK
        string name
        string canton "nullable, String(2), unused"
        enum default_curriculum "PER | LP21"
    }
    teacher {
        uuid id PK
        uuid home_school_id FK "NOT the request tenant"
        string email UK
        string password_hash
    }
    school_year {
        uuid id PK
        uuid school_id FK
        string label "no uniqueness"
        date starts_on
        date ends_on
        bool is_current "no partial unique"
    }
    class {
        uuid id PK
        uuid school_id FK
        uuid school_year_id FK
        uuid head_teacher_id FK
        string code "UK per school+year; free text"
        string label
    }
    student {
        uuid id PK
        uuid school_id FK
        uuid home_class_id FK "mints uid"
        uuid school_year_id FK "year-bound identity"
        string uid "UK per school+year"
        int number
        string first_name
        string last_name
    }
    competency {
        uuid id PK
        enum curriculum "PER | LP21"
        string code "UK per curriculum; no edition"
        uuid parent_id FK "2 levels seeded"
        string subject_key "matched to subject.key BY STRING"
        int cycle
        jsonb labels
    }
    chapter {
        uuid id PK
        uuid school_id FK
        uuid subject_id FK
        uuid primary_competency_id FK "NULL == unfiled"
        string key "UK per school+subject"
        jsonb labels
    }
    exercise {
        uuid id PK
        uuid school_id FK
        enum type "mcq|true_false|open"
        enum origin "textbook|ai_generated|teacher"
        text statement
        jsonb options
        int difficulty "CK 1..5"
        timestamp approved_at "AI gate"
        timestamp discarded_at
    }
    source {
        uuid id PK
        string title "no edition, no volume, no artefact type"
        string isbn
        enum status
        text notice
    }
    source_chunk {
        uuid id PK
        int page
        text text
        vector embedding "1024d, NO INDEX"
    }
```

### 4.2 Sheets, scanning, grading, mastery and operations

```mermaid
erDiagram
    class ||--o{ sheet : "class_id C"
    chapter ||--o{ sheet : "chapter_id R"
    sheet ||--o{ sheet : "derived_from_id N"
    sheet }o--o{ sheet : "sheet_source (position)"
    sheet ||--o{ sheet_item : "sheet_id C"
    exercise ||--o{ sheet_item : "exercise_id R"
    sheet ||--o{ sheet_instance : "sheet_id C"
    student ||--o{ sheet_instance : "student_id C"
    sheet ||--o{ answer_box_placement : "sheet_id C"
    misconception_note ||--o{ sheet_instance : "feedback_id N"
    student ||--o{ misconception_note : "student_id C"
    sheet ||--o{ misconception_note : "based_on_sheet_id N"

    sheet ||--o{ scan : "sheet_id N"
    scan ||--o{ scan_page : "scan_id C"
    scan_page ||--o{ detection : "scan_page_id C"
    sheet_item ||--o{ detection : "sheet_item_id N"
    exercise ||--o{ detection : "exercise_id N"
    student ||--o{ scan_page : "student_id N"
    sheet_instance ||--o{ scan_page : "sheet_instance_id N"

    detection ||--o{ attempt : "detection_id N"
    student ||--o{ attempt : "student_id C"
    exercise ||--o{ attempt : "exercise_id R"
    sheet ||--o{ attempt : "sheet_id N"
    scan ||--o{ attempt : "confirmed_scan_id N"

    student ||--o{ mastery_snapshot : "student_id C"
    competency ||--o{ mastery_snapshot : "competency_id C"
    student ||--o{ mastery_branch_snapshot : "student_id C"

    job ||--o| adaptive_proposal : "job_id C UK"
    model_call ||--o{ prompt_log : "model_call_id N"
    job ||--o{ prompt_log : "job_id N"

    sheet {
        uuid id PK
        uuid class_id FK
        uuid chapter_id FK "NOT NULL, unfiled fallback"
        uuid derived_from_id FK "adaptive lineage"
        string layout_version "print/scan contract"
        float default_points_correct "CK 0..20"
        float default_points_penalty "magnitude, sign applied at grading"
        timestamp rendered_at
    }
    sheet_item {
        uuid id PK
        int position "UK per sheet"
        text statement_override "per-printing wording"
        text expected_answer "per-printing answer"
        int answer_box_lines "CK 0..14"
        float points_correct "NULL == sheet default"
    }
    sheet_instance {
        uuid id PK
        string student_uid
        jsonb item_plan "frozen at render"
        string group_label "label, not FK - recomputed"
    }
    answer_box_placement {
        uuid id PK
        string student_uid
        int copy_page
        int item_index
        float x_mm
        float y_mm
        float w_mm
        float h_mm "measured in Chromium, never recomputed"
    }
    scan_page {
        uuid id PK
        string image_key "no retention"
        bool registered
        string detected_uid "OCR of bubble grid, not QR"
        float uid_confidence
        bool wrong_class
        bool discarded "no actor, no timestamp"
    }
    detection {
        uuid id PK
        int item_index
        enum outcome
        int detected_index "teacher-overwritable"
        int machine_index "written once"
        enum machine_outcome "written once"
        float machine_confidence "written once"
        string crop_key "no retention"
        text transcription
        text machine_transcription
        bool verdict_correct
        bool machine_verdict_correct
        string vision_model
        text reference_answer
        uuid corrected_by_id FK
        timestamp corrected_at
    }
    attempt {
        uuid id PK
        bool correct "the mastery signal"
        float score "the bareme - may be negative"
        int difficulty "snapshot"
        timestamp answered_at
    }
    mastery_snapshot {
        uuid id PK
        timestamp computed_at
        float score "CK 0..1"
        enum band
        int attempts_count
    }
```

**Tenant reachability (brief #35).** Every table is reachable from `school` — 26 carry `school_id`
directly, 6 association tables reach it through a parent that does, and the three deliberate
exceptions are `school` itself, `competency` (shared reference data) and `teacher`/`teacher_school`
(a teacher spans schools; both are read *before* a tenant is known, during login). Verified against
the live database: 33 tables have RLS `ENABLE` **and** `FORCE`, with 33 policies — matching
`0024`'s 26 + 6 + 1 exactly. I found no table where a query could cross establishments without an
explicit predicate.

**Blast radius of one forgotten `WHERE` (brief #36).** Small, and this is the strongest part of the
design. Isolation is enforced in the database, not only in application code: policies compare
`school_id` to `nullif(current_setting('app.current_school_id', true), '')::uuid`, so an unbound
session sees **nothing** rather than everything, and `db/tenancy.py` re-applies the GUC on
`after_begin` because `set_config(..., true)` is transaction-scoped and services commit mid-request.
A handler that forgets `TenantDep` reads an empty list. The one caveat is the deployment shape:
Postgres does not apply policies to a table's owner, and `.env` has `ALPPY_DATABASE_URL` pointing at
`alppy` (the owner, explicitly `BYPASSRLS` per `infra/postgres/init.sql`) — so **RLS is inert in local
development**. That is correct for local, and `core/config.py:_refuse_unsafe_deployment` refuses to
boot a `staging` or `production` API whose DSN names the owning role. Confirmed the compose runtime
does the right thing: `alppy-api-1` connects as `alppy_app`.

---

## 5 · Proposed target ER model (Critical and High only)

Only the deltas for C1, C2, H1, H2, H3 and H8 — the findings whose fix changes shape. H4–H7 are
scripts, indexes, a CLI command and one new flat table, and need no diagram.

```mermaid
erDiagram
    person ||--o{ student : "person_id  [NEW: durable identity]"
    school ||--o{ person : "school_id"
    school ||--o{ canton_profile : "canton  [NEW]"
    canton_profile ||--o{ stream : "canton  [NEW: VP/VG, R1-R3, Niv I/II]"
    stream ||--o{ teaching_group : "stream_id  [NEW]"

    school_year ||--o{ teaching_group : "school_year_id"
    class ||--o{ teaching_group : "homeroom vs course group"

    teaching_group ||--o{ group_membership : "[NEW: valid_from/valid_to]"
    student ||--o{ group_membership : "student_id"
    teaching_group ||--o{ group_staffing : "[NEW: role + validity]"
    teacher ||--o{ group_staffing : "teacher_id"

    competency ||--o{ competency : "parent_id  (5 real PER levels)"
    competency ||--o{ competency_niveau : "[NEW: Niv 1s|2|3]"
    curriculum_edition ||--o{ competency : "edition_id  [NEW]"

    person ||--o{ attempt : "person_id  [REPOINTED]"
    person ||--o{ mastery_snapshot : "person_id  [REPOINTED]"
    student ||--o{ sheet_instance : "student_id  (stays year-bound)"

    person {
        uuid id PK
        uuid school_id FK
        string first_name
        string last_name
        timestamp anonymised_at "H5: erase the name, keep the evidence"
    }
    student {
        uuid id PK
        uuid person_id FK "NEW"
        uuid school_year_id FK
        uuid home_class_id FK
        string uid "still UK per school+year"
        int number
    }
    group_membership {
        uuid id PK
        uuid teaching_group_id FK
        uuid student_id FK
        date valid_from "NEW"
        date valid_to "NEW, NULL == current"
    }
    group_staffing {
        uuid id PK
        uuid teaching_group_id FK
        uuid teacher_id FK
        uuid subject_id FK
        enum role "titulaire|appui|remplacant|co  [NEW]"
        date valid_from "NEW"
        date valid_to "NEW"
    }
    teaching_group {
        uuid id PK
        uuid school_year_id FK
        uuid subject_id FK
        uuid stream_id FK "NEW, nullable"
        string code
    }
    stream {
        uuid id PK
        string canton FK "NEW - lookup, not enum"
        string code "VP, VG, R1, R2, R3, Niv1..."
        string label
        int position
    }
    curriculum_edition {
        uuid id PK
        enum curriculum "PER | LP21"
        string edition "CIIP-2010"
        date valid_from
        date valid_to
    }
    competency {
        uuid id PK
        uuid edition_id FK "NEW - H3"
        uuid parent_id FK
        string code "UK per (curriculum, edition, code)"
        enum kind "domaine|objectif|composante|progression|attente  [NEW]"
        string year "9H|10H|11H, nullable  [NEW]"
        bool is_official "NEW - H3"
    }
    canton_profile {
        string canton PK
        date year_starts_on "H8"
        date year_ends_on "H8"
        string grading_scale
    }
    school_year {
        uuid id PK
        uuid school_id FK
        string label "UK (school_id, label)  [NEW]"
        date starts_on
        date ends_on
        bool is_current "partial UK per school  [NEW]"
    }
```

### Deltas

| # | Delta | Fixes | Kind |
|---|---|---|---|
| 1 | New `person`; `student.person_id` NOT NULL; repoint `attempt`, `mastery_snapshot`, `mastery_branch_snapshot`, `misconception_note` at `person_id` | C2 | Additive + repoint; 1:1 backfill |
| 2 | `person.anonymised_at`; `delete_student` deletes storage objects; `purge-scans` CLI + `scan.retain_until` | H5 | Additive |
| 3 | `class_student` → `group_membership` with `valid_from`/`valid_to`; PK widens to include `valid_from` | C1 | Rename + widen; open-ended backfill |
| 4 | `class_teacher_subject` → `group_staffing` with `role` + validity | C1, L2 | Rename + widen |
| 5 | `teacher_school.left_at` | C1 | Additive |
| 6 | Split `class` into homeroom `class` and `teaching_group` — **optional**, see Open question 2 | — | Structural |
| 7 | `competency.kind` + `competency.year`; re-seed the five real PER levels from the CIIP PDFs; move Pythagore to `MSN 34` | H1 | Additive + re-seed |
| 8 | `competency_niveau`; `teaching_group.stream_id`; `stream` and `canton_profile` lookup tables | H2 | Additive |
| 9 | `curriculum_edition`; `competency.edition_id`; `competency.is_official`; widen `uq_competency_code` to `(curriculum, edition, code)` | H3 | Additive + widen UK |
| 10 | `UNIQUE (school_id, label)` and partial unique on `is_current`; per-canton year bounds; a SchoolYear endpoint | H8 | Constraints + CRUD |
| 11 | `access_log` table written from `deps.get_membership` | H7 | New table |
| 12 | 3 FK indexes; drop 17 redundant; HNSW on `source_chunk.embedding` | M1, M2, H6 | Index-only |
| 13 | `compare_server_default=True` in the drift gate; declare or drop the 7 defaults | H4 | Script + models |

**Deliberately NOT proposed.** Delta 6 is listed but not recommended without an answer to Open
question 2 — `Class` already carries the teaching-group role adequately (see below), and splitting it
is the kind of change that is worth doing once, with the answer in hand, rather than twice.

---

## 6 · Open questions for you

**1 · Cantonal scope.** The brief left this as a placeholder. It changes the size of H2 substantially:
Vaud + Genève is two `stream` vocabularies and two calendars; "all Romandie" is six, plus Valais's
bilingual establishments where a single school runs PER *and* LP21 — which the schema already
anticipates (`School.default_curriculum` is per school, and `Chapter.primary_competency_id` resolves
per school) but which would need `default_curriculum` to move from the school to the teaching group.
*Consequence:* if the answer is "Vaud only for launch", H2 drops to Medium and delta 8 shrinks to one
seeded table.

**2 · Is the homeroom/teaching-group distinction worth a second entity?** I want to correct the
brief's prior here rather than confirm it. The audit anticipated finding
`student → class → maths lessons` and asked me to flag it Critical. **The schema does not assume
that.** `class_student` is a many-to-many, `Student.home_class_id` is separately the class that
minted the UID, `class_subject` says what a group studies and `class_teacher_subject` who teaches it.
A Vaud niveau-2 maths group *can* be modelled today: a `Class` with its own code, its own head
teacher, `class_subject = {mathematics}`, and pupils enrolled from several homerooms whose
`home_class` remains their homeroom. The docstring even says so — *"A teaching group"*.

What is missing is a **discriminator**: nothing marks which `Class` rows are homerooms and which are
course groups, so the UI, the tree and every roster read treat them identically, and a pupil in three
groups has three equally-weighted "classes". *Options:* (a) add `class.kind` (`homeroom` | `course`),
one nullable column, no restructuring — my recommendation; (b) the full split in delta 6, cleaner
long-term but touches every read path; (c) leave it as convention. *Consequence:* (a) and (c) are
compatible with everything else in this report; (b) should be sequenced *before* C1, since it changes
which table grows the validity columns.

**3 · What should happen on 1 August?** There is no rollover code and no SchoolYear endpoint, so
today a new year materialises silently on the first request in August and every teacher's classes
disappear. Someone has to decide: does a school roll classes forward (same group, new year, same
pupils), re-import a roster from the cantonal system, or start empty? *Consequence:* this determines
whether delta 1 is enough for C2 or whether you also need a `promotion` record linking last year's
group to this year's. It is also the one question that has a hard deadline.

**4 · Deletion vs anonymisation as the default answer to a parent request.** Today the only option
destroys the evidence and silently changes class statistics. I have proposed anonymisation as the
default (delta 2). *Consequence:* if your cantonal DPO requires true erasure of the pedagogical record
and not just the identifier, `anonymised_at` is insufficient and H5 needs a full cascade *including*
object storage, which is a larger piece of work. This is a legal question, not an engineering one, and
it should be asked before delta 2 is built.

**5 · Should invented curriculum codes keep CIIP notation?** `MSN 31.2` is not a CIIP code.
*Options:* renumber to a clearly-Alppy namespace; keep the notation and mark it in the UI; or replace
the invented level entirely with the real composante/progression levels from H1 (which removes the
need to invent anything). I recommend the third — the CIIP PDFs extract cleanly, so the real data is
obtainable. *Consequence:* the third makes H1 and H3 one piece of work instead of two, but it is a
larger seed effort.

**6 · Does `attempt` ever need time partitioning?** Answering "no" now is fine and costs nothing.
Answering "yes" later costs a change to `uq_attempt_student_exercise_sheet`, which is the constraint
enforcing "re-scanning a pile corrects the record rather than doubling it" (M7). *Consequence:* if
there is any chance of yes, widen the constraint to include `answered_at` while the table is small.

---

## 7 · What I could not verify

- **A true from-empty replay of the migration chain (brief #40).** Both `check-schema-drift.py` and
  `check-rls.py` drop the `public` schema, and the only Postgres available holds live development
  data — running them would have been destructive, which the audit rules forbid. What I did instead:
  confirmed the chain is linear and unbranched (`0001`→`0025`, every `down_revision` matching), that
  the live database reports `alembic_version = 0025` with 37 tables and 33 RLS policies exactly
  matching `0024`'s declared sets, and ran `compare_metadata` read-only against it. That is strong
  evidence the chain replays to the models, but it is not the same as watching it run from empty.
  **To close this:** `createdb alppy_drift && ALPPY_DATABASE_URL=…/alppy_drift python
  scripts/check-schema-drift.py` — one command, on a throwaway database.
- **RLS behaviour under the low-privilege role.** I confirmed the policies exist, are `FORCE`d, and
  that `alppy-api-1` connects as `alppy_app` — but `check-rls.py` is what actually *exercises* them,
  and it needs the same disposable database. I did not test that a cross-tenant read is refused in
  practice; I only established that the mechanism is present and correctly shaped.
- **Whether the seven `server_default` drifts also appear in a fresh database.** They are present in
  the live one; I inferred from reading `0003`/`0006`/`0007`/`0014` that they originate in the
  migrations rather than in a manual `ALTER`, but confirming needs the from-empty replay above.
- **LP21 code verification.** I verified the PER side against primary CIIP sources. I did **not**
  independently verify the LP21 codes — `docs/curriculum.md` §5 reports that `lehrplan21.ch` and the
  cantonal viewers return HTTP 403 to direct fetches, and I did not retry them. Every LP21 finding in
  this report rests on the repo's own account of its sourcing, which is self-declared "Verified
  (content), code position approximate" for most rows. **Treat H1/H3's LP21 half as unverified.**
- **Whether the PER "composante" level has an official code notation.** I verified from the CIIP PDF
  that composantes are numbered 1–8 within an objective and phrased as continuations ("… en
  définissant…"). Whether CIIP's own database (`bdper.plandetudes.ch`) assigns them stable
  identifiers I could not determine — the portal is JavaScript-rendered and returned no static text.
  This affects *how* delta 7 should code the new level, not whether it is needed.
- **Query plans.** All index findings are from schema and code reading, not from `EXPLAIN ANALYZE` —
  the development database has only demo-seed volumes, so a plan there would not be informative. The
  missing-index findings (M1, H6) are structural and hold regardless; the redundant-index list (M2) is
  mechanically derived from prefix containment and is exact.
- **Actual production data volumes**, so the growth/partitioning assessment (M7, #34) is reasoned from
  the domain — a class of 24, a term of weekly sheets, a 400-page textbook — rather than measured.

---

## Evidence appendix

**Read-only drift comparison** (§H4) — run inside `alppy-api-1` against the live database, no DDL:

```python
ctx = MigrationContext.configure(conn, opts={"compare_type": True,
                                             "compare_server_default": True})
compare_metadata(ctx, Base.metadata)   # -> 7 modify_default entries
```

**FK columns with no leading-column index** (§M1) — from `Base.metadata`:

```
chapter_competency.competency_id, exercise_competency.competency_id,
class_subject.subject_id, class_teacher_subject.subject_id, competency.parent_id
```

**Redundant indexes** (§M2) — from live `pg_indexes`, single-column indexes contained as a prefix of a
composite on the same table:

```
answer_box_placement.ix_..._sheet_id      ⊂ uq_answer_box_placement_slot
attempt.ix_attempt_student_id             ⊂ ix_attempt_student_answered, uq_attempt_student_exercise_sheet
chapter.ix_chapter_school_id              ⊂ uq_chapter_key
class.ix_class_school_id                  ⊂ uq_class_code
event.ix_event_school_id                  ⊂ ix_event_school_occurred
exercise.ix_exercise_source_section_id    ⊂ ix_exercise_source_section
exercise.ix_exercise_subject_id           ⊂ ix_exercise_subject_origin
mastery_branch_snapshot.ix_..._student_id ⊂ ix_mastery_branch_student
mastery_snapshot.ix_..._student_id        ⊂ ix_mastery_student_competency
misconception_note.ix_..._student_id      ⊂ ix_misconception_note_student_sheet
prompt_log.ix_prompt_log_school_id        ⊂ ix_prompt_log_school_created
sheet_instance.ix_..._sheet_id            ⊂ uq_instance_student
sheet_item.ix_sheet_item_sheet_id         ⊂ uq_sheet_item_position
source_chunk.ix_source_chunk_source_id    ⊂ ix_source_chunk_source_page
source_section.ix_..._source_id           ⊂ ix_source_section_source, uq_source_section_position
student.ix_student_school_id              ⊂ uq_student_uid
subject.ix_subject_school_id              ⊂ uq_subject_key
```

**Delete-rule census** (§4, M10) — 67 CASCADE, 6 RESTRICT, 28 SET NULL, 0 NO ACTION. The six RESTRICTs
are `attempt.exercise_id`, `sheet_item.exercise_id`, `sheet.chapter_id`, `student.home_class_id`,
`class.head_teacher_id`, `class_teacher_subject.teacher_id` — each argued in the model, and together
they are what stops a delete from reaching student work. The CASCADEs that touch pedagogical records
(`attempt.student_id`, `mastery_snapshot.student_id`, `sheet_instance.student_id`) are reachable from
exactly one endpoint, `DELETE /students/{id}`, which requires the pupil's UID typed back and is
restricted to the head teacher of their home class.

**PER primary sources** (§H1, H2) — `pdftotext -layout` over CIIP-published print PDFs:
[`PER_print_MSN_31.pdf`](https://bdper.plandetudes.ch/uploads/per_pdf/Mathematiques_et_sciences_de_la_nature/Mathematiques/PER_print_MSN_31.pdf),
[`PER_print_MSN_34.pdf`](https://bdper.plandetudes.ch/uploads/per_pdf/Mathematiques_et_sciences_de_la_nature/Mathematiques/PER_print_MSN_34.pdf),
both © CIIP 2010, from [bdper.plandetudes.ch](https://bdper.plandetudes.ch). The portal at
[plandetudes.ch](https://www.plandetudes.ch) redirects to a JavaScript-rendered site that returned no
static text.
