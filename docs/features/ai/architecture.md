# AI Layer Architecture

## Component diagram

```
  ingest/pipeline.py        adaptive_service.py       feedback_service.py
  extract_exercises         generate_exercises        generate_feedback
        │                          │                         │
        └──────────────┬───────────┴────────────┬────────────┘
                       │                        │
                       │        services/open_answer_grading.py
                       │        grade_open_answer  (+ ImagePart)
                       ▼                        ▼
          ┌──────────────── ai/client.py::AiClient ────────────────┐
          │  load_prompt(name, version) → Prompt (a versioned .md) │
          │  prompt.render(**values) → (system, user)              │
          │  digest = sha256(system + user + sha256(each image))   │
          │  ┌── try ─────────────────────────────────────────┐    │
          │  │  assert_no_pii(system, names=roster)           │    │
          │  │  assert_no_pii(user,   names=roster)  ← RAISES │    │
          │  │  provider.complete(ChatRequest(...))           │    │
          │  └── except → CallRecord(ok=False, error) and RE-RAISE │
          │  CallRecord(provider, model, purpose, prompt name +    │
          │             version + sha256, tokens, latency, cost)   │
          └───────────────────────┬───────────────────────────────┘
                                  │
        ┌─────────────────────────┴──────────────────────────┐
        ▼                                                    ▼
  AnthropicChatProvider (grounded=True)        EchoChatProvider (grounded=False)
        │                                       purpose ∈ TRANSCRIPTION_PURPOSES
        │                                          → the empty shape, no invention
        ▼                                       else → a deterministic authored answer
  ChatResponse
        │
        ▼
  ai/audit.py::record_calls(db, school_id, records) → ModelCall   (never raises)
```

## Data flow

### The call

```python
response, record = ai.complete(
    prompt=load_prompt("grade_open_answer", "v2"),
    purpose="grade_open_answer",
    values={"language": ..., "statement": ..., "reference": ..., "fill": ...},
    student_names=roster,          # the gate is armed with the REAL roster
    images=(ImagePart(png_bytes),),
    temperature=0.0,
)
```

`values` is structured. There is no name field to fill in, which is the first of the
two defences; `assert_no_pii` over the rendered strings is the second.

### `ImagePart` — bytes, not a URL

```python
@dataclass(frozen=True, slots=True)
class ImagePart:
    data: bytes
    media_type: str = "image/png"
```

The crop never leaves the process by any other route, and a provider that cannot look
at pixels simply ignores it. **The text gate cannot inspect these**; what keeps a name
out of them is geometry — a crop is cut from the statement region only.

### The audit row

```python
@dataclass(frozen=True)
class CallRecord:
    provider: str; model: str; purpose: str
    prompt_name: str; prompt_version: str; prompt_sha256: str
    input_tokens: int | None; output_tokens: int | None
    latency_ms: int; cost_estimate_chf: float | None
    ok: bool; error: str | None
```

Read the list for what is missing: no prompt text, no response text, no student, no
class. That is what makes the table safe to keep for as long as a school wants it —
and therefore what makes it an audit trail at all.

## Component interaction

### `scrub.py` — the gate

- `scrub(text, names=...)` **redacts**: emails, Swiss phone numbers, AHV numbers, and
  every roster name, longest first, case-insensitively.
- `assert_no_pii(text, names=...)` **raises** `PiiLeakError`.

Both take the class roster because pattern-guessing at names is not safe here: Swiss
school rosters are FR/DE/IT names, and "a capitalised word" would flag half the
mathematics vocabulary — Pythagore, Zürich, Thalès.

The two are used together in the generation paths: textbook prose is *scrubbed on the
way in* (it may legitimately name a pupil who is also in this class), and the
assertion stays armed as the proof. Asserting alone meant a corpus that happened to
name a pupil silently killed generation for that student.

### `providers.py` — grounded vs authored

`grounded` is a claim about whether the output derives from the input. The echo
provider's text is a deterministic function of a hash, so it is `False`.

`TRANSCRIPTION_PURPOSES = {extract_exercises, adaptive_feedback, grade_open_answer}`,
in increasing order of severity:

- **`extract_exercises`** — an invented exercise would be stored with a real page's
  provenance.
- **`adaptive_feedback`** — an invented misconception is a claim about how one named
  child thinks, printed and handed to that child.
- **`grade_open_answer`** — a stand-in that cannot see the image, answering anyway,
  would be a verdict on a real student drawn from a hash.

For those, the offline provider returns the **empty shape** and the caller records "no
verdict" / "no note" / "no exercises". It still *authors* when asked to author
(`generate_exercises`), because a made-up practice question is honestly labelled as
generated and gated behind approval.

### Cost estimation

Rough public list prices per million tokens, used **only** for the audit estimate,
never for billing.

## Edge cases

- **The gate fires.** → `PiiLeakError` propagates, and a `CallRecord(ok=False)` is
  written first. The gate is inside the `try` on purpose: a silent gate is an
  unfalsifiable one, and a blocked prompt is exactly the event an audit trail exists
  to record.
- **The provider throws.** → audited as a failure, then re-raised. Callers decide
  whether that shortens a sheet or fails a job; the client does not swallow it.
- **The audit write fails.** → logged, returns 0, **never raises**. Losing a log line
  must not lose a textbook import.
- **A response that is not JSON.** → `parse_json_response` raises; the caller reports
  it rather than writing a partially-understood row.
- **No API key at all.** → `build_chat_provider` returns the echo provider. Everything
  runs; everything grounded refuses honestly.
- **Two callers, one client.** → `AiClient.records` accumulates, so one job writes one
  audit trail rather than one per call site.

---

**Companion:** [`README.md`](README.md) §2 for the load-bearing rules.
