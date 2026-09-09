# Retrieval Decisions Log

D-numbers follow the repo-wide [`docs/decisions-log.md`](../../decisions-log.md);
entries without one are local to this subsystem.

---

## The four weights · similarity is the largest term and not a majority

**Date:** M2 · **Affected invariant:** I-retrieval-05

**Background.** The obvious RAG design ranks by cosine similarity and stops.

**Considered alternatives**
- A) *Pure vector search.* Rejected: an embedding of "révision fractions avant le test"
  is six words of signal, while the teacher has *also* told us the chapter, the
  difficulty and the language — three strong, exact signals that a cosine cannot beat.
- B) *A learned ranker.* Rejected: no training data, and no way to explain a rank to a
  teacher, which the provenance panel requires.
- C) **A four-term linear score, similarity at 0.45.** Chosen.

**Tradeoff**
- ✅ Every term is explainable in one line in the provenance panel
- ✅ With no intent the ranking is still sensible — the term simply drops out
- ❌ Four constants that were set by judgement, not by fitting

---

## Language is a filter, not a weight

**Date:** M2 · **Affected invariant:** I-retrieval-03

`language_fit` at 0.15 would let a strongly-matching German exercise outrank a decent
French one on a French sheet. That is not a trade-off a teacher would accept: a pupil
handed an exercise in a language they do not read cannot do it at all.

So candidates in the sheet's language are **exhausted first**, and the weight stays only
so the reported score reflects reality.

---

## Selection is greedy, because diversity is not a property of one item

**Date:** M2 · **Affected invariant:** I-retrieval-06

A plain top-N sort cannot express "this is a good item, but I already took three from
the same chunk". The penalties accumulate over what has been picked:

| Penalty | Weight | Catches |
|---|---|---|
| Same source chunk | −0.15 | Eight variations of one exercise off one page |
| Same chapter | −0.07 | A sheet that never leaves section 4.2 |
| Near-duplicate statement | −0.30 | The same exercise with different numbers |

**Tradeoff**
- ✅ A sheet covers the chapter instead of one paragraph of it
- ❌ The result is order-dependent, so the reported score has to be the *penalised* one
  (I-retrieval-07) or the panel would explain an order the list does not have

---

## D18 · Tests run on SQLite with a test-only type swap

**Date:** M0 · **Affected invariant:** the RAG test strategy

CI stays fast and contributors need no Postgres for the unit suite: `Vector` and `JSONB`
are swapped for test-only types, and cosine is computed in Python. Integration tests that
exercise pgvector run against the Postgres service container, and
`test_cosine_similarity_matches_pgvector_semantics` pins that the two agree.

The consequence worth stating: **29 retrieval tests run with no database server and no
API key.** That is why the ranking can be changed with confidence.

---

## Unapproved AI is excluded at the proposal, not just at the print

**Date:** M5 · **Affected invariant:** I-retrieval-01

The approval gate would catch it at render. Excluding it here as well is not redundant:
a teacher who builds a sheet from a proposal and then cannot print it has been sent down
a path that was never going to work. The suggestion surface and the print surface must
agree.

---

## When policy changes

```json
{
  "change": "raise similarity to 0.7 and drop competency_fit",
  "reason": "the embeddings are better now",
  "date": "YYYY-MM-DD",
  "decision": "requires re-checking test_no_intent_means_no_similarity_and_the_
               provenance_says_so and the whole provenance surface",
  "watch": "with no intent, a majority-weight similarity term makes the ranking
            arbitrary while still LOOKING scored — the worst of both."
}
```
