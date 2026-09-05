# ADR 0001: Embeddings provider

Status: Accepted
Date: 2026-09-05

## Context

Alppy's RAG pipeline needs a text-embedding model for two purposes: indexing textbook chunks
(`SourceChunk.embedding`, `vector(1024)` in the plan) and embedding a teacher's stated intent /
retrieval queries at sheet-build and adaptive-generation time. This choice is separate from the
choice of generation model (Anthropic, default per `docs/plan.md`) for two reasons:

1. **Anthropic does not offer an embeddings endpoint.** Verified directly against Anthropic's own
   documentation: *"Anthropic does not offer its own embedding model."* Anthropic's docs point
   third-party developers to Voyage AI (and note that other vendors — OpenAI, Cohere, Mistral —
   are options to evaluate).
   Source: [Anthropic — Embeddings](https://platform.claude.com/docs/en/build-with-claude/embeddings), accessed 2026-09-05.
2. **The data-sensitivity constraint is different from generation.** `docs/privacy.md` §2
   establishes a hard rule that no student PII reaches a third-party model. Textbook chunks are
   *not* student data — they are (per `docs/research/textbook-access-ch.md`) either the teacher's
   own uploaded material or a self-authored demo corpus. The privacy constraint that dominates
   generation (never send a name to a vendor) mostly doesn't apply here. What dominates instead is
   the **licensing caution** from that same research doc: publisher licence terms explicitly
   forbid third-party use/extraction of digital textbook content (Klett und Balmer's terms say so
   in as many words), and GT 7/Art. 19 URG do not clearly license a third-party SaaS to reproduce
   textbook content at all — sending full chunk text to an external embeddings API is an additional,
   avoidable act of "giving the content to a third party" on top of whatever risk already exists
   from indexing it in the first place. Minimizing the number of parties that ever see the raw
   text is the operative principle, not PII.
3. **Query embeddings do carry a teacher's typed intent** (free text like "more fraction word
   problems for the strugglers"), which is low-sensitivity but not zero-sensitivity — another
   reason to prefer not routing every retrieval query through an external vendor by default.
4. **French/German quality is decisive.** Alppy's primary languages are fr and de (plus en).
   Embedding quality on Sek I subject-matter text in these two languages matters more than raw
   English MTEB leaderboard position.

## Decision

**Self-host `intfloat/multilingual-e5-large` as the embeddings model**, served from
`alppy/ai/` behind the same provider-agnostic interface used for generation, with no data leaving
infrastructure Alppy controls for this purpose.

Verified facts about the model:

- **Dimensions: 1024** — matches the `vector(1024)` column already specified in the domain model
  (`docs/plan.md` §3), so no schema change or re-indexing scheme is needed.
  Source: [intfloat/multilingual-e5-large — Hugging Face](https://huggingface.co/intfloat/multilingual-e5-large), accessed 2026-09-05.
- **Licence: MIT.** Free to self-host, modify, and run in any environment without per-seat or
  per-call licensing.
  Source: [intfloat/multilingual-e5-large — Hugging Face](https://huggingface.co/intfloat/multilingual-e5-large), accessed 2026-09-05.
- **Language coverage:** trained on 100 languages via XLM-RoBERTa; French and German are
  well-represented, high-resource languages for this model family (the model card itself warns
  that *low-resource* languages may degrade — fr/de are not in that category).
  Source: same, accessed 2026-09-05.
- **Usage constraints to design around:** requires `"query: "` / `"passage: "` prefixes for
  asymmetric retrieval (must be baked into `alppy/ai/embed.py`'s call sites, not left to callers to
  remember), and truncates at **512 tokens** — chunking must respect this ceiling upstream.
  Source: same, accessed 2026-09-05.

### Operational cost of self-hosting

`multilingual-e5-large` is a ~560M-parameter encoder (~1.1 GB in fp16). It runs adequately on CPU
for the MVP's throughput profile (ingestion is a background job, not a latency-critical path per
Flow 1 in `docs/architecture.md`; a school ingesting a chapter's worth of PDF is not a
requests-per-second problem) and comfortably on a small/shared GPU if ingestion volume grows. This
is an order-of-magnitude estimate, not a benchmarked figure — validate against real ingestion
volume before committing to a specific instance size; the qualitative point is that self-hosting a
560M-parameter encoder is inexpensive relative to running the product's Postgres/Redis/worker
tier, not that a specific dollar figure has been measured.

## Alternatives considered

| Option | Dimensions | Licence/access | Multilingual fr/de | Residency | Why not chosen |
|---|---|---|---|---|---|
| **`intfloat/multilingual-e5-large`** (chosen) | 1024 | MIT, self-hosted | Strong (100-lang XLM-R base) | Fully controlled — no vendor call | — |
| `BAAI/bge-m3` | 1024 | MIT, self-hosted | Strong; adds sparse + multi-vector retrieval, 8192-token context | Fully controlled | Real alternative, not rejected on quality — e5-large is the safer default because its usage pattern (single dense vector, query/passage prefix) is simpler to integrate with a plain `pgvector` column and existing tooling; bge-m3's multi-functionality is upside Alppy doesn't need yet. Revisit if long-chunk retrieval quality becomes a problem (see below). |
| Voyage AI (`voyage-4` family, Anthropic's recommended partner) | 1024 (configurable via Matryoshka) | Hosted API, commercial | Explicitly multilingual-optimized per Anthropic's own docs | Vendor-controlled (US-based vendor per public docs) | Would mean sending every textbook chunk (and every teacher query) to a third-party vendor — exactly the extra exposure §Context flags as avoidable given the unresolved licensing posture of textbook content. Best-in-class if a hosted option is later required. |
| Cohere `embed-v4` | 1536 (configurable 256–1536) | Hosted API, commercial (~$0.12/M tokens per search-derived pricing, unverified against Cohere's own pricing page) | 100+ languages incl. fr/de | Vendor-controlled | Same third-party-exposure objection as Voyage; also a dimension mismatch against the planned `vector(1024)` column unless truncated. |
| OpenAI `text-embedding-3-large` | 3072 (truncatable) | Hosted API, commercial (~$0.13/M tokens per OpenAI's pricing) | Meaningfully improved multilingual/MIRACL scores over `ada-002` per OpenAI's own announcement | Vendor-controlled, US-based by default | Same third-party-exposure objection; native dimensionality is 3x the planned column (usable truncated to 1024, but that's working around the vendor's design rather than with it). |
| Mistral `mistral-embed` | 1024 | Hosted API, commercial (~$0.10/M tokens per aggregator pricing, unverified against Mistral's own page) | "Strong English and French quality" per available summaries; German coverage less clearly documented | EU (France)-based vendor — best residency story of the hosted options | Matches dimensions and has an EU home, making it the strongest *hosted* fallback if self-hosting turns out to be operationally unworkable; not chosen as primary because self-hosting removes the third-party-exposure question entirely rather than just improving its jurisdiction, and German-language quality wasn't found clearly documented in sources checked. |

Pricing figures in this table come from secondary/aggregator sources found via search, not each
vendor's own pricing page fetched directly — treat them as indicative only and re-verify before any
procurement decision.

## Consequences

- No per-token embedding cost, no vendor rate limits on ingestion throughput.
- Alppy owns model-serving infrastructure (a small inference service inside `alppy/ai/` or a
  sidecar) — this is new operational surface that hosted APIs would have avoided; budget for it in
  the worker/infra plan.
- The 512-token truncation limit must be enforced by the chunker (`alppy/ingest/`), not discovered
  at query time — chunk sizes should be chosen with headroom under 512 tokens, prefix text
  included.
- Because embeddings never call an external vendor, the `ModelCall` audit log (`docs/privacy.md`
  §3) will show generation calls to the configured LLM provider but no embedding-related rows for
  external providers — this is expected and should not be read as a monitoring gap.
- Model upgrades (e.g. swapping in a newer self-hosted checkpoint) require re-embedding existing
  `SourceChunk` rows, since vectors from different model versions are not comparable — this is a
  migration, not a config change, and should be planned as one (batch re-embed job, dual-write
  during transition, or an accepted one-time reindex window).

## Revisit if

- Self-hosted inference cost/latency at real ingestion volume turns out to be worse than expected
  (e.g. large multi-hundred-page textbook uploads becoming a throughput bottleneck on shared
  worker infrastructure) — Mistral `mistral-embed` (EU-hosted, matching 1024 dims) is the
  pre-evaluated fallback.
- Retrieval quality on long or structurally complex chunks (tables, multi-part exercises) proves
  inadequate — `BAAI/bge-m3`'s multi-vector/sparse retrieval and 8192-token context is the
  pre-evaluated upgrade path, at the cost of a more complex retrieval implementation than a single
  dense `pgvector` column.
- A publisher partnership (`docs/research/textbook-access-ch.md` §6) is signed with contractual
  terms that explicitly permit and price third-party embedding of their content — at that point the
  self-hosting rationale in §Context point 2 weakens for that publisher's content specifically, and
  a hosted vendor could be reconsidered on pure cost/quality grounds.
- Anthropic ships a first-party embeddings endpoint — re-run this ADR's comparison rather than
  assuming it wins by default; the French/German quality bar and the licensing-caution rationale
  still apply regardless of vendor.
