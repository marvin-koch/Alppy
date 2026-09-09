# Corpus

**Status:** describes `main` as of 2026-09-09
**Audience:** developers, LLM agents, reviewers

---

## 1 · What it does

A teacher uploads their textbook PDFs. This subsystem turns each one into something a
sheet can be built from: page-provenanced text chunks with embeddings, the document's
**own** table of contents, and `Exercise` rows — many of them carrying an **image crop
of the book's page** rather than a transcription of it.

```
  POST /sources  (PDF, subject)  ──▶ Source + Job(INGEST_SOURCE)   [request returns]
        │
        ▼  arq worker — ingest/pipeline.py::run_ingest
   extract.extract_pdf ──▶ PageText[]        page numbers survive; no text layer → FAILED
        │
        ├─ sections.detect_sections ──▶ SourceSection[]   the book's own chapters
        │
        ├─ chunk.chunk_pages ─────────▶ Chunk[]           never splits an exercise,
        │                                                 never spans a page
        │      └─ ai.embed ───────────▶ SourceChunk(embedding vector(1024))
        │
        ├─ regions.detect ────────────▶ Exercise(label "NO64", figure_key = a CROP)
        │                                                 deterministic, no model
        │
        └─ _extract_eagerly (budget) ─▶ Exercise(...)      model transcription for
                                                           books without coded headers
        ▼
   the rest of the book waits: SourceSection.extracted_at IS NULL
        │
        └─ POST /sources/{id}/sections/{sid}/extract  ← read one chapter on demand
```

### Key properties

1. **Page provenance is the product.** A teacher auditing a proposal opens the book at
   a page. Text is never concatenated across page boundaries.
2. **A scanned book is a reported failure, not an empty success.** `pypdf` returns `""`
   for an image-only PDF without raising; that would sail through as a green tick over
   nothing.
3. **What a model cannot do, geometry does.** An exercise that is a figure, a table or
   a photo is *cut out of the page*, not transcribed.

---

## 2 · Invariants (load-bearing)

| # | Invariant | Enforced in | Why it matters | Failure symptom |
|---|---|---|---|---|
| I-corpus-01 | **Page numbers survive extraction.** Text is never concatenated across pages. | `ingest/extract.py` | Provenance is the feature; a wrong page is a lie the teacher checks | "p. 112" opens a page that does not hold the exercise |
| I-corpus-02 | **A PDF with no text layer is reported**, never accepted as empty. | `extract.ExtractedDocument.has_text`, `MIN_DOC_CHARS` | Swiss textbooks are frequently scans | A `SUCCEEDED` source with zero chunks and a green tick |
| I-corpus-03 | A **chunk never splits an exercise** and **never spans a page**. | `ingest/chunk.py::chunk_pages` | Half a statement embeds as a fragment, and the extractor correctly refuses it — a 100 % loss on that item | Exercises silently missing from both halves |
| I-corpus-04 | Chunk sizes stay within the **embedding budget** (target 500–800 chars). | `ingest/chunk.py` | The 512-token truncation limit of the embeddings model | Silently truncated vectors, degraded retrieval |
| I-corpus-05 | A coded exercise becomes a row with an **image crop**, deterministically, **with no model in the loop**. | `ingest/regions.py` | A transcription of `3n²/n` or a figure loses the part the student looks at | Unusable exercises attributed to a real page |
| I-corpus-06 | **Ingestion is idempotent, keyed on `Source.sha256`.** A second upload of the same file in the same school **copies** the existing chunks and exercises. | `ingest/pipeline.py::_ingested_twin`, `_copy_from_twin`, `_wipe` | Two teachers, one textbook, zero model calls | A partial re-run doubling rows, or a second full-price ingestion |
| I-corpus-07 | **Every page belongs to exactly one section**, and sections are contiguous and gapless. | `ingest/sections.py::detect_sections` | An exercise with a null section vanishes from the builder's primary filter | Exercises that exist and cannot be found |
| I-corpus-08 | Extraction is **grounded-only**: an ungrounded provider yields no exercises. | `ai/providers.py::TRANSCRIPTION_PURPOSES` | An invented exercise would carry a real book's provenance | Fiction attributed to a teacher's textbook |
| I-corpus-09 | Eager extraction stops **before** a section it cannot finish whole. | `ingest/pipeline.py::_extract_eagerly` | Half a chapter is the worst outcome available | The teacher sees exercises and cannot tell the back half is missing |
| I-corpus-10 | A Theme's **primary** competency decides where it sits; its **tagged** competencies decide what it credits. The primary must be one of the tagged. | `seed/loader.py::_load_chapters` (raises naming the chapter) | Rolling up through the tagging set would leak a chapter's evidence into a curriculum branch its primary never belongs to | A PER school's Pythagore chapter appears under an LP21 area, or under two areas at once |

---

## 3 · Module map

| Path | Owns | Depends on |
|---|---|---|
| `alppy/ingest/extract.py` | `extract_pdf`, `PageText`, `document_from_pages`, `has_text`, stopword language detection | pypdf |
| `alppy/ingest/chunk.py` | Exercise-aware chunking with page provenance, `TARGET_CHARS` | `extract` |
| `alppy/ingest/sections.py` | `detect_sections` — the document's own outline, conservatively | — |
| `alppy/ingest/regions.py` | Typographic region detection, page crops, `SUITE ▶` stitching. **Pure over bytes**; needs PyMuPDF | `logging` only |
| `alppy/ingest/pipeline.py` | `run_ingest`, `extract_section`, idempotence, chapter/competency resolution, de-duplication | all the above + `ai` + `models` |
| `alppy/api/v1/sources.py` | Upload, status, sections, the faceted paged exercise listing, on-demand extraction, manual exercises | `pipeline`, `deps` |
| `alppy/ai/prompts/extract_exercises.v1/v2.md` | The extraction prompt | — |
| `apps/web/src/app/[locale]/sources/` | Upload, ingestion status, the extracted exercises | `packages/shared` |

---

## 4 · How to extend this feature

**Adding a book format.** Region detection is typographic, not lexical: a header is a
*bold, coloured, body-sized line opening with a short code* at the left edge of the
column. A book that does not use coded headers yields no regions and falls back to
chunk-and-transcribe — that fallback is the safety net, so do not weaken the rule to
catch more books.

**Adding OCR.** The integration point is `extract.document_from_pages()`, which already
accepts pre-extracted text. An OCR pass ahead of `extract_pdf` in `_ingest_fresh` feeds
it without touching anything downstream — `detect_sections` reads `PageText` and does
not care where the text came from (D31).

### LLM checklist

- [ ] Read §2 — these are not suggestions
- [ ] Does any change concatenate text across pages? (I-corpus-01 — never)
- [ ] Can an empty extraction now look like a success? (I-corpus-02)
- [ ] Does chunking gain a fixed-width path? (I-corpus-03)
- [ ] Does a re-upload add rows instead of copying or rebuilding? (I-corpus-06)
- [ ] Could a page end up in no section? (I-corpus-07)
- [ ] Does anything let an ungrounded provider's output be stored with a page number? (I-corpus-08)

---

## 5 · Privacy & safety

| Data | Where it is handled | Why |
|---|---|---|
| The uploaded PDF | Object storage, tenant-scoped; the ingest loader reads object storage, not the filesystem | A teacher's textbook is their material |
| Extraction prompts | Book text only — no student, no class | I-ai-01 holds trivially here |
| Model calls | Audited as `ModelCall`: hash, tokens, cost. Never content | I-ai-06 |
| A textbook naming a pupil | Scrubbed downstream, where it is used as a style example (`adaptive`) | Swiss textbook prose is full of names that are also on the roster |

**Copyright note.** Crops of a teacher's own textbook stay inside their school's tenant
and are served through a tenant-scoped file route.

---

## 6 · Testing strategy

| Invariant | Proved by |
|---|---|
| I-corpus-01 | `test_chunk.py::test_extracts_text_with_page_numbers`, `::test_page_provenance_survives_and_chunks_never_span_pages` |
| I-corpus-02 | `test_chunk.py::test_a_scanned_book_is_reported_not_silently_empty`, `::test_an_unreadable_file_raises` |
| I-corpus-03 | `test_chunk.py::test_no_exercise_is_split_across_chunks`, `::test_a_chunk_never_holds_only_the_head_of_an_exercise`, `::test_chunk_boundaries_land_on_exercise_starts` |
| I-corpus-04 | `test_chunk.py::test_chunk_sizes_stay_within_the_embedding_budget`, `::test_long_prose_is_split_on_sentence_ends_not_mid_sentence` |
| I-corpus-05 | `test_ingest_regions.py::test_coded_exercises_become_rows_with_crops_without_a_model`, `::test_a_grounded_model_classifies_and_tags_but_does_not_rewrite`, `test_regions_real_book.py` (15 tests against a real book) |
| I-corpus-06 | `test_ingest_regions.py::test_a_second_upload_of_the_same_book_shares_the_crops` |
| I-corpus-07 | `test_source_sections.py::test_every_page_belongs_to_exactly_one_section`, `::test_a_document_with_no_headings_is_still_one_whole_section`, `::test_a_running_head_is_not_a_heading`, `::test_an_exercise_line_is_not_mistaken_for_a_heading` |
| I-corpus-08 | `test_ingest_grounding.py::test_the_offline_provider_returns_nothing_for_grounded_purposes`, `::test_a_prose_only_document_yields_no_invented_exercises` |
| I-corpus-09 | `test_ingest_regions.py::test_without_a_model_the_section_keeps_its_button_and_says_why`, `::test_reading_a_section_on_demand_tags_the_rows_that_are_there` |
| I-corpus-10 | `test_seed_hierarchy.py::test_a_theme_hangs_from_its_own_schools_curriculum`, `::test_every_seeded_theme_has_a_primary_and_it_is_one_of_its_own_tags`, `::test_a_theme_with_no_primary_for_this_curriculum_fails_loudly` |

```bash
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests/test_chunk.py \
  apps/api/tests/test_source_sections.py apps/api/tests/test_ingest_regions.py \
  apps/api/tests/test_regions_real_book.py apps/api/tests/test_ingest_grounding.py -q
```

`test_regions_real_book.py` runs against an actual textbook. It is the reason region
detection can be trusted at all.

---

## Companion documents

- [`architecture.md`](architecture.md) — the pipeline, the two extraction paths, the edge cases
- [`decisions.md`](decisions.md) — D26, D27, D28, D31, D40
- [`../retrieval/`](../retrieval/) — the consumer of everything indexed here
- [`../../rag.md`](../../rag.md), [`../../curriculum.md`](../../curriculum.md)

**Last updated:** 2026-09-09
