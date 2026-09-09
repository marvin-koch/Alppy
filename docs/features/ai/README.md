# AI Layer

**Status:** describes `main` as of 2026-09-09
**Audience:** developers, LLM agents, reviewers
**Authority on privacy:** [`docs/privacy.md`](../../privacy.md)

---

## 1 · What it does

Every model call in Alppy goes through one facade, `AiClient`. Four things it does
that scattered call sites would not do consistently:

1. loads prompts from **versioned files**, never inline strings;
2. runs the **PII gate** before anything leaves the process;
3. writes an **audit row** for every call — provider, model, purpose, prompt hash,
   tokens, latency, cost estimate — and never the content;
4. keeps the provider **swappable by configuration**, because a Swiss school may
   require that no data leaves EU/CH infrastructure;
5. accumulates an optional **prompt log** — the content, for debugging — which is a
   different artefact with a different lifetime and is off unless a school asks.

```
  caller (ingest · adaptive · feedback · open-answer grading)
      │  ai.complete(prompt=…, purpose=…, values=…, student_names=roster, images=(crop,))
      ▼
  ai/client.py::AiClient.complete
      ├─ prompt.render(**values)          versioned file, e.g. grade_open_answer.v2.md
      ├─ sha256(system + user + images)   the audit digest
      ├─ assert_no_pii(system); assert_no_pii(user)   ── RAISES, never redacts
      │      │ a rejection is audited like any other failed call
      ▼      ▼
  ai/providers.py  ── OpenAiChatProvider     (grounded=True, the default)
                   ├─ AnthropicChatProvider  (grounded=True)
                   └─ EchoChatProvider       (grounded=False)
      │                    │
      │                    └─ purpose ∈ TRANSCRIPTION_PURPOSES → the empty shape
      ▼
  ChatResponse + CallRecord ──┬─▶ ai/audit.py::record_calls ─────▶ ModelCall  (no content)
                              └─▶ ai/prompt_log.py::record_prompts ▶ PromptLog (content,
                                     only if enabled, and only if the gate passed)
```

Both writes go through one call — `ai/audit.py::flush(db, school_id=…, ai=client)` —
so a call site never grows a second logging concern. It drains, so flushing after every
call and flushing once per job both write each row exactly once.

### Key properties

1. **No student name ever reaches a model provider.** Prompts carry the UID
   (`7B_15`). This is the product's central privacy claim, and `scrub.py` is the gate.
2. **The offline stand-in ships in the repo.** `docker compose up` works on a clean
   machine with no API key, deterministically, so tests and the demo seed reproduce.
3. **An ungrounded provider refuses to transcribe.** It can *author*; it cannot claim
   to have read something — nor claim to have decided something about real children.
4. **Content and audit are separate stores.** `ModelCall` proves a call happened and is
   safe to keep indefinitely; `PromptLog` says what was in it and is off, capped and
   swept. Merging them would make the audit trail the leak it exists to detect.

---

## 2 · Invariants (load-bearing)

| # | Invariant | Enforced in | Why it matters | Failure symptom |
|---|---|---|---|---|
| I-ai-01 | **No student name reaches a provider.** Prompts carry the UID. | `ai/scrub.py::assert_no_pii`, called inside `AiClient.complete` | The product's central privacy claim | A school's roster in a third-party log |
| I-ai-02 | **The gate raises rather than redacting.** | `ai/scrub.py::assert_no_pii` | A leak here is a *caller bug* and must not be papered over | The bug survives, silently, in every future call |
| I-ai-03 | Names are matched against the **actual roster**, never guessed by pattern. | `ai/scrub.py` (`names=`) | Swiss rosters are FR/DE/IT names; pattern-matching would flag "Pythagore" and "Zürich" | Mangled exercise statements, or a false sense of safety |
| I-ai-04 | Content that must be **derived from the prompt** is refused by an ungrounded provider. | `ai/providers.py::TRANSCRIPTION_PURPOSES` (`extract_exercises`, `adaptive_feedback`, `grade_open_answer`, `adaptive_cluster`) | An invented transcription would be attributed to a real page, a real child's thinking, or a real answer | Fiction stored with real provenance |
| I-ai-05 | **Prompts are versioned files**, loaded by name and version. | `ai/client.py::load_prompt`, `ai/prompts/*.vN.md` | A prompt change must be attributable in the audit trail | Nobody can tell which prompt produced a stored result |
| I-ai-06 | The audit row stores **provider, model, purpose, prompt hash, tokens, latency, cost — never content and never a name**. | `ai/client.py::CallRecord`, `ai/audit.py::record_calls` | The row is safe to keep as long as a school wants it | The audit log becomes the leak it exists to detect |
| I-ai-07 | A **blocked or failed call is still audited**, then re-raised. | `AiClient.complete` (the gate is inside the `try`) | A silent gate is an unfalsifiable one | No evidence the gate ever fired |
| I-ai-08 | `record_calls` **never raises**. | `ai/audit.py::record_calls` | An audit row that cannot be written must not fail the ingestion that produced it | A whole textbook import lost to a logging failure |
| I-ai-09 | The **prompt log is off by default, capped, swept, and never holds a blocked prompt's content**. `ModelCall` gains no content column. | `ai/prompt_log.py`, `AiClient._transcribe`, `core/config.py` | Content and audit are different artefacts with different lifetimes. The moment prompt text lives in the audit table, that table is the leak it exists to detect | The debugging aid becomes the leak, or a roster name is written down by the very code that refused to send it |

---

## 3 · Module map

| Path | Owns | Depends on |
|---|---|---|
| `alppy/ai/base.py` | `ChatRequest`/`ChatResponse`/`ImagePart`, the `ChatProvider` and `EmbeddingsProvider` protocols, the `grounded` flag | nothing |
| `alppy/ai/scrub.py` | `StudentRef`, `to_ref`, `scrub`, `assert_no_pii`, `PiiLeakError` | `core.uid` |
| `alppy/ai/client.py` | `AiClient.complete`, `AiClient.embed`, `load_prompt`, `parse_json_response`, `CallRecord`, cost estimation | `base`, `providers`, `scrub`, `config` |
| `alppy/ai/providers.py` | `OpenAiChatProvider` (grounded, **the default** — ADR 0002), `AnthropicChatProvider` (grounded), `EchoChatProvider` + `HashEmbeddingsProvider` (offline, deterministic), `TRANSCRIPTION_PURPOSES` | `base`, `config` |
| `alppy/ai/prompt_log.py` | `record_prompts`, `purge_expired_prompts` → `PromptLog`. **Deliberately not in `audit.py`**, whose whole point is that it stores no content | `client.PromptTranscript`, `models` |
| `alppy/ai/audit.py` | `record_calls` → `ModelCall` | `client.CallRecord`, `models` |
| `alppy/ai/prompts/` | `extract_exercises.v1/v2`, `generate_exercises.v1`, `generate_exercises_batch.v1`, `cluster_students.v1`, `generate_feedback.v1`, `grade_open_answer.v1/v2` | — |

---

## 4 · How to extend this feature

**Adding a purpose.** Ask one question first: *would an invented answer be attributed
to something real?* If yes, the purpose belongs in `TRANSCRIPTION_PURPOSES` and the
offline provider must return the empty shape for it. `extract_exercises` (a real page
of a teacher's book), `adaptive_feedback` (how a named child thinks),
`grade_open_answer` (a verdict on a real answer) and `adaptive_cluster` (which children
belong together) are all in that set.

`adaptive_cluster` is the subtle one and worth stating: an invented *exercise* is a bad
question a teacher reads and rejects, but an invented *partition* takes effect without
anyone reading it. The empty answer sends the caller back to the deterministic rule,
which is both honest and correct — so the offline path produces a real partition, not a
degraded one.

`adaptive_generate` and `adaptive_generate_batch` stay out of the set: authoring is not
transcription, and a made-up practice question is honestly labelled and gated behind
approval.

**Adding a provider.** Implement `ChatProvider`, set `grounded` honestly, and register
it in `build_chat_provider`. `grounded` is not a capability flag — it is a claim about
whether the output is derived from the input.

**Changing a prompt.** Bump the version and add a file. Do not edit a shipped version:
stored results reference it.

### LLM checklist

- [ ] Read §2 — these are not suggestions
- [ ] Does the new call pass `student_names=` the real roster? (I-ai-01/03)
- [ ] Does anything catch `PiiLeakError` and continue? (I-ai-02 — never)
- [ ] Is the prompt a file with a version, or a string in the code? (I-ai-05)
- [ ] Could an ungrounded provider's answer be stored as if it were read? (I-ai-04)
- [ ] Does any new audit field carry content or a name? (I-ai-06 — never)
- [ ] Is prompt content being written on a path the gate did not clear? (I-ai-09 — never)
- [ ] Does a new provider drop a `temperature` a prompt's own front matter requires?

---

## 5 · Privacy & safety

| Data | Scrubbing point | Why |
|---|---|---|
| Student name | `assert_no_pii` on the rendered system and user text, with the class roster | Exact matching against the real roster; no guessing (I-ai-03) |
| Email, phone, AHV number | Regex, redacted by `scrub`, refused by `assert_no_pii` | Structured PII that *can* be matched by pattern safely |
| Textbook prose containing a pupil's name | `scrub`-ed **on the way in**, then the gate stays armed | Swiss textbook prose is full of Léa, Noah and Emma — who are also in the class |
| An image crop | **Geometry, not inspection.** The gate reads text only | A crop is cut from the statement region only (`I-scanning-07`) |
| Prompt content | Never stored. The audit row keeps a sha256 | The row must be safe to keep indefinitely |

Two defences, deliberately:

- `build_safe_prompt` / structured values — there is no name field to fill in.
- `assert_no_pii` — belt and braces on the final string, so a future caller who
  assembles a prompt by hand still cannot leak a roster.

The image hash is folded into the audit digest: the same crop with the same prompt is
the same call, and a different crop is a different one.

---

## 6 · Testing strategy

| Invariant | Proved by |
|---|---|
| I-ai-01 | `test_adaptive.py::test_no_roster_name_appears_in_a_generation_prompt`, `::test_generation_meta_records_the_uid_never_the_name` |
| I-ai-02 | `test_adaptive.py::test_the_armed_gate_would_actually_fire`, `test_adaptive_fixes.py::test_the_pii_gate_still_fires_on_a_name_the_scrub_did_not_see` |
| I-ai-03 | `test_adaptive_fixes.py::test_a_roster_name_in_a_textbook_statement_does_not_kill_generation`, `test_adaptive.py::test_the_pii_gate_is_armed_with_the_real_roster` |
| I-ai-04 | `test_ingest_grounding.py::test_the_offline_provider_returns_nothing_for_grounded_purposes`, `::test_the_offline_provider_still_generates_when_asked_to_author`, `test_ai_vision.py::test_the_offline_provider_never_invents_a_verdict` |
| I-ai-05 | `test_ai_vision.py::test_the_grading_prompt_names_every_input`, `::test_the_v2_grading_prompt_carries_the_reference_block` |
| I-ai-06 | `test_ingest_grounding.py::test_model_calls_are_recorded_without_any_content`, `test_ai_vision.py::test_the_client_hashes_the_image_into_the_audit_record` |
| I-ai-07 | `test_adaptive_fixes.py::test_a_blocked_prompt_is_written_to_the_audit_log`, `::test_the_client_records_a_failed_call_before_re_raising` |
| I-ai-08 | `test_adaptive.py::test_a_shared_client_keeps_one_audit_trail`, `test_prompt_log.py::test_a_prompt_log_failure_never_fails_the_call_that_produced_it` |
| I-ai-09 | `test_prompt_log.py` (whole file — 11 tests), in particular `::test_nothing_is_logged_until_a_school_turns_it_on`, `::test_a_prompt_blocked_by_the_gate_is_never_written_to_the_prompt_log`, `::test_an_expired_row_is_swept_and_a_fresh_one_is_left_alone` |
| ADR 0002 | `test_ai_providers.py` (whole file — 18 tests): the Responses translation, the temperature contract, the provider/model pair check, and the loud keyless fallback |

```bash
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests/test_ai_vision.py \
  apps/api/tests/test_ingest_grounding.py apps/api/tests/test_adaptive.py \
  apps/api/tests/test_adaptive_fixes.py apps/api/tests/test_ai_providers.py \
  apps/api/tests/test_prompt_log.py -q
```

The whole suite runs on the offline providers. That is not a compromise — it is what
lets CI exercise every AI path, deterministically, with no key and no network.

---

## Companion documents

- [`architecture.md`](architecture.md) — the call path, the providers, the audit row
- [`decisions.md`](decisions.md) — D8, D9, D10, and the grounding rule
- [`../../privacy.md`](../../privacy.md) — the authority

**Last updated:** 2026-09-09
