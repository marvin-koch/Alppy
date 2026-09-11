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

### Images: the one payload the text gate cannot read

The vision grader (F2, written answers) sends a model an **image**: the inside of one answer
box, cut from the registered scan page. `scrub.py` reads strings and cannot inspect pixels, so
the guarantee for images is made by geometry rather than by inspection:

- A box is cropped at the rectangle the renderer *measured* for that copy and page
  (`AnswerBoxPlacement`), and the renderer refuses to record a box outside the statement region
  (`layout.ITEMS_TOP_MM..ITEMS_BOTTOM_MM`). The header, the student code and the UID grid sit
  above that region, so a crop cannot carry them.
- The printed sheet carries no student name anywhere — only the UID — so nothing Alppy printed
  can leak a roster through a crop.
- The text half of the request (question, expected answer, the fill the box carried) still goes
  through `assert_no_pii` like every other prompt.
- The residual risk is a student writing their own name inside the box. It is not guarded
  against, because there is no roster to match pixels against; it is recorded here rather than
  left implicit. The prompt instructs the model never to infer or invent a name.
- The crop is stored beside the scan page image and shares its retention (§4). The audit row
  (`ModelCall`) hashes the image into the prompt hash and stores neither.

### What is explicitly *not* restricted this way

Textbook/curriculum content indexed for RAG (source PDFs, chunks, competency text) is not student
data and is not subject to this scrubbing path — see `docs/adr/0001-embeddings-provider.md` for why
that content has a different, less strict, data-residency treatment (self-hosted embeddings model,
no vendor call at all, for a different reason: content-licensing caution per
`docs/research/textbook-access-ch.md`, not a PII concern).

## 3. Provider configuration and data residency

- The LLM provider is **configurable**, not hard-coded, specifically so a school or canton can
  require an EU/CH-hosted option. **OpenAI is the default for generation** (ADR 0002, which
  supersedes the earlier Anthropic default); Anthropic remains selectable, and both are chosen by
  one setting, `ALPPY_AI_CHAT_PROVIDER`. The `alppy/ai/` interface is provider-agnostic by
  construction (a `ChatProvider` protocol with swappable backends) so a Mistral (EU, Paris) or a
  self-hosted EU/CH-region deployment can be substituted without touching call sites.
- **The image path is a transfer too, and of the most sensitive payload here.** §2 is written
  about prompts, and the residency question is easy to read as being about text. It is not: the
  vision grader sends a **photograph of one child's handwriting** to the configured provider on
  every written answer, and the default provider is OpenAI, in the United States. The PII gate
  cannot inspect it — it reads text — so what keeps a name out of that image is geometry
  (`measure_answer_boxes` refuses a box outside the statement region), not inspection. Under GDPR
  and the revised Swiss FADP this is a transfer of personal data to a third country, and
  handwriting on a school assessment is plausibly special-category data.
  **This is an open decision, recorded here rather than settled** (2026-09-10): the product
  continues to send crops to the configured provider, and whether that provider must be CH/EU is
  to be answered before any pilot with a real class. The two exits already exist —
  `ALPPY_AI_CHAT_PROVIDER` selects the provider, and a regional or self-hosted vision model
  substitutes without touching call sites.
- **No processor agreement exists with either vendor yet** (§7 lists this among the things a real
  deployment needs before it holds a real class). A school that requires EU/CH residency today
  should set `ALPPY_AI_CHAT_PROVIDER=echo` or point the setting at an in-region deployment; the
  offline provider is a complete, deterministic stand-in, not a stub, and the product runs on it.
- **A provider whose own key is absent falls back to the offline provider and says so**
  (`ai.provider.no_key`). This matters operationally now that there is more than one real vendor:
  a deployment holding the *other* provider's key is silently offline, and everything it
  "generates" is derived from a hash. The log line is how that is noticed.
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

### The prompt log — content, and therefore a different thing entirely

`PromptLog` (`alppy/ai/prompt_log.py`) stores what `ModelCall` deliberately does not: the rendered
system and user text and the provider's raw answer. It exists because "which calls happened" and
"what did we actually send" are different questions, and an engineer debugging a bad sheet needs
the second one. It is **not** an extension of the audit trail and must never be described as one —
the moment content lives in the audit table, the audit table is the leak it exists to detect.

Four properties make it defensible, and all four are enforced in code:

| Property | Where |
|---|---|
| **Off unless a school turns it on.** `ALPPY_AI_PROMPT_LOG_ENABLED` defaults to false; an upgrading deployment gains an empty table and no new data flow. | `core/config.py`, `AiClient._transcribe` |
| **Content is written only after the PII gate passed.** A prompt that fired `PiiLeakError` is by definition the one carrying a roster name; that row records the refusal, the provider, the purpose and the hash — and no content at all. | `AiClient.complete` |
| **Rows expire.** `ALPPY_AI_PROMPT_LOG_RETENTION_DAYS` (default 30) plus `python -m alppy.cli purge-prompt-logs`. A retention window nothing enforces is no window. | `prompt_log.purge_expired_prompts` |
| **Fields are capped.** `ALPPY_AI_PROMPT_LOG_MAX_CHARS`, and a truncated value says so rather than reading as the thing that was sent. An extraction prompt carries a whole textbook chunk. | `AiClient._transcribe` |

**Passing the PII gate is not the same as holding no student data.** The gate refuses names,
e-mail, Swiss phone numbers and AHV numbers; it does not and cannot refuse a UID, a wrong answer,
or a description of a misconception — and a UID plus a class roster re-identifies. That is why this
table is school-scoped (so a tenant deletion takes it), swept by default, and off by default. It
is a debugging aid a school opts into, not a record it is asked to keep.

## 4. Data export and deletion; retention of scans

- **Export.** `GET /api/v1/classes/{id}/export` returns the whole class as one JSON document —
  every pupil currently enrolled, each with their enrolments across every year, their attempts and
  their misconception notes. `GET /api/v1/students/{id}/export` does the same for one pupil. This is
  the mechanism a school uses to take its data with it, and the mechanism used to satisfy a
  data-portability request.

  Two limits, stated rather than left to be discovered. The class document covers the roster **as
  it stands**: a pupil who has left is exported individually, under the access rule that governs
  them (a teacher who arrived in March has no standing over a pupil who left in October). And the
  document is JSON only — the **PDF and image assets are not included**, so a school taking its
  data also needs the object store, which today means asking. Mastery snapshots are deliberately
  absent: they are recomputed from the attempts, and a decaying score is a photograph of a
  calculation rather than an independent fact about a child.
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

  **What actually happens today (2026-09-11): 400 days, swept nightly.**
  `ALPPY_SCAN_IMAGE_RETENTION_DAYS` defaults to **400 — a school year plus one term** — and
  `alppy/worker/cron.py` runs `purge-scan-images` at 03:30 every night. Both halves are new and
  neither works without the other: the window used to default to 0 (keep forever), and even a
  window that was set would have been enforced by nobody, because there was no scheduler
  anywhere in the repository (audit 07, D2/D3).

  The old default of 0 was right for as long as the alternative was "a number a developer
  invented", which would have destroyed the evidence behind a contested mark the week before a
  parent asked about it. It stopped being right once the real alternative was an unbounded,
  permanently growing store of photographs of named children's handwriting. 400 days is a
  starting position chosen so a mark given in June is still appealable against the page the
  following spring; a school that states a shorter one is making the easier argument, not the
  harder, and sets the variable.

  **Still not supported: a per-school or per-canton window.** This is one number for the
  deployment. Making it vary is a column on `School` read per pile by the purge, and it is
  flagged rather than built. Until then, a canton demanding a shorter window than 400 days is
  served by setting the deployment's number to theirs.

  `delete_student` still removes a pupil's page images and crops immediately as part of erasure,
  independently of this window.

  When a window is set, a purge takes the crops first and the page images second, and takes
  neither from a pile still in review. The grade, the transcription and the verdict live on
  `Detection` and are never touched; what is lost is the ability to look at the paper again.

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
| `Scan` / `ScanPage` (image) | Yes (handwriting, potentially name if visible on the page) | S3-compatible storage | **Kept indefinitely today** — bounded window (see §4) once one is configured | Teacher(s) of the class; Alppy ops during active job processing only |
| `Detection.crop_key` (the answer box, cut) | Handwriting; a name only if the student wrote one inside the box | S3-compatible storage, beside the page image | Same window as the page image (so: indefinitely, today) | Teacher(s) of the class; **transferred to the configured vision provider — OpenAI, US, by default — during the grading call (see §3)** |
| `Detection` | Indirect (tied to a scan/student) | Postgres | Tied to parent scan | Teacher(s) of the class |
| `Attempt` | Indirect (student UID + competency + score, no name) | Postgres | Retained for mastery history beyond scan deletion | Teacher(s) of the class |
| `MasterySnapshot` | Indirect (student UID) | Postgres | Retained per-class history | Teacher(s) of the class; the student's later teachers on class handover |
| `ModelCall` (audit log) | No (see §3 — explicitly content-free) | Postgres | Operational retention (e.g. 90 days), separate from student data lifecycle | Alppy ops; school admin on request |
| `PromptLog` (prompt/response content) | Indirectly: UIDs, answers, competency text — never a name, never an e-mail (§3) | Postgres | **Off by default**; 30 days when enabled, swept by `alppy.cli purge-prompt-logs` | Alppy ops, with the school's consent to enable it |
| `AdaptiveProposal` (a built proposal awaiting review) | Indirectly: UIDs and exercise text; no names | Postgres | Cascades with the `Job` that produced it | Teacher(s) of the class |

"Indirect" PII means the row carries a student UID or class/sheet linkage that is only personally
identifying when joined against `Student`; access control (tenancy, §below) governs who can make
that join.

**Tenancy as an access control, not just a partition key.** Every row above carries `school_id`
(see `docs/architecture.md` §Tenancy); every read path filters on it. This is the mechanism that
answers "who can access" in practice — a teacher's session is scoped to their school, and
cross-school access has no code path, not just a permissions check that could be forgotten on one
endpoint.

## 6. Explicitly out of scope for the MVP

**Update, 2026-09-11.** Three of the items below now have a real, current
starting document in [`data-protection/`](data-protection/), and one of the
list's premises has changed:

* [`data-protection/subprocessors.md`](data-protection/subprocessors.md) — the
  subprocessor register, with residency and transfer positions. **Complete and
  maintained**; update it in the same change that changes a vendor.
* [`data-protection/dpia-outline.md`](data-protection/dpia-outline.md) — the
  DPIA's structure, with the factual sections filled in from the code and the
  risk assessment and legal conclusions deliberately empty.
* [`data-protection/breach-procedure.md`](data-protection/breach-procedure.md) —
  the order of operations, with every name and timeline left blank.

The DPA, the processing register and the parental notice are **not** drafted,
and deliberately: they carry legal weight, and a plausible-looking draft is
worse than an empty section because it gets signed.

The premise that changed: **in the shipped configuration no personal data
leaves the deployment.** The default AI provider is offline (`echo`), so the
transfers that most of the list below is about are not currently happening.
Written answers are counted as skipped rather than graded; nothing else is
affected. That makes "no transfer until the paperwork exists" a position that
can be held while the paperwork is done.

The following are still necessary before Alppy processes real, non-demo student
data at any school:

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

The operational half — deploy, rollback, restore, secret rotation, worker drain,
a stuck batch, and a pre-launch checklist for a new establishment — is in
[`runbook/`](runbook/). Read [`runbook/restore-from-backup.md`](runbook/restore-from-backup.md)
before accepting any pilot: **there are still no backups of anything**, so a
volume loss is total and permanent loss of a term of graded work. That is the
largest remaining gap and it is not a paperwork one.
