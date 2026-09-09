# Retrieval

**Status:** describes `main` as of 2026-09-09
**Audience:** developers, LLM agents, reviewers

---

## 1 · What it does

The teacher types an intent — *"révision fractions avant le test"* — picks chapters and
a difficulty, and gets an ordered list of exercises with a **provenance panel** beside
each one: which book, which page, which chapter, and why this item was ranked where it
was. This module produces that list, and it is also the candidate engine the adaptive
sheet builds on.

```
  intent + chapters + difficulty + language
        │
        ▼
  gather_candidates      SQL, tenant-scoped, unapproved AI excluded, chapter filter HARD
        │
        ▼
  similarity_terms       pgvector <=> on Postgres · the same cosine in Python on SQLite
        │
        ▼
  score = 0.45·similarity + 0.20·difficulty_fit + 0.20·competency_fit + 0.15·language_fit
        │
        ▼
  select_diverse (greedy)   − 0.15 same chunk · − 0.07 same chapter · − 0.30 near-duplicate
        │
        ▼
  build_proposal + build_provenance   the reason, written in the SHEET's language
```

### Key properties

1. **Language is a preferential hard filter**, not merely a term. Candidates in the
   sheet's language are exhausted before any other language is considered.
2. **Selection is greedy, not a top-N sort**, because the diversity penalty depends on
   what has already been picked.
3. **The same maths on Postgres and SQLite**, so the whole RAG path is exercisable in
   CI with no Postgres and no API key.

---

## 2 · Invariants (load-bearing)

| # | Invariant | Enforced in | Why it matters | Failure symptom |
|---|---|---|---|---|
| I-retrieval-01 | **Unapproved AI exercises are never proposed.** | `services/retrieval.py::gather_candidates` | The approval gate must hold at the *suggestion*, not only at the print | The teacher builds a sheet that then refuses to render |
| I-retrieval-02 | **Everything is school-scoped**, including the chapter and competency lookups. | `gather_candidates`, `_competencies_of_chapters`, `chapters_for_competencies` | Tenancy is not optional in a shared corpus of books | One school's textbook proposed to another |
| I-retrieval-03 | **Language is a preferential hard filter.** Other languages are used only once the sheet's language runs out. | `gather_candidates` (+ `language_fit` in the score) | Printing a German exercise on a French sheet is a defect, not a trade-off | A pupil handed an exercise they cannot read |
| I-retrieval-04 | The **chapter filter is hard.** | `gather_candidates` | The teacher asked for a chapter, not a hint | Items from a chapter the class has not covered |
| I-retrieval-05 | **No intent ⇒ no similarity term.** Similarity is 0.5 for everything, so the term drops out rather than distorting. | `_embed_intent`, `similarity_terms` | An embedding of six words is a weak signal; chapter + difficulty are strong ones | A random-looking order presented as relevance |
| I-retrieval-06 | **Selection is greedy with an accumulating diversity penalty**, never a plain sort. | `select_diverse`, `_greedy`, `diversity_penalty` | Eight variations of one fraction addition off one chunk is a worse sheet than eight merely-good items | A monotonous sheet built from one page |
| I-retrieval-07 | **The displayed score is the score it was ordered by**, and the reason never claims a match at zero similarity. | `score_of`, `build_provenance`, `_reason` | The provenance panel is an audit surface, not decoration | A panel that explains an order the list does not have |

---

## 3 · Module map

| Path | Owns | Depends on |
|---|---|---|
| `alppy/services/retrieval.py` | `propose_exercises`, `gather_candidates`, `similarity_terms`, `select_diverse`, `diversity_penalty`, `build_proposal`, `build_provenance`, `cosine_similarity` | `models`, `ai` (embeddings), pgvector or Python |
| `alppy/api/v1/sheets.py::propose` | `POST /sheets/propose` | `retrieval` via `deps.load_optional` |
| `alppy/services/adaptive_service.py` | The other consumer: candidates per gap | `retrieval` |
| `apps/web/.../sheet-builder/ProposeTab.tsx` | The intent box, the ranked list, the provenance panel | `packages/shared` |

---

## 4 · How to extend this feature

The four weights are the ranking. If you change one, change this table and say why:

| Term | Weight | What it is |
|---|---|---|
| `similarity` | 0.45 | Cosine between the intent vector and the exercise's source chunk |
| `difficulty_fit` | 0.20 | `1 − |difficulty − target| / 4` |
| `competency_fit` | 0.20 | Share of the exercise's competencies the requested chapters ask for |
| `language_fit` | 0.15 | 1.0 in the sheet's language, else 0.0 |

Similarity is the largest single term but **deliberately not a majority**: an embedding
of a six-word intent is a weak signal, and a teacher who asked for chapter *Fractions*
at difficulty 2 has given two much stronger ones. When the intent is empty the other
three decide the order entirely — correct behaviour, not an accident.

### LLM checklist

- [ ] Read §2 — these are not suggestions
- [ ] Could an unapproved AI item now be proposed? (I-retrieval-01 — never)
- [ ] Is every new query school-scoped? (I-retrieval-02)
- [ ] Does a language other than the sheet's get in before the sheet's is exhausted? (I-retrieval-03)
- [ ] Did greedy selection become a sort? (I-retrieval-06)
- [ ] Does the reported score still match the order? (I-retrieval-07)
- [ ] Does the SQLite path still compute the same cosine as pgvector?

---

## 5 · Privacy & safety

| Data | Where it is handled | Why |
|---|---|---|
| The intent string | Embedded; no student data in it | The teacher types it about a topic |
| Corpus content | Never crosses a tenant boundary | I-retrieval-02 |
| The reason text | Generated from the ranking terms, in the **sheet's** language | It is an explanation, not model output |

The provenance panel exists so a teacher can **check** a proposal against the book on
their desk. Anything that makes it less specific — a page range instead of a page, a
chapter instead of a source — removes the ability to audit, which is the feature.

---

## 6 · Testing strategy

| Invariant | Proved by |
|---|---|
| I-retrieval-01 | `test_retrieval.py::test_unapproved_ai_exercises_are_never_proposed_for_a_sheet` |
| I-retrieval-02 | `::test_school_scoping_is_enforced`, `::test_competency_and_chapter_lookups_are_school_scoped` |
| I-retrieval-03 | `::test_language_follows_the_source_not_the_ui`, `::test_other_languages_are_only_used_once_the_right_one_runs_out` |
| I-retrieval-04 | `::test_chapter_filter_is_hard`, `::test_competency_filter_targets_exercises_directly` |
| I-retrieval-05 | `::test_no_intent_means_no_similarity_and_the_provenance_says_so`, `::test_similarity_terms_are_neutral_without_signal_and_spread_with_it`, `::test_an_intent_never_penalises_the_whole_candidate_set` |
| I-retrieval-06 | `::test_repeats_from_the_same_chunk_are_penalised`, `::test_near_duplicate_statements_are_penalised`, `::test_diversity_penalty_accumulates_over_what_is_already_picked` |
| I-retrieval-07 | `::test_the_displayed_score_matches_the_order_it_is_displayed_in`, `::test_the_reason_never_claims_a_match_at_zero_similarity`, `::test_provenance_is_specific_enough_to_check_against_the_book` |
| pgvector parity | `::test_cosine_similarity_matches_pgvector_semantics` |

```bash
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests/test_retrieval.py -q
```

29 tests, no Postgres required.

---

## Companion documents

- [`architecture.md`](architecture.md) — the ranking, the greedy selection, the two backends
- [`decisions.md`](decisions.md) — the weights, the hard filters, D18
- [`../../rag.md`](../../rag.md) — the RAG design
- [`../corpus/`](../corpus/) — what is being ranked

**Last updated:** 2026-09-09
