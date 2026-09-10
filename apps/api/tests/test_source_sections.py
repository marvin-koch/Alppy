"""The builder's navigation of a large document, and what it must never do.

A textbook holds well over a thousand exercises. Three things had to hold before
the sheet builder could offer it as something to pick from:

1. **No exercise may be unreachable.** ``Exercise.chapter_id`` is inferred from
   competency overlap and is legitimately ``NULL``; ``source_section_id`` is a
   fact about the file and must not be. A filter whose primary axis can hide
   rows is worse than no filter.
2. **The list may not arrive in one piece.** The old endpoint returned every row
   of a document in a single array.
3. **The rest of the book must be reachable without splitting the PDF**, which
   is what the old per-upload extraction ceiling forced.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_exercise

from alppy.ingest.extract import PageText
from alppy.ingest.sections import detect_sections
from alppy.models import Exercise, Source, SourceSection
from alppy.models.enums import ExerciseOrigin, ExerciseType, JobStatus


# --------------------------------------------------------------------------
# 1 · Reading the document's own outline
# --------------------------------------------------------------------------
def _pages(*texts: str, start: int = 1) -> list[PageText]:
    return [PageText(page=start + i, text=t) for i, t in enumerate(texts)]


def test_headings_become_sections_with_honest_page_ranges() -> None:
    sections = detect_sections(
        _pages(
            "Chapitre 1 — Les nombres entiers\nUn nombre entier est...",
            "1. Calcule 12 + 8.\n2. Calcule 45 - 17.",
            "4 Les fractions\nUne fraction represente une part.",
            "1. Simplifie 12/18.",
        )
    )
    assert [(s.label, s.title) for s in sections] == [
        ("1", "Les nombres entiers"),
        ("4", "Les fractions"),
    ]
    assert (sections[0].page_from, sections[0].page_to) == (1, 2)
    assert (sections[1].page_from, sections[1].page_to) == (3, 4)


def test_every_page_belongs_to_exactly_one_section() -> None:
    """Gapless and non-overlapping, or an exercise falls between two chapters
    and disappears from the only filter that would have found it."""
    sections = detect_sections(
        _pages(
            "Preface\nCe manuel accompagne le cycle 3.",
            "Chapitre 2 — Les decimaux\nUn nombre decimal...",
            "1. Calcule 0,5 + 0,25.",
        )
    )
    covered = [p for s in sections for p in range(s.page_from, s.page_to + 1)]
    assert covered == sorted(covered), "sections must be in page order"
    assert covered == list(range(1, 4)), "every page covered exactly once"


def test_an_exercise_line_is_not_mistaken_for_a_heading() -> None:
    """``4. Calcule le perimetre`` has the shape of a numbered heading. It is an
    exercise, and treating it as a chapter would shatter the outline into
    hundreds of one-page sections that hold nothing."""
    sections = detect_sections(
        _pages(
            "4. Calcule le perimetre de ce rectangle.",
            "5. Determine l'aire du triangle.",
            "6. Explique ta demarche en une phrase.",
        )
    )
    assert len(sections) == 1, [s.title for s in sections]


def test_a_document_with_no_headings_is_still_one_whole_section() -> None:
    """A worksheet, or a book whose titles are images. Falling back to a single
    section keeps every exercise reachable; returning none would not."""
    sections = detect_sections(_pages("Revision des fractions pour lundi.", start=7))
    assert len(sections) == 1
    assert (sections[0].page_from, sections[0].page_to) == (7, 7)


def test_a_running_head_is_not_a_heading() -> None:
    """The book's own title repeated at the top of every page."""
    head = "Chapitre 3 — Geometrie"
    sections = detect_sections(
        _pages(*[f"{head}\nPage de contenu numero {i}." for i in range(8)])
    )
    assert len(sections) == 1, "a line on every page is furniture, not a chapter"


# --------------------------------------------------------------------------
# 2 · The endpoints the builder drives
# --------------------------------------------------------------------------
def _source(db: Session, tenant: Tenant, *, sha: str = "abc") -> Source:
    source = Source(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        subject_id=tenant.subject.id,
        filename="maths7.pdf",
        storage_key="maths7.pdf",
        content_type="application/pdf",
        size_bytes=1,
        sha256=sha,
        status=JobStatus.SUCCEEDED,
        page_count=40,
    )
    db.add(source)
    db.flush()
    return source


def _section(
    db: Session,
    tenant: Tenant,
    source: Source,
    *,
    title: str,
    position: int,
    page_from: int,
    page_to: int,
    extracted: bool = True,
) -> SourceSection:
    from datetime import UTC, datetime

    section = SourceSection(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        source_id=source.id,
        title=title,
        label=str(position + 1),
        page_from=page_from,
        page_to=page_to,
        position=position,
        extracted_at=datetime.now(UTC) if extracted else None,
    )
    db.add(section)
    db.flush()
    return section


@pytest.fixture
def book(db: Session, tenant: Tenant) -> tuple[Source, list[SourceSection]]:
    source = _source(db, tenant)
    sections = [
        _section(db, tenant, source, title="Les fractions", position=0, page_from=1, page_to=20),
        _section(db, tenant, source, title="Proportionnalite", position=1, page_from=21, page_to=40),
    ]
    for index in range(25):
        exercise = make_exercise(
            db,
            tenant,
            statement=f"Exercice numero {index} sur les fractions.",
            kind=(
                ExerciseType.MCQ
                if index % 3 == 0
                else ExerciseType.TRUE_FALSE
                if index % 3 == 1
                else ExerciseType.OPEN
            ),
            answer_index=1 if index % 3 == 0 else None,
            answer_bool=True if index % 3 == 1 else None,
            difficulty=(index % 5) + 1,
        )
        exercise.source_id = source.id
        exercise.source_section_id = sections[0].id
        exercise.source_page = 1 + (index % 20)
    db.commit()
    return source, sections


def test_sections_are_listed_with_their_exercise_counts(
    client, db: Session, tenant: Tenant, book
) -> None:
    source, _sections = book
    login(client, tenant.teacher.email)

    response = client.get(f"/api/v1/sources/{source.id}/sections")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [s["title"] for s in body] == ["Les fractions", "Proportionnalite"]
    assert body[0]["exercise_count"] == 25
    assert body[1]["exercise_count"] == 0
    assert body[0]["extracted_at"] is not None


def test_exercise_listing_is_paginated_not_the_whole_document(
    client, db: Session, tenant: Tenant, book
) -> None:
    """The old shape returned every row. Twenty-five is small; a textbook is
    not, and the wire format has to be the same either way."""
    source, _ = book
    login(client, tenant.teacher.email)

    response = client.get(f"/api/v1/sources/{source.id}/exercises", params={"limit": 10})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["items"]) == 10
    assert body["total"] == 25
    assert body["limit"] == 10 and body["offset"] == 0

    second = client.get(
        f"/api/v1/sources/{source.id}/exercises", params={"limit": 10, "offset": 10}
    ).json()
    first_ids = {e["id"] for e in body["items"]}
    assert not (first_ids & {e["id"] for e in second["items"]}), "pages must not overlap"


def test_filters_narrow_the_page_and_facets_ignore_the_type_filter(
    client, db: Session, tenant: Tenant, book
) -> None:
    """A type chip has to report what selecting it would give. Counting facets
    *after* applying the type filter would make every unselected chip read 0."""
    source, sections = book
    login(client, tenant.teacher.email)

    unfiltered = client.get(f"/api/v1/sources/{source.id}/exercises").json()
    facets = unfiltered["facets"]
    assert facets["total"] == 25
    assert facets["mcq"] + facets["true_false"] + facets["open"] == 25

    mcq = client.get(
        f"/api/v1/sources/{source.id}/exercises", params={"type": "mcq"}
    ).json()
    assert mcq["total"] == facets["mcq"]
    assert {e["type"] for e in mcq["items"]} == {"mcq"}
    assert mcq["facets"] == facets, "facets must not collapse when a type is picked"

    by_section = client.get(
        f"/api/v1/sources/{source.id}/exercises",
        params={"section_id": str(sections[1].id)},
    ).json()
    assert by_section["total"] == 0


def test_search_matches_the_statement(client, db: Session, tenant: Tenant, book) -> None:
    source, _ = book
    login(client, tenant.teacher.email)
    found = client.get(
        f"/api/v1/sources/{source.id}/exercises", params={"q": "numero 7 "}
    ).json()
    assert found["total"] == 1
    assert "numero 7" in found["items"][0]["statement"]


def test_extracting_a_section_needs_the_document_indexed(
    client, db: Session, tenant: Tenant
) -> None:
    source = _source(db, tenant, sha="pending")
    source.status = JobStatus.QUEUED
    section = _section(
        db, tenant, source, title="Les fractions", position=0, page_from=1, page_to=9,
        extracted=False,
    )
    db.commit()
    login(client, tenant.teacher.email)

    response = client.post(f"/api/v1/sources/{source.id}/sections/{section.id}/extract")
    assert response.status_code == 422, response.text


def test_a_section_of_another_school_is_not_found(
    client, db: Session, tenant: Tenant, other_tenant: Tenant, book
) -> None:
    source, sections = book
    login(client, other_tenant.teacher.email)
    assert client.get(f"/api/v1/sources/{source.id}/sections").status_code == 404
    assert (
        client.post(
            f"/api/v1/sources/{source.id}/sections/{sections[0].id}/extract"
        ).status_code
        == 404
    )


# --------------------------------------------------------------------------
# 3 · The teacher's own exercises
# --------------------------------------------------------------------------
def test_a_hand_written_exercise_is_neither_textbook_nor_ai(
    client, db: Session, tenant: Tenant
) -> None:
    """It carries no page to audit against a book, so calling it a textbook
    transcription would be a lie; and the mandarin accent means "a model wrote
    this", so calling it AI-generated would spend that signal on a human."""
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/exercises",
        json={
            "subject_id": str(tenant.subject.id),
            "type": "true_false",
            "language": "fr",
            "statement": "6/9 et 2/3 sont deux ecritures de la meme fraction.",
            "answer_bool": True,
            "difficulty": 2,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["origin"] == "teacher"
    assert body["source_id"] is None and body["source_page"] is None
    # Written by the teacher, so it passes the print gate by construction.
    assert body["approved_at"] is not None

    row = db.get(Exercise, uuid.UUID(body["id"]))
    assert row is not None and row.origin is ExerciseOrigin.TEACHER


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        (
            {"type": "mcq", "options": ["2/3"], "answer_index": 0},
            "one option is not a choice",
        ),
        (
            {"type": "mcq", "options": ["2/3", "3/4"], "answer_index": 7},
            "the key must point at an option that exists",
        ),
        ({"type": "mcq", "options": ["2/3", "3/4"]}, "an MCQ with no key prints a blank corrigé"),
        ({"type": "true_false"}, "a true/false with no answer cannot be graded"),
    ],
)
def test_a_manual_exercise_whose_answer_does_not_fit_its_type_is_refused(
    client, tenant: Tenant, payload: dict, why: str
) -> None:
    """Coercing instead of refusing produces a sheet whose answer key is blank
    for that item, discovered by the teacher at the photocopier."""
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/exercises",
        json={
            "subject_id": str(tenant.subject.id),
            "language": "fr",
            "statement": "Une question.",
            **payload,
        },
    )
    assert response.status_code == 422, f"{why}: {response.text}"


def test_a_manual_mcq_cannot_claim_more_options_than_the_grid_prints(
    client, tenant: Tenant
) -> None:
    """``sheets.layout.MAX_OPTIONS`` bubbles are printed. A fifth option would
    key the answer to a bubble that is not on the paper."""
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/exercises",
        json={
            "subject_id": str(tenant.subject.id),
            "type": "mcq",
            "language": "fr",
            "statement": "Quelle fraction vaut 0,4 ?",
            "options": ["1/4", "2/5", "4/10", "3/8", "5/12"],
            "answer_index": 1,
        },
    )
    assert response.status_code == 422, response.text


def test_an_open_answer_can_be_corrected_after_extraction(
    client, db: Session, tenant: Tenant
) -> None:
    """``answer_text`` and ``answer_bool`` were absent from ``ExerciseUpdate``,
    so what the answer key prints could be written by extraction and never
    fixed by the teacher who spotted it was wrong."""
    exercise = make_exercise(
        db, tenant, statement="Explique ta demarche.", kind=ExerciseType.OPEN,
        answer_index=None,
    )
    login(client, tenant.teacher.email)
    response = client.patch(
        f"/api/v1/exercises/{exercise.id}",
        json={"answer_text": "Mettre au meme denominateur."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["answer_text"] == "Mettre au meme denominateur."


@pytest.mark.parametrize(
    ("field", "value", "why"),
    [
        (
            "statement",
            "x" * 4001,
            "a statement the renderer must paginate is bounded on the way in",
        ),
        (
            "options",
            ["1/4", "2/5", "4/10", "3/8", "5/12"],
            "a fifth option keys the answer to a bubble the grid does not print",
        ),
        ("statement", "", "an empty statement prints an item with nothing to answer"),
    ],
)
def test_an_edit_cannot_smuggle_in_what_a_creation_would_refuse(
    client, db: Session, tenant: Tenant, field: str, value: object, why: str
) -> None:
    """`ExerciseUpdate` carries `ExerciseCreate`'s bounds, field for field.

    The row a PATCH lands in is the row the sheet renderer paginates and the
    printed grid draws its bubbles from, so a bound that only guards POST guards
    nothing: extraction writes the row, and the teacher's correction is the write
    that actually reaches it.
    """
    exercise = make_exercise(db, tenant, statement="Simplifie 12/18.")
    login(client, tenant.teacher.email)

    created = client.post(
        "/api/v1/exercises",
        json={
            "subject_id": str(tenant.subject.id),
            "type": "mcq",
            "language": "fr",
            "statement": "Quelle fraction vaut 0,4 ?",
            "options": ["1/4", "2/5"],
            "answer_index": 0,
            field: value,
        },
    )
    assert created.status_code == 422, f"{why} (POST): {created.text}"

    patched = client.patch(f"/api/v1/exercises/{exercise.id}", json={field: value})
    assert patched.status_code == 422, f"{why} (PATCH): {patched.text}"

    db.refresh(exercise)
    assert exercise.statement == "Simplifie 12/18."


# --------------------------------------------------------------------------
# 4 · Previewing a sheet that does not exist yet
# --------------------------------------------------------------------------
def test_a_draft_is_previewed_without_writing_anything(
    client, db: Session, tenant: Tenant
) -> None:
    """The teacher sees the paper while still reordering. The alternative was a
    real draft `Sheet` PATCHed on every edit, which writes one `SheetInstance`
    per student per keystroke and abandons a row when they change their mind."""
    from alppy.models import Sheet

    first = make_exercise(db, tenant, statement="Simplifie la fraction 12/18.")
    second = make_exercise(
        db, tenant, statement="3/4 est plus grand que 2/3.",
        kind=ExerciseType.TRUE_FALSE, answer_index=None, answer_bool=True,
    )
    login(client, tenant.teacher.email)

    before = db.query(Sheet).count()
    response = client.post(
        "/api/v1/sheets/preview",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Fractions — revision",
            "language": "fr",
            "items": [
                {"exercise_id": str(second.id), "position": 0},
                {"exercise_id": str(first.id), "position": 1},
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert "Fractions" in html
    assert "3/4 est plus grand" in html
    # Position, not insertion order: the true/false item was sent first.
    assert html.index("3/4 est plus grand") < html.index("Simplifie la fraction")
    assert db.query(Sheet).count() == before, "a preview must persist nothing"


def test_a_draft_preview_uses_the_teachers_wording(
    client, db: Session, tenant: Tenant
) -> None:
    exercise = make_exercise(db, tenant, statement="Calcule 2/5 + 1/5.")
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/sheets/preview",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Revision",
            "language": "fr",
            "items": [
                {
                    "exercise_id": str(exercise.id),
                    "position": 0,
                    "statement_override": "Calcule 2/5 + 1/5. Donne le resultat simplifie.",
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    assert "Donne le resultat simplifie" in response.text


def test_an_empty_draft_says_why_instead_of_five_hundred(
    client, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/sheets/preview",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "",
            "language": "fr",
            "items": [],
        },
    )
    assert response.status_code == 422, response.text


def test_a_manual_exercise_cannot_borrow_another_school_s_subject(
    client, db: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    """`db.get(Subject, id)` looks up by primary key alone.

    Used on its own it accepts any subject id, so an exercise could be created
    with this school's `school_id` and a foreign key pointing across the tenant
    boundary — right on the one table the sheet builder writes to.
    """
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/exercises",
        json={
            "subject_id": str(other_tenant.subject.id),
            "type": "open",
            "language": "fr",
            "statement": "Une question qui traverse les écoles.",
        },
    )
    assert response.status_code == 404, response.text
    assert not db.query(Exercise).filter(Exercise.subject_id == other_tenant.subject.id).all()


def test_a_manual_exercise_cannot_borrow_another_school_s_chapter(
    client, db: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    from test_api_fixtures import make_chapter

    theirs = make_chapter(db, other_tenant, key="leurs-fractions", competencies=[])
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/exercises",
        json={
            "subject_id": str(tenant.subject.id),
            "chapter_id": str(theirs.id),
            "type": "open",
            "language": "fr",
            "statement": "Une question qui traverse les écoles.",
        },
    )
    assert response.status_code == 404, response.text


# --- the untagged bucket ---------------------------------------------------
def test_the_untagged_bucket_is_selectable_and_distinct_from_no_filter(
    client, db: Session, tenant: Tenant, book: tuple[Source, list[SourceSection]]
) -> None:
    """`chapter_id=none` is what keeps every exercise reachable.

    Theme is the builder's root now, and `Exercise.chapter_id` is inferred and
    null on a large minority of a real textbook's rows. Without a selector for
    those rows they would have no way to be listed at all — the exact failure
    ExercisePicker's docstring used to prevent by having no theme filter.
    """
    from test_api_fixtures import make_chapter

    source, sections = book
    chapter = make_chapter(db, tenant, key="fractions", competencies=[tenant.competency])

    tagged = make_exercise(db, tenant, statement="Une fraction bien rangee.")
    tagged.source_id = source.id
    tagged.source_section_id = sections[0].id
    tagged.chapter_id = chapter.id
    db.commit()

    login(client, tenant.teacher.email)
    base = f"/api/v1/sources/{source.id}/exercises"

    only_tagged = client.get(f"{base}?chapter_id={chapter.id}").json()
    assert [i["id"] for i in only_tagged["items"]] == [str(tagged.id)]

    untagged = client.get(f"{base}?chapter_id=none&limit=100").json()
    ids = {i["id"] for i in untagged["items"]}
    assert str(tagged.id) not in ids
    # The 25 exercises the fixture never tagged are exactly what this returns.
    assert untagged["total"] == 25

    # And absence of the parameter is a THIRD answer: everything.
    everything = client.get(f"{base}?limit=100").json()
    assert everything["total"] == 26


def test_a_chapter_id_that_is_neither_a_uuid_nor_the_sentinel_is_refused(
    client, db: Session, tenant: Tenant, book: tuple[Source, list[SourceSection]]
) -> None:
    source, _sections = book
    login(client, tenant.teacher.email)
    response = client.get(f"/api/v1/sources/{source.id}/exercises?chapter_id=fractions")
    assert response.status_code == 422
