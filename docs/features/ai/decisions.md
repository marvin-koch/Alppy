# AI Layer Decisions Log

D-numbers follow the repo-wide [`docs/decisions-log.md`](../../decisions-log.md).

---

## D8 · Offline `echo` and `hash` AI providers ship in the repo

**Date:** M1 · **Affected invariants:** I-ai-04, and the whole test strategy

**Background.** `docker compose up` must work on a clean machine with no API key —
that is in the definition of done — and CI must exercise every AI path.

**Considered alternatives**
- A) *Mock the client in tests only.* Rejected: the demo would be broken on a clean
  machine, and mocks drift from the real interface.
- B) *Require a key.* Rejected: it makes the product undemonstrable and CI expensive.
- C) **Ship a deterministic `EchoChatProvider` and `HashEmbeddingsProvider` as real
  providers.** Chosen.

**Tradeoff**
- ✅ The whole product runs, reproducibly, offline
- ✅ Tests and the demo seed are deterministic
- ❌ A second implementation of every response shape to keep honest
- ❌ A stand-in that answers *anything* would be worse than none — which is why D-grounding
  below exists

Real embeddings choice: [ADR 0001](../../adr/0001-embeddings-provider.md).

---

## D9 · The PII gate raises instead of redacting

**Date:** M1 · **Affected invariants:** I-ai-02, I-ai-07

**Background.** `scrub()` can quietly remove a name. `assert_no_pii()` refuses to send.
Both are implemented; the question was which one guards the exit.

**Chosen.** The gate **raises**. A name reaching `AiClient.complete` is a bug in the
caller — the caller was supposed to pass a UID — and silently redacting it would let
that bug live forever, in every future call, undetected.

Redaction still has a place: content that legitimately *contains* a name (textbook
prose) is scrubbed on the way in. Then the assertion stays armed as the proof.

**Tradeoff**
- ✅ A leak is a loud, testable, fixable event
- ✅ The property is *proved* by the gate rather than assumed
- ❌ A generation can fail for a reason that looks unrelated — which is precisely
  what `test_a_roster_name_in_a_textbook_statement_does_not_kill_generation` covers

---

## D10 · Names are matched against the actual roster, not guessed by pattern

**Date:** M1 · **Affected invariant:** I-ai-03

Swiss school rosters are FR/DE/IT names. A "capitalised word" heuristic would flag
Pythagore, Thalès and Zürich, mangling exercise statements — and would still miss a
name it had not seen. Matching against the class roster we were handed is *exact* and
has no false positives on mathematics vocabulary.

**Amended by experience.** D10 was too optimistic in one respect: the roster match is
exact against the *prompt*, but textbook prose is full of Léa, Noah and Emma, who are
also in the class. Asserting alone meant a corpus that happened to name a pupil
silently killed generation for that student. Style examples are now `scrub`-ed on the
way in; the assertion stays armed.

---

## The grounding rule · an ungrounded provider must not transcribe

**Date:** M1, extended 2026-09 · **Affected invariant:** I-ai-04

Anything that claims to have *read* something must refuse to run on a provider whose
output is a function of a hash. Three purposes, in increasing severity:

| Purpose | What an invented answer would be |
|---|---|
| `extract_exercises` | An exercise attributed to a real page of a teacher's textbook |
| `adaptive_feedback` | A claim about how one named child thinks, printed and handed to them |
| `grade_open_answer` | A verdict on a real child's answer, drawn from a hash |

The echo provider still **authors** when asked to author (`generate_exercises`): a
made-up practice question is honestly labelled generated and gated behind teacher
approval. The distinction is not "can the model do this" but "would the output be
attributed to something real".

---

## Prompts are versioned files

**Date:** M1 · **Affected invariant:** I-ai-05

`ai/prompts/<name>.<version>.md`, loaded by `load_prompt(name, version)`, with the
name and version stored on every `ModelCall`. A shipped version is never edited — a
change is a new file — because a stored result references the prompt that produced it.
`grade_open_answer` is at v2; v1 is still on disk.

---

## When policy changes

```json
{
  "change": "catch PiiLeakError in the batch loop and continue with the next student",
  "reason": "one student's prompt should not fail the batch",
  "date": "YYYY-MM-DD",
  "decision": "rejected — violates I-ai-02",
  "rationale": "the batch already degrades per student without swallowing the gate.
                Catching PiiLeakError specifically would turn a proof into a warning."
}
```
