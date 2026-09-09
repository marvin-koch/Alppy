# Corpus Architecture

## Component diagram

```
  POST /sources (PDF + subject)
        │  validated: really a PDF, under the size cap, subject in this school
        ▼
  Source(status=QUEUED, sha256) + Job(INGEST_SOURCE)      ← the request ends here
        │
        ▼  arq worker
  ingest/pipeline.py::run_ingest
        │
        ├─ _ingested_twin(sha256)?  ──▶ _copy_from_twin   zero model calls   (I-corpus-06)
        ├─ partial previous run?    ──▶ _wipe, then rebuild
        │
        └─ _ingest_fresh
             ├─ extract.extract_pdf → PageText[]
             │      has_text is False → Source.status=FAILED, Source.error   (I-corpus-02)
             │
             ├─ sections.detect_sections → SourceSection[]   contiguous, gapless
             │
             ├─ chunk.chunk_pages → Chunk[]  → ai.embed → SourceChunk(vector(1024))
             │
             ├─ regions.detect_regions → Exercise + figure crop   (no model)  (I-corpus-05)
             │
             └─ _extract_eagerly       model transcription, budget MAX_EXTRACTION_CHUNKS
                   stops BEFORE a section it cannot finish whole            (I-corpus-09)
        ▼
  Source(status=SUCCEEDED, page_count, language)
        │
        └─ later: POST /sources/{id}/sections/{sid}/extract → Job(EXTRACT_SECTION)
                     ├─ _existing_statements  (de-dupe against the DATABASE)
                     └─ SourceSection.extracted_at = now
```

## Data flow

### Two extraction paths, and why both exist

| | **Regions** (`regions.py`) | **Transcription** (`_extract_*`) |
|---|---|---|
| Trigger | The book uses coded headers (`NO64`) | Everything else |
| Method | Typographic: bold, coloured, body-sized line opening with a short code | A model reads the chunk |
| Output | A row plus an **image crop of the page** | A row with transcribed text |
| Model? | **None.** Deterministic | Yes, and grounded-only |
| Cost | Embeddings only | One call per chunk, budgeted |

A Romandy maths exercise is often a figure, a table, a column of fractions or a photo
of a newspaper clipping. Handing that body to a language model as extracted text loses
exactly the part the student is meant to look at, and a transcription of `3n²/n` has no
way of being "precise". So regions does the one thing a model cannot: it finds where
each exercise **is** and cuts it out.

The rule is **typographic, not lexical**. A region runs from its header to the next
header, to the book's own cross-reference line (`Fichier : …`), to a section title, or
to the end of the page's content — whichever comes first. An exercise continuing over a
page is stitched back together: the book marks it `SUITE ▶`, and the continuation is
the body text above the next page's first header.

Everything in `regions.py` is a pure function over bytes. It reaches no database and no
network.

### Chunking

```python
TARGET_CHARS = 650        # aim
# floor:   large enough for an exercise plus the instruction line above it
# ceiling: comfortably under the 512-token truncation of multilingual-e5-large
```

The chunker treats the start of a numbered exercise as a **preferred break point**, and
never breaks *into* one when it can break *before* one instead. Two things depend on
that:

- **Retrieval.** Half a statement embeds as a fragment — "Calcule l'aire d'un triangle
  rectangle dont les cathètes mesurent" and "6 cm et 8 cm." are two vectors, neither
  close to a query about areas.
- **Extraction.** The prompt is explicitly told not to invent. Handed half an exercise
  it correctly refuses, so the exercise is lost from **both** halves — a silent 100 %
  loss on that item, not a degradation.

Chunks never span a page: page provenance is the whole point, and a chunk covering
pages 12–13 can only report one of them honestly.

### Sections vs chapters — two different axes

| | `SourceSection` | `Chapter` |
|---|---|---|
| What | A fact about the file: "4 · Les fractions, p. 112–131" | The teacher's grouping, tied to curriculum competencies |
| Needs setup? | No | Yes: create chapters, give them codes, and the extraction must tag the item |
| Nullable for an exercise? | No | **Yes, legitimately** |
| Role in the builder | **Primary** filter | Secondary — the only thing that answers "fractions across every book I own" |

Heading detection is deliberately conservative: short, alone on its line, and either
carrying an explicit chapter word ("Chapitre 4", "Kapitel 7", "Unit 3") or a bare number
followed by a title-cased phrase. Running heads are detected by repetition and dropped.
A false heading shatters the outline into noise, which is worse than a coarse outline: a
teacher can scroll twenty pages inside a correct chapter and cannot find anything in
ninety spurious ones.

### Language detection

A stopword frequency count over three near-disjoint 60-word sets. It is not a language
model and does not need to be: the question is only "fr, de or en?" over hundreds of
words. `langdetect` or `fasttext` would add tens of megabytes for a decision a lookup
table already gets right — and it declines to guess on too little text rather than
picking one.

## Edge cases

- **An image-only PDF.** → `has_text` is False → `Source.status = FAILED` with an error
  the teacher can read. Not a green tick over nothing (I-corpus-02).
- **The same file uploaded twice in one school.** → chunks and exercises are copied from
  the twin. Zero model calls.
- **A previous run that failed halfway.** → its rows are deleted and rebuilt, never
  added to.
- **A 400-page textbook nobody teaches from.** → indexed and searchable for the price of
  embeddings; chapter 19 is never sent to a model unless someone opens it (D27).
- **A chunk straddling two sections.** → de-duplication reads the **database**
  (`_existing_statements`), not a per-run set, because sections are extracted separately
  and their page ranges abut.
- **A document with no recognisable headings.** → one section covering the whole file.
- **Pages before the first heading.** → a leading section (a preface, a contents table),
  never dropped, so no exercise ends up with a null section.
- **A prose-only document on a grounded provider.** → no exercises, honestly.
- **An ungrounded provider.** → no exercises at all, and the section keeps its button
  and says why.
- **A teacher-written exercise.** → `ExerciseOrigin.TEACHER`, `approved_at` stamped at
  creation (D28).

---

**Companion:** [`README.md`](README.md) §2 for the load-bearing rules.
