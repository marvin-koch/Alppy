"""The layout path through the pipeline: coded exercises become rows with pictures.

The real book is exercised in ``test_regions_real_book.py``. This module runs
the *pipeline* on a three-page PDF drawn here with PyMuPDF, in the MER style —
bookmarks, bold coloured coded headers, a drawn figure, a ``SUITE ▶`` over the
page, a workbook cross-reference — so it stays fast and runs everywhere.

What has to hold:

1. Every coded exercise becomes an ``Exercise`` with its label, its title, its
   text and a PNG crop in object storage, **with no model in the loop**.
2. Sections are the file's bookmarks, not the heading heuristic.
3. A grounded model classifies and tags; without one, the rows still exist
   and the section keeps its button and says why.
4. Reading a section on demand tags the rows that are there instead of
   transcribing the chunks and creating a second set.
5. The web app gets a URL for the picture, and the sheet prints it.
"""

from __future__ import annotations

import io
import json
import uuid

import pytest
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login

from alppy.ai.base import ChatRequest, ChatResponse
from alppy.ai.client import AiClient
from alppy.ingest import pipeline
from alppy.ingest.regions import detect_exercise_regions
from alppy.models import Chapter, Competency, Exercise, Source, SourceSection
from alppy.models.enums import ExerciseOrigin, ExerciseType, JobStatus
from alppy.sheets import render as sheet_render
from alppy.storage import LocalStorage

pymupdf = pytest.importorskip("pymupdf", reason="the region detector needs PyMuPDF")

RED = (0.93, 0.11, 0.14)
INK = (0.14, 0.12, 0.13)
BODY = "helv"
BOLD = "hebo"

# Enough prose per page for `ExtractedDocument.has_text` and for the language
# detector to say "fr" — the pipeline refuses a PDF it reads as a scan.
FILLER = (
    "Dans ce chapitre nous étudions les nombres relatifs et leurs opérations. "
    "Les exercices sont à faire dans le cahier avec les calculs détaillés. "
)


def _page(doc: object, *, running_head: str) -> object:
    page = doc.new_page(width=533, height=757)  # type: ignore[attr-defined]  # pymupdf ships no stubs
    page.insert_text((300, 28), running_head, fontname=BODY, fontsize=10, color=(0.65, 0.66, 0.67))
    return page


def _header(page: object, y: float, code: str, title: str) -> None:
    page.insert_text((60, y), f"{code}  {title}", fontname=BOLD, fontsize=10.5, color=RED)  # type: ignore[attr-defined]


def _body(page: object, y: float, text: str) -> None:
    page.insert_text((45, y), text, fontname=BODY, fontsize=10, color=INK)  # type: ignore[attr-defined]


def coded_book() -> bytes:
    """Three pages: two exercises on page 1 (the second runs over to page 2),
    one on page 2 after a workbook pointer, a section title and one on page 3.
    """
    doc = pymupdf.open()

    one = _page(doc, running_head="10e Nombres et opérations | Nombres relatifs")
    _body(one, 60, FILLER)
    _header(one, 120, "NO1", "Les quatre multiplications")
    _body(one, 145, "Aide-toi de ces quatre égalités pour trouver le résultat.")
    _body(one, 165, "a) (– 8) · (– 5)      b) (+ 12) · (+ 3)")
    _header(one, 230, "NO2", "Rectangle coloré")
    _body(one, 255, "L'unité d'aire est le rectangle extérieur.")
    one.draw_rect(pymupdf.Rect(300, 245, 480, 400), color=INK, fill=(0.2, 0.5, 0.8), width=1)
    _body(one, 290, "a) rouge et bleu ;   b) jaune et vert ;")
    one.insert_text((440, 720), "SUITE", fontname=BOLD, fontsize=10.5, color=RED)

    two = _page(doc, running_head="Nombres relatifs | Nombres et opérations 10e")
    _body(two, 70, "Énonce une règle te permettant d'additionner des fractions.")
    _body(two, 90, "i) 4/5 – 2/5      k) 7/9 – 2/3")
    two.insert_text((400, 130), "Fichier :  NO3 et NO4", fontname=BODY, fontsize=10, color=RED)
    # Intro prose between the cross-reference and the next header: belongs to
    # neither the continued exercise above nor NO5 below.
    _body(two, 150, "Pour consolider, relis la page précédente avant de continuer.")
    _header(two, 170, "NO5", "Quelle somme ?")
    _body(two, 195, "Voici deux procédés pour additionner 3/4 et 4/5. " + FILLER)
    _body(two, 215, "Utilise les deux procédés successivement.")

    three = _page(doc, running_head="10e Fonctions et algèbre | Calcul littéral")
    three.insert_text((58, 100), "Multiplication de monômes", fontname=BOLD, fontsize=19, color=RED)
    _body(three, 130, FILLER)
    _header(three, 170, "FA1", "Équivalentes ?")
    _body(three, 195, "Quelles sont les expressions équivalentes ? a) 3n   n – 3   n : 3")

    doc.set_toc(
        [
            [1, "Nombres et opérations", 1],
            [2, "NO – Nombres relatifs", 1],
            [1, "Fonctions et algèbre", 3],
            [2, "FA – Calcul littéral", 3],
        ]
    )
    payload: bytes = doc.tobytes()
    return payload


class _Classifier:
    """A grounded provider that classifies whatever region text it is shown."""

    name = "stub"
    grounded = True

    def __init__(self) -> None:
        self.seen: list[str] = []

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.seen.append(request.user)
        code = request.user.split("- ", 1)[1].split(" ", 1)[0] if "- " in request.user else ""
        if "NO1 " in request.user:
            body = {
                "type": "mcq",
                "statement": "ignored: the page's own text wins",
                "options": ["40", "– 40", "13"],
                "answer_index": 0,
                "difficulty": 2,
                "competency_codes": [code],
            }
        else:
            body = {"type": "open", "statement": "x", "difficulty": 4, "competency_codes": [code]}
        return ChatResponse(text=json.dumps({"exercises": [body]}), model="stub")


def _source(db: Session, tenant: Tenant, *, sha: str = "c0ded") -> Source:
    source = Source(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        subject_id=tenant.subject.id,
        filename="maths10.pdf",
        storage_key="maths10.pdf",
        content_type="application/pdf",
        size_bytes=1,
        sha256=sha,
        status=JobStatus.QUEUED,
    )
    db.add(source)
    db.flush()
    return source


def _chapter_with(db: Session, tenant: Tenant) -> Chapter:
    competency = db.query(Competency).first()
    assert competency is not None
    chapter = Chapter(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        subject_id=tenant.subject.id,
        key="relatifs",
        labels={"fr": "Nombres relatifs", "de": "Ganze Zahlen", "en": "Integers"},
        position=0,
    )
    chapter.competencies.append(competency)
    db.add(chapter)
    db.flush()
    return chapter


@pytest.fixture
def book() -> bytes:
    return coded_book()


@pytest.fixture
def figures(storage: LocalStorage, monkeypatch: pytest.MonkeyPatch) -> LocalStorage:
    """Point every ``get_storage()`` at the test's own filesystem backend."""
    monkeypatch.setattr(pipeline, "get_storage", lambda: storage)
    monkeypatch.setattr(sheet_render, "get_storage", lambda: storage)
    monkeypatch.setattr("alppy.services.get_storage", lambda: storage)
    return storage


# --------------------------------------------------------------------------
# 1 · The synthetic book is read the way the real one is
# --------------------------------------------------------------------------
def test_the_synthetic_book_is_detected_like_the_real_one(book: bytes) -> None:
    regions = detect_exercise_regions(book)
    assert [r.label for r in regions] == ["NO1", "NO2", "NO5", "FA1"]
    no2 = regions[1]
    assert no2.continues and tuple(p.page for p in no2.parts) == (1, 2)
    assert "rectangle extérieur" in no2.text and "additionner des fractions" in no2.text
    assert "Fichier" not in no2.text and "relis la page" not in no2.text
    assert "Fichier" not in regions[2].text
    assert "Multiplication de monômes" not in regions[2].text, "a title ends the region above"
    assert regions[3].page == 3


# --------------------------------------------------------------------------
# 2 · Rows with pictures, no model needed
# --------------------------------------------------------------------------
def test_coded_exercises_become_rows_with_crops_without_a_model(
    db: Session, tenant: Tenant, book: bytes, figures: LocalStorage
) -> None:
    source = _source(db, tenant)
    client = AiClient()
    assert not client.chat_is_grounded, "the offline provider is the default in tests"

    result = pipeline.run_ingest(db, source_id=source.id, loader=lambda _s: book, ai=client)

    assert result.status is JobStatus.SUCCEEDED
    assert result.exercises_created == 4
    rows = {
        r.label: r
        for r in db.query(Exercise).filter(Exercise.source_id == source.id).all()
    }
    assert set(rows) == {"NO1", "NO2", "NO5", "FA1"}
    no2 = rows["NO2"]
    assert no2.title == "Rectangle coloré"
    assert no2.origin is ExerciseOrigin.TEXTBOOK
    assert no2.type is ExerciseType.OPEN, "unclassified until a model reads it"
    assert no2.source_page == 1
    assert "rectangle extérieur" in no2.statement
    assert no2.approved_at is None

    # The crop is in object storage under a server-built key, and it is a PNG.
    assert no2.figure_key is not None
    assert no2.figure_key.startswith(f"figures/{tenant.school.id}/{source.id}/")
    png = figures.get_bytes(no2.figure_key)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image

    width_px, height_px = Image.open(io.BytesIO(png)).size
    assert no2.figure_width_mm and no2.figure_height_mm
    assert abs(width_px / 200 * 25.4 - no2.figure_width_mm) < 0.5
    assert abs(height_px / 200 * 25.4 - no2.figure_height_mm) < 0.5
    # Two pages stacked: taller than either half on its own.
    assert no2.figure_height_mm > rows["NO1"].figure_height_mm


def test_sections_are_the_files_bookmarks(
    db: Session, tenant: Tenant, book: bytes, figures: LocalStorage
) -> None:
    source = _source(db, tenant)
    pipeline.run_ingest(db, source_id=source.id, loader=lambda _s: book, ai=AiClient())

    sections = (
        db.query(SourceSection)
        .filter(SourceSection.source_id == source.id)
        .order_by(SourceSection.position)
        .all()
    )
    assert [(s.title, s.label, s.page_from, s.page_to) for s in sections] == [
        ("NO – Nombres relatifs", "NO", 1, 2),
        ("FA – Calcul littéral", "FA", 3, 3),
    ]
    by_section = {
        s.title: sorted(
            r.label for r in db.query(Exercise).filter(Exercise.source_section_id == s.id)
        )
        for s in sections
    }
    assert by_section == {
        "NO – Nombres relatifs": ["NO1", "NO2", "NO5"],
        "FA – Calcul littéral": ["FA1"],
    }


def test_without_a_model_the_section_keeps_its_button_and_says_why(
    db: Session, tenant: Tenant, book: bytes, figures: LocalStorage
) -> None:
    source = _source(db, tenant)
    result = pipeline.run_ingest(db, source_id=source.id, loader=lambda _s: book, ai=AiClient())

    assert result.exercises_created == 4
    assert source.notice == pipeline.REGIONS_UNTAGGED_NOTICE
    for section in db.query(SourceSection).filter(SourceSection.source_id == source.id):
        assert section.extracted_at is None, "nothing classified it yet"
        assert section.extraction_notice == pipeline.REGIONS_UNTAGGED_NOTICE


# --------------------------------------------------------------------------
# 3 · A grounded model classifies and tags; the page's own words stay
# --------------------------------------------------------------------------
def test_a_grounded_model_classifies_and_tags_but_does_not_rewrite(
    db: Session, tenant: Tenant, book: bytes, figures: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    chapter = _chapter_with(db, tenant)
    source = _source(db, tenant)
    client = AiClient()
    classifier = _Classifier()
    monkeypatch.setattr(client, "_chat", classifier, raising=False)

    pipeline.run_ingest(db, source_id=source.id, loader=lambda _s: book, ai=client)

    rows = {r.label: r for r in db.query(Exercise).filter(Exercise.source_id == source.id)}
    assert len(rows) == 4
    assert len(classifier.seen) == 4, "one call per exercise, not per chunk"
    assert all(" NO1 " in s or "NO1 " in s for s in classifier.seen[:1])

    no1 = rows["NO1"]
    assert no1.type is ExerciseType.MCQ
    assert no1.options == ["40", "– 40", "13"] and no1.answer_index == 0
    assert no1.difficulty == 2
    assert "Aide-toi de ces quatre égalités" in no1.statement, "the model's statement is ignored"
    assert no1.competencies and no1.chapter_id == chapter.id
    assert rows["NO2"].type is ExerciseType.OPEN and rows["NO2"].difficulty == 4

    for section in db.query(SourceSection).filter(SourceSection.source_id == source.id):
        assert section.extracted_at is not None
    assert source.notice is None


def test_reading_a_section_on_demand_tags_the_rows_that_are_there(
    db: Session, tenant: Tenant, book: bytes, figures: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Import without a model, configure one, open the chapter: the four rows
    are classified in place. No transcription, no second copy of anything."""
    source = _source(db, tenant)
    pipeline.run_ingest(db, source_id=source.id, loader=lambda _s: book, ai=AiClient())
    section = (
        db.query(SourceSection)
        .filter(SourceSection.source_id == source.id, SourceSection.label == "NO")
        .one()
    )
    assert section.extracted_at is None

    client = AiClient()
    monkeypatch.setattr(client, "_chat", _Classifier(), raising=False)
    result = pipeline.extract_section(db, section_id=section.id, ai=client)

    assert not result.skipped
    assert result.exercises_created == 0, "nothing new: the rows already existed"
    assert result.exercises_total == 3
    assert db.query(Exercise).filter(Exercise.source_id == source.id).count() == 4
    assert section.extracted_at is not None
    no1 = db.query(Exercise).filter(Exercise.source_id == source.id, Exercise.label == "NO1").one()
    assert no1.type is ExerciseType.MCQ


def test_a_second_upload_of_the_same_book_shares_the_crops(
    db: Session, tenant: Tenant, book: bytes, figures: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _chapter_with(db, tenant)
    first = _source(db, tenant, sha="same")
    tagged = AiClient()
    monkeypatch.setattr(tagged, "_chat", _Classifier(), raising=False)
    pipeline.run_ingest(db, source_id=first.id, loader=lambda _s: book, ai=tagged)
    second = _source(db, tenant, sha="same")
    result = pipeline.run_ingest(db, source_id=second.id, loader=lambda _s: book, ai=AiClient())

    assert result.reused_from_source_id == first.id
    copied = {r.label: r for r in db.query(Exercise).filter(Exercise.source_id == second.id)}
    original = {r.label: r for r in db.query(Exercise).filter(Exercise.source_id == first.id)}
    assert set(copied) == set(original) == {"NO1", "NO2", "NO5", "FA1"}
    for label, row in copied.items():
        assert row.figure_key == original[label].figure_key
        assert row.title == original[label].title
        assert row.figure_height_mm == original[label].figure_height_mm
        assert row.type is original[label].type
        assert [c.id for c in row.competencies] == [c.id for c in original[label].competencies]
        assert row.competencies, "the tags travel with the copy"


# --------------------------------------------------------------------------
# 4 · The picture reaches the web app and the paper
# --------------------------------------------------------------------------
def test_the_api_lists_the_label_title_and_a_picture_url(
    client, db: Session, tenant: Tenant, book: bytes, figures: LocalStorage
) -> None:
    source = _source(db, tenant)
    pipeline.run_ingest(db, source_id=source.id, loader=lambda _s: book, ai=AiClient())
    login(client, tenant.teacher.email)

    listed = client.get(f"/api/v1/sources/{source.id}/exercises", params={"q": "NO2"}).json()
    assert listed["total"] == 1, "the search matches the book's own code"
    item = listed["items"][0]
    assert (item["label"], item["title"]) == ("NO2", "Rectangle coloré")
    assert item["figure_url"].startswith("/api/v1/files/figures/")
    assert item["figure_width_mm"] > 100

    picture = client.get(item["figure_url"])
    assert picture.status_code == 200
    assert picture.headers["content-type"] == "image/png"
    assert picture.content[:4] == b"\x89PNG"

    by_title = client.get(
        f"/api/v1/sources/{source.id}/exercises", params={"q": "coloré"}
    ).json()
    assert by_title["total"] == 1


def test_the_sheet_prints_the_picture_in_place_of_the_statement(
    client, db: Session, tenant: Tenant, book: bytes, figures: LocalStorage
) -> None:
    source = _source(db, tenant)
    pipeline.run_ingest(db, source_id=source.id, loader=lambda _s: book, ai=AiClient())
    no2 = db.query(Exercise).filter(Exercise.source_id == source.id, Exercise.label == "NO2").one()
    login(client, tenant.teacher.email)

    response = client.post(
        "/api/v1/sheets/preview",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Nombres relatifs",
            "language": "fr",
            "items": [{"exercise_id": str(no2.id), "position": 0}],
        },
    )
    assert response.status_code == 200, response.text
    html = response.text
    assert 'data-figure="true"' in html
    assert '<img class="sheet-figure" src="data:image/png;base64,' in html
    # The text is there for a reader without images, not printed twice.
    assert "rectangle extérieur" in html
    assert html.count("rectangle extérieur") == 1
    assert 'alt="' in html


def test_the_teachers_wording_prints_above_the_picture(
    client, db: Session, tenant: Tenant, book: bytes, figures: LocalStorage
) -> None:
    source = _source(db, tenant)
    pipeline.run_ingest(db, source_id=source.id, loader=lambda _s: book, ai=AiClient())
    no1 = db.query(Exercise).filter(Exercise.source_id == source.id, Exercise.label == "NO1").one()
    login(client, tenant.teacher.email)

    response = client.post(
        "/api/v1/sheets/preview",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Nombres relatifs",
            "language": "fr",
            "items": [
                {
                    "exercise_id": str(no1.id),
                    "position": 0,
                    "statement_override": "Fais seulement a) et b), sans calculatrice.",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    html = response.text
    assert "sans calculatrice" in html
    assert '<img class="sheet-figure"' in html


def test_a_missing_crop_prints_the_text_and_says_so_in_the_log(
    client, db: Session, tenant: Tenant, book: bytes, figures: LocalStorage
) -> None:
    source = _source(db, tenant)
    pipeline.run_ingest(db, source_id=source.id, loader=lambda _s: book, ai=AiClient())
    no5 = db.query(Exercise).filter(Exercise.source_id == source.id, Exercise.label == "NO5").one()
    no5.figure_key = f"figures/{tenant.school.id}/{source.id}/gone.png"
    db.commit()
    login(client, tenant.teacher.email)

    from structlog.testing import capture_logs

    with capture_logs() as logged:
        response = client.post(
            "/api/v1/sheets/preview",
            json={
                "class_id": str(tenant.school_class.id),
                "subject_id": str(tenant.subject.id),
                "title": "Nombres relatifs",
                "language": "fr",
                "items": [{"exercise_id": str(no5.id), "position": 0}],
            },
        )
    assert response.status_code == 200, response.text
    assert '<img class="sheet-figure"' not in response.text
    assert "deux procédés" in response.text
    assert any(
        entry["event"] == "sheets.figure.unreadable" and entry["log_level"] == "warning"
        for entry in logged
    ), logged
