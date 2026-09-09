# Retrieval Architecture

## Component diagram

```
  POST /sheets/propose {class, subject, chapters[], intent, difficulty, count}
        │                       (also called by adaptive_service, per gap)
        ▼
  propose_exercises
        │
        ├─ _embed_intent(intent)          empty intent → no vector at all
        │
        ├─ gather_candidates              ── one SQL query, tenant-scoped
        │     WHERE school_id = …
        │       AND NOT (origin = AI_GENERATED AND approved_at IS NULL)   (I-retrieval-01)
        │       AND chapter_id IN (…)      hard                            (I-retrieval-04)
        │     ORDER BY language = sheet_language DESC                      (I-retrieval-03)
        │       (+ pgvector `embedding <=> :intent` on Postgres)
        │
        ├─ similarity_terms → _apply_similarity
        │     Postgres: cosine from the query
        │     SQLite:   cosine_similarity() in Python over the fetched rows
        │
        ├─ _attach_competency_codes
        │
        └─ select_diverse → _greedy
              for each pick: score_of(candidate) − diversity_penalty(already_taken)
        ▼
  build_proposal + build_provenance
        source · page · chapter · excerpt (trimmed on a word boundary) · reason · score
```

## Data flow

### The candidate

```python
@dataclass
class Candidate:
    exercise: Exercise
    chunk_id: UUID | None       # provenance, and the same-chunk penalty
    similarity: float           # 0.5 for everything when there is no intent
    difficulty_fit: float       # 1 − |difficulty − target| / 4
    competency_fit: float       # share of the exercise's competencies requested
    language_fit: float         # 1.0 or 0.0
```

### The formula

```
base  = 0.45·similarity + 0.20·difficulty_fit + 0.20·competency_fit + 0.15·language_fit

score = base − 0.15·same_chunk_already_taken
             − 0.07·same_chapter_already_taken
             − 0.30·near_duplicate_of_something_taken
```

`similarity` is the largest single term and deliberately **not a majority**. An embedding
of a six-word intent is a weak signal; "chapter *Fractions*, difficulty 2" is two much
stronger ones. With no intent the term is a constant 0.5 for every candidate, so it
drops out of the ordering rather than distorting it, and the provenance says so.

### Greedy selection, not a sort

The diversity penalty depends on **what has already been picked**, which a plain sort
cannot express. Eight variations of the same fraction addition off one textbook chunk is
a worse sheet than eight merely-good items that cover the chapter.

The near-duplicate test is a Jaccard overlap of statement phrases — cheap, language-
agnostic, and enough to catch the "same exercise with different numbers" case that a
single chunk produces.

## Component interaction

### Postgres vs SQLite

| | Postgres | SQLite |
|---|---|---|
| Cosine | pgvector `<=>` inside the query | `cosine_similarity()` in Python over fetched rows |
| Used by | Production | The unit suite, and any contributor with no Postgres |

Identical maths, pinned by `test_cosine_similarity_matches_pgvector_semantics`. It means
the whole RAG path — including this ranking — is exercisable in CI with no Postgres and
no API key (D18).

### Language as a preferential hard filter

Candidates in the sheet's language are **exhausted before any other language is
considered**. `language_fit` stays in the formula so the reported score still reflects
it, but the ordering guarantee does not come from the weight — printing a German
exercise on a French sheet is a defect, not a trade-off.

The exercise's language follows the **source material**, never the teacher's UI locale
(see `adaptive` I-adaptive-06).

### Provenance

`build_provenance` returns what a teacher can check against the book on their desk: the
source filename, the page, the chapter, an excerpt trimmed on a word boundary, and a
reason written in the **sheet's** language. `_reason` never claims a topical match when
similarity is zero — a sentence that says "matches your intent" about a ranking that
ignored the intent would make the panel worse than absent.

## Edge cases

- **No intent.** → no vector is computed; similarity is neutral, and the provenance says
  the ranking used chapter and difficulty.
- **An intent that matches nothing.** → the whole candidate set is *not* penalised; the
  order falls back to the other three terms.
- **A plural intent against a singular subject** ("fractions" vs "fraction"). → still
  found; the embeddings are multilingual and morphology-tolerant.
- **An untagged exercise** (no competencies). → neither a match nor a mismatch: it does
  not gain `competency_fit`, and it is not excluded.
- **A missing locale label.** → falls back rather than rendering a key.
- **Fewer candidates than requested.** → returns what exists; the caller (adaptive)
  decides whether to generate the shortfall.
- **An exercise discarded by a teacher.** → never proposed again, even if it is later
  approved.

---

**Companion:** [`README.md`](README.md) §2 for the load-bearing rules.
