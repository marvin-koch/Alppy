"""PDF ingestion: extract -> chunk -> embed -> extract exercises.

The three stages are separate modules on purpose. Extraction and chunking are
pure functions over bytes and strings, so they are unit-testable without a
database, without a model provider and without Postgres; only
``pipeline.ingest_source`` touches the session.
"""

from __future__ import annotations

from alppy.ingest.chunk import Chunk, chunk_pages, is_exercise_start
from alppy.ingest.extract import (
    ExtractedDocument,
    PageText,
    PdfExtractionError,
    detect_language,
    extract_pdf,
)
from alppy.ingest.pipeline import (
    NO_TEXT_LAYER_ERROR,
    IngestResult,
    ingest_source,
)
from alppy.ingest.regions import ExerciseRegion, detect_exercise_regions, render_region

__all__ = [
    "NO_TEXT_LAYER_ERROR",
    "Chunk",
    "ExerciseRegion",
    "ExtractedDocument",
    "IngestResult",
    "PageText",
    "PdfExtractionError",
    "chunk_pages",
    "detect_exercise_regions",
    "detect_language",
    "extract_pdf",
    "ingest_source",
    "is_exercise_start",
    "render_region",
]
