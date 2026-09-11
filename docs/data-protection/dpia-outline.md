# DPIA — outline and factual inputs

> **This is not a DPIA.** It is the structure one needs, and the facts about
> this system that a qualified person would otherwise have to extract from the
> codebase. **The risk assessment, the necessity and proportionality analysis,
> and every legal conclusion are deliberately left blank** — they carry legal
> weight, they are not engineering work, and a plausible-looking draft of them
> is worse than an empty section because it gets signed.
>
> What follows is the part engineering *can* answer: what data, from whom, why,
> where it goes, how long it stays, and what is actually built.

Under the revised Swiss FADP (nLPD), a DPIA is required where processing is
likely to present a high risk to the personality or fundamental rights of the
data subject. Two factors here point that way and should be stated rather than
argued around: **the data subjects are minors**, and the processing includes
**automated evaluation of their schoolwork**.

---

## 1 · Who fills in what

| Section | Who | Status |
|---|---|---|
| 1–5 (description, data, purposes, recipients, retention) | Engineering | **Below, and current** |
| 6 (necessity and proportionality) | Data-protection counsel / DPO | **Empty** |
| 7 (risks to data subjects) | Counsel / DPO, with engineering input | **Empty** |
| 8 (measures) | Both — technical measures listed below, organisational ones are not | **Partial** |
| 9 (residual risk, consultation, sign-off) | The controller | **Empty** |

---

## 2 · What the processing is

A teacher builds an exercise sheet from their own textbooks and prints it. Each
pupil's copy carries a printed UID and no name. Completed copies are scanned or
photographed; the system identifies the pupil from the UID, grades multiple-
choice and true/false items automatically, and — where configured — sends the
cropped answer box of a written answer to a model provider for a verdict. A
teacher reviews and confirms every pile. Confirmed readings become attempts,
which feed a five-band mastery model per competency.

**Controller:** the school (to be confirmed by counsel — the alternative
reading, that Alppy is a joint controller for product improvement, has not been
taken and nothing in the product currently does anything that would require it).
**Processor:** Alppy.
**Data subjects:** pupils in Swiss compulsory school, cycle 3 (roughly ages 10
to 16), and their teachers.

---

## 3 · Categories of personal data

| Category | Fields | About |
|---|---|---|
| Identity | `Student.first_name`, `last_name`, `uid`, class, school year | Pupil |
| Identity | `Teacher.email`, name, preferences | Teacher |
| **Schoolwork** | `Attempt.correct`, `score`, `Detection.transcription`, `verdict_correct` | Pupil |
| **Biometric-adjacent** | Page images and answer-box crops — **photographs of handwriting** | Pupil |
| Derived evaluation | `MasteryBand` per competency, `MisconceptionNote` | Pupil |
| Audit | `AccessLog` (who read whose file), `ModelCall` (content-free) | Teacher |

**The handwriting is the reason this document exists.** Everything else is what
a school's existing register already holds.

Two structural facts worth stating explicitly, because they change the analysis:

* **`Person` and `Student` are separate.** `Student` is one year of a pupil;
  `Person` is the pupil. Mastery history hangs off `Person` and survives a year
  boundary; the print and scan path is year-bound. Deleting a `Student` does not
  destroy evidence, deleting a `Person` does, and erasure does both.
* **A pupil's name never reaches a model provider.** Prompts carry the UID
  (`7B_15`). `ai/scrub.py` *raises* rather than redacting, because a leak is a
  caller bug and a redaction is a silent one.

---

## 4 · Purposes

1. Grading the teacher's own assessment, at the teacher's instruction.
2. Producing a per-competency mastery picture for that teacher.
3. Generating differentiated exercises — **never printed without the teacher's
   explicit approval** (`Exercise.approved_at`).

**Not** for: profiling outside the teaching relationship, any use across
schools, analytics on teachers (there is none), or training a model. No data is
used to improve a vendor's model where the vendor's API is configured for it
(`store=False`); that is a vendor-side setting to be confirmed on the account,
not only in the request.

---

## 5 · Recipients, transfers and retention

Recipients and transfers: see
[`subprocessors.md`](subprocessors.md) §1 and §3. **In the shipped
configuration nothing leaves the deployment** — the default AI provider is
offline.

| Data | Retention | Enforced by |
|---|---|---|
| Scan images and crops | **400 days** (school year + one term) | `purge-scan-images`, nightly 03:30 |
| Prompt log (content) | 30 days, and **off by default** | `purge-prompt-logs`, nightly 03:10 |
| Access log (read audit) | 365 days | `purge-access-log`, nightly 03:20 |
| `ModelCall` (content-free audit) | 1095 days (three years) | `purge-model-calls`, nightly 03:40 |
| Roster, attempts, mastery | Life of the school's account | Erasure on request |
| Backups | **Do not exist** | — |
| Application logs | **Set by the aggregator, once one exists** | — |

Backups are a gap, not an omission from this table.

On application logs: **no log line identifies a pupil.** The access line carries
the route and not the row (`core/logging.py:scrub_path`, tested in
`test_log_hygiene.py`), so a retention window on them is an operational choice
rather than a data-protection one. The exception is deliberate and is the
**erasure log** — `privacy.erasure`, emitted on every anonymisation and
deletion, carrying a `person_id` and a UID and never a name. It exists precisely
so that it OUTLIVES the database: after a restore, every erasure since the
restore point has to be re-applied, and a record kept inside the database being
restored is a record the restore takes away.

---

## 6 · Necessity and proportionality

> **To be completed by counsel / the DPO.** Engineering input available on
> request for: why the crop rather than the whole page is sent, why the image
> is retained at all after a verdict is stored, and what the product loses at
> each shorter retention window.

---

## 7 · Risks to data subjects

> **To be completed by counsel / the DPO.** The factual inputs a risk assessment
> would need are below; the assessment itself is not attempted.

| Risk | What is built | What is not |
|---|---|---|
| A pupil's work read by a teacher who should not see it | Two tenancy layers: every query takes `school_id`, and Postgres row-level security keyed on `app.current_school_id`. Reading a pupil's past requires the teacher's employment window to have **overlapped** theirs, not merely "ever". | — |
| A name reaching a model provider | `ai/scrub.py` raises on any name; the sheet carries a UID and no name; the crop is cut by measured geometry inside the statement region. | Nothing prevents a pupil writing their name **inside** the answer box. |
| A wrong mark from an automated reading | A written answer is graded on a verdict, never a heuristic; pending, unreadable and offline all produce **no attempt** and count as skipped, never a zero. A low-confidence reading **blocks confirmation** until a teacher opens it. | Whether the teacher's review is meaningful in practice is a human question, not a technical one. |
| Handwriting held longer than needed | 400-day window, swept nightly; per-pupil deletion on erasure. | No per-school or per-canton window. Object storage has no versioning, so a delete is final — which is right for erasure and means there is no undo. |
| An unnoticed degradation in grading quality | Override rate, confidence distribution and registration failure rate, computed weekly per school. | No alerting. The numbers are logged, and nothing reads the logs. |
| Loss of a term's work | — | **No backups of anything.** This is the largest single gap. |

---

## 8 · Measures

**Technical, and in place.** Listed so counsel does not have to find them:
row-level security with a separate low-privilege role; a startup validator that
refuses a deployment on any development default; the PII gate; a content-free
model-call audit trail; a read audit trail (`AccessLog`) with a one-year window;
presigned crop URLs valid 120 seconds; CSP with a per-request nonce; HSTS;
Argon2id; a session key ring so rotation is not an outage; scan-image retention
enforced nightly; per-school model-spend caps.

**Organisational.** Not written. Access control within a school, staff
training, the contract with the school, and incident responsibilities are all
outside this repository.

---

## 9 · Residual risk, consultation and sign-off

> **Empty.** Requires the controller.

Whether the FDPIC must be consulted depends on §7's conclusions, which do not
exist yet.
