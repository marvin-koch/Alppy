# Privacy and data protection

Engineering documentation, not legal advice. It describes how the architecture is built to satisfy
the Swiss Federal Act on Data Protection as revised (revDSG / nLPD, in force since 1 September
2023) and to keep student data away from third-party model providers. It does not replace a data
protection impact assessment (DPIA) or a lawyer's review before Alppy processes real students'
data.

## 1. Why this is sensitive

Students in Sek I / cycle 3 are **minors** (roughly ages 10–16). Their school performance data
(exercise attempts, correctness, per-competency mastery) is data about a minor's abilities and
progress, tied to their identity. Under revDSG this is personal data requiring particular care even
though it does not fall in the narrower list of "besonders schützenswerte Personendaten" the way
health or religious data would — but "particular care" is the operating assumption for this
project regardless of exact statutory classification, because the data subjects cannot consent for
themselves and a school's duty of care extends to how it is processed.

**Legal basis.** For the MVP (demo data, pilot schools), processing rests on the school's
educational mandate and the contract between the school and Alppy, not on student/parental consent
collected per-record — consent from minors is not a reliable legal basis at scale. Before any
deployment on real students' data, the school (as controller) needs its own basis confirmed
(cantonal school law generally already permits processing of pupil data necessary for teaching and
assessment; Alppy is a processor acting on the school's instructions) — this determination belongs
to the school's data protection officer, not to Alppy's engineering team, but Alppy's design must
not foreclose it.

**Data minimisation and purpose limitation**, concretely:
- Only what mastery tracking and adaptive generation need is collected: attempts, scores, timing,
  and the identifiers required to attribute them. No demographic, health, or family data.
- Student first/last names exist only to let a teacher read a roster and a printed sheet; they are
  never sent to any model and never appear in AI-facing logs (§2).
- Scans are images of paper answer sheets; nothing beyond the sheet's own content is captured.

## 2. No student PII reaches a third-party LLM

This is a hard architectural invariant, not a policy statement. It is enforced at one chokepoint.

### The enforcement point

All calls to a generative or embedding model go through `apps/api/alppy/ai/`. That package is the
**only** code in the repository permitted to construct a request to an external model provider.
Every other module (mastery, sheets, scan, ingest) that needs a model call goes through it — there
is no second path to an LLM API.

Inside `apps/api/alppy/ai/`:

- A **scrubbing layer** (`alppy/ai/scrub.py` — name normative for this doc) sits between any
  caller and the outbound request builder. It accepts only a fixed, typed payload shape (e.g.
  `GenerationRequest`, `EmbeddingRequest`) that has no field for a student's name, and it actively
  rejects (not just ignores) any payload that contains free text pulled from a `Student` or
  `Teacher` row without having first passed through the identifier substitution below.
- Students and teachers are addressed to the model layer **only by their UID** (`7B_15` — class
  code + student index) or a similarly opaque teacher/class identifier. The mapping from UID to
  real name lives only in Postgres and is resolved back **after** a model response returns, for
  rendering in the UI or on a printed sheet — never before or during a model call.
- Free-text fields that could carry PII incidentally (e.g. a teacher's custom exercise intent, a
  chapter title they typed) are passed through a redaction check (name-list match against the
  class roster + a conservative PII pattern check) before leaving the scrubbing layer; a match
  blocks the call rather than silently stripping it, because silent stripping can corrupt the
  prompt's meaning without the caller noticing.
- The scrubbing layer is the **only** place that holds the provider client/API key. No other
  module can reach the network path to a model provider even if it wanted to — this is enforced by
  not exposing the HTTP client or credentials outside `alppy/ai/`.

### The test that asserts it

`apps/api/tests/ai/test_scrub_no_pii.py` (name normative for this doc) is the enforcement test:

- It constructs realistic requests using real student/teacher fixture data (names, not UIDs) as
  callers naturally would, and asserts that the **serialized outbound payload** — the exact bytes
  that would go over the wire to the provider — never contains any fixture name, e-mail, or other
  direct identifier as a substring.
- It is parametrised over every call site currently wired into `alppy/ai/` (sheet generation,
  adaptive generation, embeddings) so a new call site must be added to the parametrisation to pass
  CI — a call site that bypasses the scrubbing layer entirely (imports the provider client
  directly) is caught separately by a lint/import-boundary rule restricting who may import the
  provider SDKs.
- This test is part of the default CI run, not an optional/slow suite — a regression here is a
  release blocker, not a follow-up ticket.

### What is explicitly *not* restricted this way

Textbook/curriculum content indexed for RAG (source PDFs, chunks, competency text) is not student
data and is not subject to this scrubbing path — see `docs/adr/0001-embeddings-provider.md` for why
that content has a different, less strict, data-residency treatment (self-hosted embeddings model,
no vendor call at all, for a different reason: content-licensing caution per
`docs/research/textbook-access-ch.md`, not a PII concern).

## 3. Provider configuration and data residency

- The LLM provider is **configurable**, not hard-coded, specifically so a school or canton can
  require an EU/CH-hosted option. Anthropic is the default for generation (see the plan), but the
  `alppy/ai/` interface is provider-agnostic by construction (a `ModelProvider` protocol with
  swappable backends) so a Mistral (EU, Paris) or a self-hosted EU/CH-region deployment can be
  substituted without touching call sites.
- Embeddings are planned to be **self-hosted** (see ADR 0001) precisely so textbook-chunk data
  never has to leave infrastructure Alppy controls, sidestepping the residency question for that
  data class entirely.
- Object storage (scans, rendered PDFs, source PDFs) is S3-compatible and is deployed in an
  EU/CH region in any real deployment; MinIO locally for development only holds synthetic/demo
  data.
- Database (Postgres) is likewise deployed in-region for any real deployment; local development
  uses the same schema against synthetic data.

### Audit log of every model call

Every call through `alppy/ai/` writes one `ModelCall` row (already in the domain model, see
`docs/plan.md` §3):

| Field | Purpose |
|---|---|
| `provider`, `model` | which vendor/model served the call — needed for cost/latency accounting and for proving which calls were, or were not, sent to a given jurisdiction |
| `prompt_hash` | a one-way hash of the prompt actually sent, so a specific call can be identified/reproduced/investigated without storing its content |
| `input_tokens`, `output_tokens` | cost and quota accounting |
| `latency_ms` | operational monitoring |
| `cost` | budget accounting |
| `school_id`, `caller` (module/route) | attributes the call to a tenant and a feature, for audit and for tenancy isolation checks |

**`ModelCall` never stores prompt or completion content, with or without PII.** The hash exists so
an engineer investigating an incident can correlate a suspect call with server-side request logs
retained for a short, separately-governed window (out of scope for the MVP — see §6) without the
audit table itself becoming a second place PII could leak into. This table is the artifact a school
or auditor is shown to answer "did any of our data go to provider X" without Alppy needing to
expose actual prompts.

## 4. Data export and deletion; retention of scans

- **Export.** A school (via its admin/teacher account) can request a full export of one class:
  roster, sheets, scans, attempts, mastery snapshots, in a documented machine-readable format
  (JSON + the original PDF/image assets). This is the mechanism a school uses to take its data with
  it, and the mechanism used to satisfy a data-portability request.
- **Deletion.** Deleting a class cascades to its students, sheets, sheet instances, scans, scan
  pages, detections, attempts, and mastery snapshots for that class. Deletion is hard delete for
  personal data (not a soft `deleted_at` flag left queryable) once any legal/contractual retention
  window has passed; aggregate, de-identified statistics (e.g. "how many MCQ items were graded
  platform-wide") may be retained without the identifying rows behind them.
- **Scan retention.** Raw scan images are the most sensitive artifact (a photograph of a named
  child's handwriting and answers). Default retention: scans are kept only as long as needed for
  the teacher to review/correct detections and for the resulting attempts to be recomputed into
  mastery — a bounded default window (e.g. end of term) after which the image is deleted while the
  derived, de-identified `Attempt` rows (score, correctness, competency, UID — not the image) are
  retained for the mastery history. The exact default window is a product decision to be set
  before any real deployment, not fixed by this document; it must be configurable per school
  because retention expectations vary by canton.

## 5. Data inventory

| Entity | Contains PII? | Where stored | Retention (MVP default) | Who can access |
|---|---|---|---|---|
| `Teacher` | Yes (name, login, preferences) | Postgres | Life of account | Self; school admin; Alppy ops (support only) |
| `Student` | Yes (name, UID, class) | Postgres | Life of enrollment + export/delete on class deletion | Teacher(s) of that class; school admin |
| `Class` / `School` / `SchoolYear` | No (metadata only) | Postgres | Life of tenant | Teachers/admins of that school |
| `Source` (uploaded textbook PDF) | Usually no (publisher content, not personal); may incidentally contain a teacher's own annotations | Postgres (metadata) + S3-compatible storage (file) | Life of tenant, teacher-deletable | Uploading teacher; co-teachers with class access |
| `SourceChunk` (text + embedding) | No | Postgres (`pgvector`) | Tied to parent `Source` | Same as `Source` |
| `Exercise` / `ExerciseVariant` | No (may reference a student UID for a variant, not a name) | Postgres | Tied to parent sheet/source | Teacher(s) of the class |
| `Sheet` / `SheetItem` / `SheetInstance` | Indirect (SheetInstance binds to a student UID) | Postgres | Tied to class; export/delete with class | Teacher(s) of the class |
| `Scan` / `ScanPage` (image) | Yes (handwriting, potentially name if visible on the page) | S3-compatible storage | Bounded window (see §4), then deleted | Teacher(s) of the class; Alppy ops during active job processing only |
| `Detection` | Indirect (tied to a scan/student) | Postgres | Tied to parent scan | Teacher(s) of the class |
| `Attempt` | Indirect (student UID + competency + score, no name) | Postgres | Retained for mastery history beyond scan deletion | Teacher(s) of the class |
| `MasterySnapshot` | Indirect (student UID) | Postgres | Retained per-class history | Teacher(s) of the class; the student's later teachers on class handover |
| `ModelCall` (audit log) | No (see §3 — explicitly content-free) | Postgres | Operational retention (e.g. 90 days), separate from student data lifecycle | Alppy ops; school admin on request |

"Indirect" PII means the row carries a student UID or class/sheet linkage that is only personally
identifying when joined against `Student`; access control (tenancy, §below) governs who can make
that join.

**Tenancy as an access control, not just a partition key.** Every row above carries `school_id`
(see `docs/architecture.md` §Tenancy); every read path filters on it. This is the mechanism that
answers "who can access" in practice — a teacher's session is scoped to their school, and
cross-school access has no code path, not just a permissions check that could be forgotten on one
endpoint.

## 6. Explicitly out of scope for the MVP

The following are necessary before Alppy processes real, non-demo student data at any school, and
are deliberately not solved yet:

- **DPIA** (Datenschutz-Folgenabschätzung) — a full assessment is a prerequisite for real rollout,
  not a nice-to-have; this document is an input to that assessment, not a substitute for it.
- **Processor agreements (Auftragsdatenverarbeitungsvertrag / ADV)** with the school as controller
  and Alppy as processor, and back-to-back agreements with any subprocessor (LLM provider, cloud
  hosting) — none exist yet; the provider-agnostic design in §3 exists specifically so this is
  possible once agreements are in place, not because it has already been done.
- **Breach notification process** — revDSG requires notifying the FDPIC (and, in some cases, data
  subjects) "as soon as possible" after a data security breach likely to result in a high risk;
  the MVP has no defined incident response runbook, escalation contacts, or notification templates
  yet.
- **Subprocessor list and vendor due diligence** — no formal register of subprocessors (cloud
  provider, model provider, error-tracking/observability tooling) with their own data-processing
  terms reviewed.
- **Retention windows as a signed-off product/legal decision** — §4 states sensible defaults;
  nobody with legal authority over a real deployment has approved them yet.
- **Parental notice/rights process** — a concrete, canton-compliant way for parents to be informed
  and to exercise access/deletion rights on behalf of a minor is not designed.

Until these exist, Alppy should run only on synthetic/demo data and opt-in pilot data that the pilot
school has explicitly accepted the current state of this document for.
