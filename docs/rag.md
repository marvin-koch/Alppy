# Retrieval and generation

How a teacher's textbook becomes a ranked list of exercises (F1), and how a
student's gaps become a targeted sheet (F4).

---

## 1. Ingestion

`alppy/ingest/` — extract → chunk → embed → index → extract exercises.

### Chunking is exercise-aware, and that is the whole trick

Constants live in `alppy/ingest/chunk.py`: target 650 characters, floor 500,
ceiling 800, overlap 120.

The sizes matter less than the **boundaries**. Chunks prefer to break where a
numbered exercise starts (`^\s*\d+[.)]` and friends) rather than at a fixed
character count, because a chunk that splits an exercise in half poisons
everything downstream twice over: retrieval matches half a question, and
extraction produces an exercise whose statement stops mid-sentence. Page number
and position travel with every chunk, because provenance is not optional — the
teacher audits it against the book on their desk.

A PDF with no extractable text (a scanned book) is recorded as such on the
`Source` rather than silently producing zero chunks and looking like success.

Ingestion is idempotent on `Source.sha256`: re-uploading the same file reuses the
existing chunks and exercises instead of duplicating the corpus.

### Embeddings

The interface is `AiClient.embed`. The shipped default is
`HashEmbeddingsProvider` — a hashing trick with L2 normalisation, **not a
semantic model**. It exists so that retrieval, pgvector indexing and the whole
RAG path are exercisable offline, in CI, and in `docker compose up` with no API
key. Retrieval quality with it is a floor, not a preview.

The real choice is [ADR 0001](adr/0001-embeddings-provider.md): self-hosted
`intfloat/multilingual-e5-large`, 1024 dimensions (matching the `vector(1024)`
column), MIT-licensed, strong on French and German — which is the decisive
criterion here, and the reason the obvious hosted options lose.

Cosine distance uses pgvector's `<=>` on Postgres and falls back to computing
cosine in Python on SQLite, so the unit suite and CI need no database extension.

---

## 2. Ranking

`alppy/services/retrieval.py`. Four scored terms, then a diversity penalty
applied **at selection time**:

```
base  = 0.45 · similarity      cosine of the intent vector against the
                               exercise's source chunk; 0.5 for everything
                               when no intent was typed, so the term drops
                               out rather than distorting the order
      + 0.20 · difficulty_fit  1 − |difficulty − target| / 4
      + 0.20 · competency_fit  share of the exercise's competencies that the
                               requested chapters actually ask for
      + 0.15 · language_fit    1.0 in the sheet's language, else 0.0

score = base − 0.15 · same source chunk already taken
             − 0.07 · same chapter already taken
             − 0.30 · near-duplicate of something already taken
```

**Similarity is the largest single term but deliberately not a majority.** An
embedding of a six-word intent is a weak signal; a teacher who picked the
chapter *Fractions* and difficulty 2 has given two much stronger ones. When the
intent is empty the other three decide the order entirely — correct behaviour,
not an accident.

**Selection is greedy, not a top-N sort**, because the diversity penalty depends
on what has already been chosen. Eight variations of one fraction addition
lifted from a single textbook chunk is a worse sheet than eight merely-good
items that cover the chapter, and a plain sort cannot express that.

**Language is a preferential hard filter.** Candidates in the sheet's language
are exhausted before any other language is considered. Printing a German
exercise on a French sheet is a defect, not a trade-off: an exercise's language
follows its source material, never the teacher's UI locale.

### Provenance

Every proposal carries source filename, page, a quoted excerpt, the similarity
score, and a **human-readable reason** — *"matches chapter Fractions, difficulty
3, close to your intent"*. The excerpt renders in mono (`[data-transcription]`)
because it is data the teacher is auditing, and it should look like it.

---

## 3. Adaptive generation (F4)

`alppy/services/adaptive_service.py`. The focal feature, and the one with the
strongest ordering constraint:

> **Retrieve first. Generate only to fill the gap.**

For each student: read their latest `MasterySnapshot` rows, take the weakest
competencies (`fading` and `weak` first, then `ok`, never `solid`), and pick a
target difficulty — slightly below their current level for a fading competency,
at level for a fragile one. Then fill the sheet from **indexed textbook
exercises**. Only if retrieval cannot supply the requested count does the model
get asked for the remainder.

Why that order matters:

- A textbook exercise is already pitched at the right cohort, in the right
  register, and the teacher can check it against the page it came from.
- A generated exercise cannot be checked against anything.
- The teacher's own material is what they trust, and trust is the scarce
  resource in this product.

Generated items are passed **style examples drawn from the retrieved
exercises**, so they match the register of the book rather than sounding like a
model.

### The two hard rules

**No student name ever reaches a model.** The prompt carries the UID (`7B_15`),
wrapped by `alppy.ai.scrub.to_ref`, and `assert_no_pii` gates the final string
before it leaves the process. The gate **raises** rather than redacting: a name
in a prompt is a caller bug and must fail loudly, not be silently papered over.
A test asserts that generating for a student whose roster contains a real name
never puts that name in the prompt.

**Nothing generated is printed without approval.** AI-generated exercises are
persisted with `origin=AI_GENERATED` and `approved_at=None`, and the batch export
stays disabled until a teacher approves them. In the UI they are the one and
only thing wearing the mandarin accent — which is precisely why that colour is
not allowed anywhere else.

Prompts live in versioned files (`alppy/ai/prompts/*.v1.md`), never inline
strings, and every call is audited: provider, model, prompt hash, tokens,
latency, cost estimate — and never content.

---

## 4. Known limits

- The hash embedder makes offline retrieval **lexical, not semantic**. Swap it
  before judging proposal quality.
- Chunking has only been exercised against the self-authored demo corpus. A real
  Lehrmittel — two columns, marginalia, boxed exercises — will need work.
- Near-duplicate detection is textual, so two exercises that are the same problem
  in different words both survive.
- There is no evaluation set. "The proposals look reasonable" is not a metric;
  building twenty labelled intents is milestone **M8** in
  [`handover.md`](handover.md).
