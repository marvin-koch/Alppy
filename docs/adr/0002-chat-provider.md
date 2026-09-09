# ADR 0002: Chat (generation) provider

Status: Accepted
Date: 2026-09-09
Supersedes: the "Anthropic is the default for generation" line in `docs/privacy.md` §3

## Context

`docs/plan.md` and `docs/privacy.md` §3 named Anthropic as the default generation
provider, with `alppy/ai/` provider-agnostic by construction so a canton or a school
could require otherwise. That construction has now been exercised for the first time:
a second real provider exists, and the default moves to OpenAI's Responses API.

The AI layer's contract does not change. `ChatProvider` in `alppy/ai/base.py` is still
`name`, `grounded`, `complete(ChatRequest) -> ChatResponse`; the PII gate still runs
inside `AiClient.complete` before anything leaves the process; prompts are still
versioned files. What changes is which vendor a keyless-default deployment would talk
to, and that is a data-residency question, not an engineering one.

## Decision

1. **`OpenAiChatProvider` (Responses API) becomes the default**, with
   `ALPPY_AI_CHAT_PROVIDER=openai`. `AnthropicChatProvider` remains, selectable by the
   same setting, and `EchoChatProvider` remains the offline fallback.
2. **The API key follows the existing settings convention** — `ALPPY_OPENAI_API_KEY`,
   read by `alppy/core/config.py` (pydantic-settings, prefix `ALPPY_`). Not a bare
   `LLM_API_KEY`: every other secret in this product is `ALPPY_`-prefixed, and one
   exception is how a `.env` stops being readable.
3. **Provider and model are validated as a pair at startup.** `ai_chat_model` defaults
   to empty, meaning "this provider's default"; a model id belonging unmistakably to a
   different vendor raises on load. A `claude-*` id sent to OpenAI is a 404 on every
   generation, extraction and grade — and `AiClient`'s failure path records
   `ai_chat_model` on the audit row, so the trail would name a model that was never
   called.
4. **A missing key logs and falls back to `echo`, loudly.** With one real provider the
   fallback only ever caught "no account at all". With two it also catches the
   deployment holding the *other* vendor's key, which would otherwise answer
   hash-derived multiplication tables labelled only as "generated". `ai.provider.no_key`
   names what was configured and what was missing.

## Consequences

**Temperature is a model property, not a setting.** Reasoning models reject a
non-default `temperature`, and every call site in the product passes one — 0.0 for
extraction and grading, 0.4 for feedback, 0.6 for adaptive generation.
`grade_open_answer.v2.md` states its own contract in its front matter: *temperature 0.0
— a grade must be reproducible, never creative.* A model that will not take the
parameter cannot honour that. The provider therefore keeps a prefix table for the models
we know about **and** learns a refusal at runtime (one wasted request per process),
logging `ai.temperature.dropped` every time it happens. If that line appears for
`grade_open_answer` in a real deployment, the choice is to move to a model that accepts
temperature — not to quietly accept variable grading.

**Truncation is its own failure.** The Responses API's `max_output_tokens` covers
reasoning *and* visible output, so a budget spent thinking returns nothing. Returning
`""` would surface to a teacher as "the provider returned something unusable" when the
cause is a number in the configuration. `ChatTruncatedError` and the `truncated` failure
reason exist so the message names the real cause.

**No structured output.** The Responses API can enforce a JSON schema; we do not use it.
I-adaptive-08 depends on a schema-invalid item being dropped by `GeneratedExerciseIn`
while the good items beside it survive, and provider-side rejection would lose them.
Keeping the parse path identical across providers also keeps the two comparable.

**Cost estimates are unverified for the new rows.** `_COST_PER_MTOK` in
`alppy/ai/client.py` is marked as such. An unknown model now logs
`ai.cost.unknown_model` rather than silently reporting 0.00 CHF, because
`docs/privacy.md` §3 offers that column as budget accounting.

**Data residency is now a different story and must be re-told.** `docs/privacy.md` §3 is
the paragraph a school's DPO reads. It has been rewritten rather than find-and-replaced:
the residency position for one vendor is not the residency position for another, and no
processor agreement exists with either yet (§7 already says so).

## Alternatives considered

- **Keep Anthropic as the default and add OpenAI as an option.** Rejected: the product
  owner asked for OpenAI as the default. The mechanism is identical either way — the
  setting — so this is a one-line difference, and the setting means any deployment can
  reverse it without a code change.
- **Per-purpose providers** (grading on one vendor, generation on another). Rejected for
  now: more configuration surface than there is evidence to justify, and it would make
  "did any of our data go to provider X" — the question §3 exists to answer — a query
  over four settings instead of one.
- **A `LLM_API_KEY` variable, as originally briefed.** Rejected: it breaks the
  `ALPPY_` prefix that `Settings` is built on, and with two providers a single key
  variable cannot say which vendor it belongs to.
