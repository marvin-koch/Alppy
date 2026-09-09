"""What the reference seed has to establish for the curriculum tree to exist.

Two facts the rest of the product assumes and nothing else asserts: every
subject has an `unfiled` bucket to fall back on, and every Theme knows the one
Competence it hangs from *for this school's curriculum*.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403

from alppy.models import UNFILED_CHAPTER_KEY, Chapter, Competency, School, Subject
from alppy.models.enums import CurriculumKind
from alppy.seed.loader import SeedError, load_reference_data


def _school(db: Session, curriculum: CurriculumKind) -> School:
    school = School(
        id=uuid.uuid4(),
        name=f"CO de {curriculum.value}",
        canton="VS",
        default_curriculum=curriculum,
    )
    db.add(school)
    db.flush()
    return school


def _chapter(db: Session, school: School, key: str) -> Chapter:
    row = db.execute(
        select(Chapter).where(Chapter.school_id == school.id).where(Chapter.key == key)
    ).scalar_one()
    return row


def test_every_subject_gets_an_unfiled_bucket(db: Session) -> None:
    """`Sheet.chapter_id` is NOT NULL, so this row has to exist before a
    teacher can create their first sheet in a subject at all."""
    school = _school(db, CurriculumKind.PER)
    result = load_reference_data(db, school_id=school.id)

    assert set(result.unfiled_chapter_ids) == set(result.subject_ids)
    for subject_key, chapter_id in result.unfiled_chapter_ids.items():
        chapter = db.get(Chapter, chapter_id)
        assert chapter is not None, subject_key
        assert chapter.key == UNFILED_CHAPTER_KEY
        # What excludes it from the tree and the roll-up — not its key.
        assert chapter.primary_competency_id is None
        # Sorts last, so an ordinary `ORDER BY position` needs no filter.
        assert chapter.position > max(
            c.position
            for c in db.scalars(
                select(Chapter)
                .where(Chapter.school_id == school.id)
                .where(Chapter.key != UNFILED_CHAPTER_KEY)
            )
        )


def test_the_unfiled_bucket_is_not_created_twice(db: Session) -> None:
    school = _school(db, CurriculumKind.PER)
    load_reference_data(db, school_id=school.id)
    first = db.scalars(
        select(Chapter)
        .where(Chapter.school_id == school.id)
        .where(Chapter.key == UNFILED_CHAPTER_KEY)
    ).all()
    load_reference_data(db, school_id=school.id)
    second = db.scalars(
        select(Chapter)
        .where(Chapter.school_id == school.id)
        .where(Chapter.key == UNFILED_CHAPTER_KEY)
    ).all()
    assert len(first) == len(second) == 1


@pytest.mark.parametrize(
    ("curriculum", "code"),
    [(CurriculumKind.PER, "MSN 31.2"), (CurriculumKind.LP21, "MA.2.A.2")],
)
def test_a_theme_hangs_from_its_own_schools_curriculum(
    db: Session, curriculum: CurriculumKind, code: str
) -> None:
    """The point of `primary_competency_id` being per school.

    `plane_geometry_pythagoras` tags four competencies across BOTH curricula so
    two language regions can share the chapter (docs/curriculum.md §3). Exactly
    one of them is where a given school files it — and because `Chapter` is
    school-scoped, that needs one nullable FK rather than two columns.
    """
    school = _school(db, curriculum)
    load_reference_data(db, school_id=school.id)

    chapter = _chapter(db, school, "plane_geometry_pythagoras")
    primary = db.get(Competency, chapter.primary_competency_id)
    assert primary is not None
    assert primary.code == code
    assert primary.curriculum is curriculum

    # The tagging set is untouched: mastery still credits every one of them,
    # including the other curriculum's.
    tagged = {c.code for c in chapter.competencies}
    assert tagged == {"MSN 31.2", "MSN 31.1", "MA.2.A.2", "MA.2.C.1"}


def test_every_seeded_theme_has_a_primary_and_it_is_one_of_its_own_tags(
    db: Session,
) -> None:
    school = _school(db, CurriculumKind.PER)
    load_reference_data(db, school_id=school.id)

    for chapter in db.scalars(
        select(Chapter)
        .where(Chapter.school_id == school.id)
        .where(Chapter.key != UNFILED_CHAPTER_KEY)
    ):
        assert chapter.primary_competency_id is not None, chapter.key
        assert chapter.primary_competency_id in {c.id for c in chapter.competencies}, (
            f"{chapter.key}: primary is not among its own competency_codes"
        )


def test_a_theme_with_no_primary_for_this_curriculum_fails_loudly(
    db: Session, tmp_path
) -> None:
    """The seed's own promise: a bad reference names the offending key."""
    import json
    import shutil
    from pathlib import Path

    src = Path("apps/api/alppy/seed/data")
    for name in ("competencies.json", "chapters.json", "exercises.json"):
        shutil.copy(src / name, tmp_path / name)

    doc = json.loads((tmp_path / "chapters.json").read_text())
    doc["chapters"][0]["primary_competency_code"].pop("PER")
    (tmp_path / "chapters.json").write_text(json.dumps(doc, ensure_ascii=False))

    school = _school(db, CurriculumKind.PER)
    with pytest.raises(SeedError) as exc:
        load_reference_data(db, school_id=school.id, data_dir=tmp_path)
    assert "fractions" in str(exc.value)
    assert "PER" in str(exc.value)


def test_a_subject_that_never_saw_the_seed_still_gets_a_bucket_on_demand(
    db: Session,
) -> None:
    """The lazy safety net: a missing structural row must never surface as a
    422 on an ordinary "new sheet"."""
    from alppy.services.chapter_service import ensure_unfiled_chapter

    school = _school(db, CurriculumKind.PER)
    subject = Subject(
        id=uuid.uuid4(), school_id=school.id, key="latin", labels={"fr": "Latin"}
    )
    db.add(subject)
    db.flush()

    chapter = ensure_unfiled_chapter(db, school_id=school.id, subject_id=subject.id)
    assert chapter.key == UNFILED_CHAPTER_KEY
    again = ensure_unfiled_chapter(db, school_id=school.id, subject_id=subject.id)
    assert again.id == chapter.id
