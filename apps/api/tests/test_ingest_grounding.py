"""Extraction must never invent, and what it does extract must be findable.

Two failures live here, both of which shipped green:

1. The offline chat provider does not read its prompt — its output is a
   function of the prompt's hash — and it was allowed to serve extraction. A
   PDF containing only prose produced five "Calcule 4 × 3." exercises, stored
   with ``origin=TEXTBOOK`` and the teacher's real filename and page number.
   That combination is exempt from the approval gate and carries no accent, so
   nothing anywhere said a model wrote them.

2. Extracted exercises were given no chapter and no competency, which makes
   them invisible to the builder's chapter filter — the only way a teacher
   finds them.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant

from alppy.ai.base import ChatRequest
from alppy.ai.client import AiClient
from alppy.ai.providers import TRANSCRIPTION_PURPOSES, EchoChatProvider
from alppy.ingest import pipeline
from alppy.ingest.extract import PageText, document_from_pages
from alppy.models import Chapter, Competency, Exercise, Source
from alppy.models.enums import JobStatus

PROSE = (
    "Ce chapitre presente la notion de proportionnalite dans la vie courante. "
    "On y lit des exemples et des explications, mais aucune question posee a "
    "l'eleve. Rien ici n'est un exercice a resoudre. "
) * 6


# --------------------------------------------------------------------------
# 1 · The offline provider refuses to transcribe
# --------------------------------------------------------------------------
def test_the_offline_provider_returns_nothing_for_transcription() -> None:
    provider = EchoChatProvider()
    assert provider.grounded is False
    for purpose in TRANSCRIPTION_PURPOSES:
        response = provider.complete(
            ChatRequest(system="s", user="a page of a real textbook", purpose=purpose)
        )
        assert '"exercises": []' in response.text.replace(" ", "").replace('":[]', '": []')


def test_the_offline_provider_still_generates_when_asked_to_author() -> None:
    """Generation is where inventing is the point; only transcription is refused."""
    response = EchoChatProvider().complete(
        ChatRequest(system="s", user="write exercises", purpose="generate_exercises")
    )
    assert '"statement"' in response.text


def test_a_prose_only_document_yields_no_invented_exercises(
    db: Session, tenant: Tenant, monkeypatch
) -> None:
    source = Source(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        subject_id=tenant.subject.id,
        filename="prose.pdf",
        storage_key="prose.pdf",
        content_type="application/pdf",
        size_bytes=1,
        sha256="deadbeef",
        status=JobStatus.QUEUED,
    )
    db.add(source)
    db.flush()

    document = document_from_pages([PageText(page=1, text=PROSE)])
    monkeypatch.setattr(pipeline, "extract_pdf", lambda _data: document)

    result = pipeline.run_ingest(db, source_id=source.id, loader=lambda _s: b"%PDF-")

    assert result.status is JobStatus.SUCCEEDED
    assert result.chunks_created > 0, "the document is still indexed for search"
    assert result.exercises_created == 0, "nothing may be invented from prose"
    db.refresh(source)
    # A green tick with zero exercises has to explain itself.
    assert source.notice == pipeline.NO_GROUNDED_MODEL_NOTICE
    assert db.query(Exercise).filter(Exercise.source_id == source.id).count() == 0


# --------------------------------------------------------------------------
# 2 · What is extracted carries curriculum tags
# --------------------------------------------------------------------------
class _GroundedProvider:
    """Returns one exercise tagged with whatever code it was offered."""

    name = "stub"
    grounded = True

    def complete(self, request: ChatRequest):  # type: ignore[no-untyped-def]
        from alppy.ai.base import ChatResponse

        code = request.user.split("- ", 1)[1].split(" ", 1)[0] if "- " in request.user else ""
        return ChatResponse(
            text=(
                '{"exercises": [{"type": "open", "statement": '
                '"Calcule le perimetre de ce rectangle.", "difficulty": 2, '
                f'"competency_codes": ["{code}"]}}]}}'
            ),
            model="stub",
        )


def test_extracted_exercises_are_tagged_with_a_chapter_and_a_competency(
    db: Session, tenant: Tenant, monkeypatch
) -> None:
    competency = db.query(Competency).first()
    assert competency is not None
    chapter = Chapter(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        subject_id=tenant.subject.id,
        key="perimeters",
        labels={"fr": "Périmètres", "de": "Umfang", "en": "Perimeters"},
        position=0,
    )
    chapter.competencies.append(competency)
    db.add(chapter)
    db.flush()

    source = Source(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        subject_id=tenant.subject.id,
        filename="book.pdf",
        storage_key="book.pdf",
        content_type="application/pdf",
        size_bytes=1,
        sha256="cafe",
        status=JobStatus.QUEUED,
    )
    db.add(source)
    db.flush()

    text = "1. Calcule le perimetre de ce rectangle de 3 cm sur 4 cm. " * 12
    monkeypatch.setattr(
        pipeline, "extract_pdf", lambda _d: document_from_pages([PageText(page=7, text=text)])
    )
    client = AiClient()
    monkeypatch.setattr(client, "_chat", _GroundedProvider(), raising=False)

    pipeline.run_ingest(db, source_id=source.id, loader=lambda _s: b"%PDF-", ai=client)

    rows = db.query(Exercise).filter(Exercise.source_id == source.id).all()
    assert rows, "a grounded provider should produce exercises"
    for row in rows:
        assert row.source_page == 7, "provenance must point at the real page"
        assert row.competencies, "an untagged exercise is invisible to the chapter filter"
        assert row.chapter_id == chapter.id


# --------------------------------------------------------------------------
# 3 · The audit trail exists, and carries no content
# --------------------------------------------------------------------------
def test_model_calls_are_recorded_without_any_content(
    db: Session, tenant: Tenant, monkeypatch
) -> None:
    """`ModelCall` was declared, exported and never written by anything: after
    a full ingestion run the table was empty, so the audit trail privacy.md
    relies on did not exist."""
    from alppy.models import ModelCall

    source = Source(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        subject_id=tenant.subject.id,
        filename="audited.pdf",
        storage_key="audited.pdf",
        content_type="application/pdf",
        size_bytes=1,
        sha256="feed",
        status=JobStatus.QUEUED,
    )
    db.add(source)
    db.flush()

    text = "1. Calcule le perimetre de ce rectangle de 3 cm sur 4 cm. " * 12
    monkeypatch.setattr(
        pipeline, "extract_pdf", lambda _d: document_from_pages([PageText(page=1, text=text)])
    )
    client = AiClient()
    monkeypatch.setattr(client, "_chat", _GroundedProvider(), raising=False)
    pipeline.run_ingest(db, source_id=source.id, loader=lambda _s: b"%PDF-", ai=client)

    rows = db.query(ModelCall).filter(ModelCall.school_id == tenant.school.id).all()
    assert rows, "every model call has to leave a row"

    columns = {c.name for c in ModelCall.__table__.columns}
    assert not (columns & {"prompt", "system", "user", "content", "response", "text"})
    for row in rows:
        assert row.purpose == "extract_exercises"
        assert len(row.prompt_sha256) == 64
        assert row.prompt_name == "extract_exercises"
