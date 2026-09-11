"""Editing the nouns a school owns: subjects, themes, classes, the school.

Everything here is a WRITE to something that, until now, only the seed could
create. That is the whole reason the module exists: a create endpoint makes
states reachable that a curated seed never produced, and each function below
is mostly about refusing one of them clearly.

Three rules run through it, and each has a failure a teacher would meet:

**Renaming is not re-identifying.** A label may always change. A `key`, a
`code` or a `uid` may not, once anything has been printed from it — the paper
in the pile does not update (I-platform-09).

**Deleting is not unenrolling, and it is not a cascade.** Every delete here
either refuses with a count of what still points at it, or is a no-op. The one
operation allowed to destroy evidence is deleting a Student, and it is the only
one that asks for a typed confirmation.

**The corpus is shared for READING** (D11, I-platform-04) — a colleague's
textbook scan is meant to be usable. Deleting from it is not reading, so the
destructive half narrows to teachers who actually teach that subject somewhere
in this school (D77).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alppy.api import errors
from alppy.api.deps import Scope
from alppy.core.logging import get_logger
from alppy.db.validity import today
from alppy.models import (
    UNFILED_CHAPTER_KEY,
    Chapter,
    Class,
    Exercise,
    Person,
    School,
    Sheet,
    Source,
    Student,
    Subject,
    class_student,
)
from alppy.services.enrollment import taught_subject_ids_anywhere
from alppy.storage import Storage

log = get_logger(__name__)

__all__ = [
    "create_subject",
    "delete_chapter",
    "delete_source",
    "delete_student",
    "rename_class",
    "rename_school",
    "rename_student",
    "update_chapter",
    "update_source",
    "update_subject",
]


def _assert_teaches_subject(db: Session, scope: Scope, subject_id: uuid.UUID) -> None:
    """Refuse a destructive corpus write from someone who does not teach it.

    Reads stay school-wide on purpose — this is the one place isolation reaches
    into the shared corpus, and only because the write destroys something
    (D77). A teacher who holds the branch in any class of this school passes.
    """
    held = set(db.execute(taught_subject_ids_anywhere(scope, on=today())).scalars())
    if subject_id not in held:
        raise errors.unprocessable(
            "you do not teach this branch in this school",
            subject_id=str(subject_id),
        )


# --------------------------------------------------------------------------
# Subject
# --------------------------------------------------------------------------
def create_subject(
    db: Session, scope: Scope, *, key: str, labels: dict[str, str]
) -> Subject:
    """A new Branch for this school.

    Creates its `unfiled` Theme in the same breath: `Sheet.chapter_id` is NOT
    NULL and falls back to that bucket, so a Branch without one would 422 the
    first sheet built in it (D60).
    """
    from alppy.services.chapter_service import ensure_unfiled_chapter

    normalised = key.strip().lower()
    if not normalised:
        raise errors.unprocessable("a branch needs a key")
    clash = db.execute(
        select(Subject)
        .where(Subject.school_id == scope.school_id)
        .where(Subject.key == normalised)
    ).scalar_one_or_none()
    if clash is not None:
        # `uq_subject_key` would otherwise surface as an IntegrityError 500,
        # and the two-subjects-one-key state is the one that splits a
        # curriculum silently (0022).
        raise errors.conflict("this school already studies that branch", subject_id=str(clash.id))

    row = Subject(id=uuid.uuid4(), school_id=scope.school_id, key=normalised, labels=labels)
    db.add(row)
    db.flush()
    ensure_unfiled_chapter(db, school_id=scope.school_id, subject_id=row.id)
    return row


def update_subject(
    db: Session, scope: Scope, subject: Subject, *, labels: dict[str, str]
) -> Subject:
    """Rename a Branch. The `key` is not editable, and that is the point.

    `Competency.subject_key` matches it by string, so changing a key would
    quietly detach every curriculum node the Branch reads through — the same
    breakage `uq_subject_key` exists to prevent, arrived at from the other
    side. Labels are what a teacher sees; the key is what the data joins on.
    """
    subject.labels = labels
    db.flush()
    return subject


# --------------------------------------------------------------------------
# Theme (Chapter)
# --------------------------------------------------------------------------
def update_chapter(
    db: Session,
    scope: Scope,
    chapter: Chapter,
    *,
    labels: dict[str, str] | None = None,
    position: int | None = None,
    competency_ids: list[uuid.UUID] | None = None,
) -> Chapter:
    """Edit a Theme: its name, its place, and what it CREDITS.

    `competency_ids` is the m2m (`chapter_competency`) — what the Theme claims
    to cover, across both curricula. It is NOT `primary_competency_id`, which
    is where the Theme SITS in the tree and is resolved per school from
    `School.default_curriculum` (D56). Editing the first is ordinary teacher
    work; editing the second would move the Theme to another Branch of the
    navigation and is not offered here.

    This is also the honest answer to "add a competence I teach": a teacher
    cannot create a `Competency` — it is national reference data shared by
    every school (D11) — but they choose which ones their Theme credits.
    """
    if labels is not None:
        chapter.labels = labels
    if position is not None:
        chapter.position = position
    if competency_ids is not None:
        from alppy.models import Competency

        found = list(db.execute(select(Competency).where(Competency.id.in_(competency_ids))).scalars())
        if len(found) != len(set(competency_ids)):
            raise errors.unprocessable("one of those competencies does not exist")
        chapter.competencies = found
    db.flush()
    return chapter


def delete_chapter(db: Session, scope: Scope, chapter: Chapter) -> None:
    """Remove a Theme, refusing while sheets still sit in it.

    `Sheet.chapter_id` is RESTRICT, so without this the refusal would arrive as
    an IntegrityError 500 — true, but unreadable. A count is what lets the
    teacher decide whether to refile them.

    The `unfiled` bucket is undeletable, and is recognised by
    `primary_competency_id IS NULL` rather than by its key: a school may
    relabel it, and a rename must not make it deletable.
    """
    if chapter.primary_competency_id is None or chapter.key == UNFILED_CHAPTER_KEY:
        raise errors.conflict("the unfiled bucket cannot be deleted")
    _assert_teaches_subject(db, scope, chapter.subject_id)

    held = db.execute(
        select(func.count(Sheet.id)).where(Sheet.chapter_id == chapter.id)
    ).scalar_one()
    if held:
        raise errors.conflict("this theme still holds sheets", sheet_count=str(held))
    db.delete(chapter)
    db.flush()


# --------------------------------------------------------------------------
# Class
# --------------------------------------------------------------------------
def rename_class(
    db: Session,
    scope: Scope,
    school_class: Class,
    *,
    label: str | None = None,
    code: str | None = None,
) -> Class:
    """Rename a class. The label always; the code only while nobody sits in it.

    `Student.uid` (`7B_15`) is minted from the code and is PRINTED — the pile
    on the desk does not update, and the detector decodes what is on the paper
    (I-platform-09). So a code change is refused the moment the class has a
    roster.

    It is not refused before that, deliberately: a typo made while creating a
    class must be fixable, and a class with no students has minted no UIDs.
    """
    if label is not None:
        school_class.label = label or None
    if code is not None and code != school_class.code:
        # EVER seated, not currently seated. The guard exists because the
        # code is printed on paper, and a pupil who left in February took an
        # October copy carrying the old code away with them — so `class_student`
        # is read here WITHOUT a validity predicate, deliberately. Refusing is
        # the safe direction for a constraint about ink (D87).
        seated = db.execute(
            select(func.count())
            .select_from(class_student)
            .where(class_student.c.class_id == school_class.id)
        ).scalar_one()
        homed = db.execute(
            select(func.count(Student.id)).where(Student.home_class_id == school_class.id)
        ).scalar_one()
        if seated or homed:
            raise errors.conflict(
                "this class has pupils, and its code is printed in their identifiers",
                student_count=str(max(seated, homed)),
            )
        normalised = code.strip().upper()
        clash = db.execute(
            select(Class)
            .where(Class.school_id == school_class.school_id)
            .where(Class.school_year_id == school_class.school_year_id)
            .where(Class.code == normalised)
            .where(Class.id != school_class.id)
        ).scalar_one_or_none()
        if clash is not None:
            raise errors.conflict(f"class {normalised} already exists this school year")
        school_class.code = normalised
    db.flush()
    return school_class


# --------------------------------------------------------------------------
# School
# --------------------------------------------------------------------------
def rename_school(
    db: Session, school: School, *, name: str | None = None, canton: str | None = None
) -> School:
    """Rename the school. `default_curriculum` is deliberately not editable.

    It is resolved ONCE, at seed time, into every `Chapter.primary_competency_id`
    (D56). Changing it later would leave every Theme hanging from the other
    curriculum's node — a silent mis-filing of the whole tree, from a settings
    field that looks like a preference.
    """
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise errors.unprocessable("a school needs a name")
        school.name = cleaned
    if canton is not None:
        school.canton = canton.strip().upper() or None
    db.flush()
    return school


# --------------------------------------------------------------------------
# Textbook (Source)
# --------------------------------------------------------------------------
def update_source(
    db: Session,
    scope: Scope,
    source: Source,
    *,
    title: str | None = None,
    language: str | None = None,
    publisher: str | None = None,
    isbn: str | None = None,
    url: str | None = None,
) -> Source:
    """Edit a textbook's own metadata.

    Not `subject_id`: exercises cut from the book carry their OWN
    `subject_id`, so re-filing the book would leave every exercise behind under
    the old Branch and the shelf would disagree with the corpus.
    """
    if title is not None:
        source.title = title.strip() or None
    if language is not None:
        source.language = language.strip() or None
    if publisher is not None:
        source.publisher = publisher.strip() or None
    if isbn is not None:
        # Stored as typed, minus surrounding space. Alppy never resolves an
        # ISBN against anything, so normalising hyphens would be a rule with
        # no beneficiary and one more way to reject a correct entry.
        source.isbn = isbn.strip() or None
    if url is not None:
        source.url = url.strip() or None
    db.flush()
    return source


def delete_source(db: Session, scope: Scope, source: Source) -> None:
    """Remove a textbook, refusing while exercises still cite it.

    `Exercise.source_id` is SET NULL, so a delete would not fail — it would
    quietly strip the provenance from every exercise cut from that book, which
    is the one thing `ExerciseOrigin.TEXTBOOK` exists to assert. A refusal with
    a count is the honest answer; discarding the exercises first is the
    teacher's decision, not this function's.

    The stored PDF is left where it is: `Storage` has no `delete`, and adding
    one to satisfy this path would put an untested destructive call on the
    object store behind an ordinary button.
    """
    _assert_teaches_subject(db, scope, source.subject_id)
    cited = db.execute(
        select(func.count(Exercise.id))
        .where(Exercise.source_id == source.id)
        .where(Exercise.discarded_at.is_(None))
    ).scalar_one()
    if cited:
        raise errors.conflict("this textbook still has exercises", exercise_count=str(cited))
    db.delete(source)
    db.flush()


# --------------------------------------------------------------------------
# Student
# --------------------------------------------------------------------------
def rename_student(
    db: Session,
    scope: Scope,
    student: Student,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
) -> Student:
    """Correct a pupil's name. Their `uid` and `number` are not editable.

    A misspelt name is the ordinary case and costs nothing: names never leave
    the database toward a model provider (`docs/privacy.md`), so nothing
    downstream holds a copy. `uid` and `number` are the opposite — printed on
    every sheet already in a pile (I-platform-09).
    """
    if first_name is not None:
        cleaned = first_name.strip()
        if not cleaned:
            raise errors.unprocessable("a pupil needs a first name")
        student.first_name = cleaned
    if last_name is not None:
        cleaned = last_name.strip()
        if not cleaned:
            raise errors.unprocessable("a pupil needs a last name")
        student.last_name = cleaned
    db.flush()
    return student


def scan_image_keys_for_student(db: Session, student: Student) -> list[str]:
    """Every stored image that is a photograph of this pupil's paper.

    The page images and the answer-box crops cut from them. Collected before
    the rows are deleted, because the rows are the only index into the object
    store — once `ScanPage` is gone there is nothing left that knows the key
    (audit 03, B14).

    Crops are a stronger case than pages, not a weaker one: a crop is a picture
    of one child's handwriting, cut from their paper, sent to a model provider.
    It is the most personal artefact this product holds.
    """
    from alppy.models import Detection, ScanPage

    pages = list(
        db.execute(
            select(ScanPage).where(ScanPage.student_id == student.id)
        ).scalars()
    )
    keys = [p.image_key for p in pages if p.image_key]
    if pages:
        crops = db.execute(
            select(Detection.crop_key).where(
                Detection.scan_page_id.in_([p.id for p in pages]),
                Detection.crop_key.is_not(None),
            )
        ).scalars()
        keys.extend(k for k in crops if k)
    return sorted(set(keys))


def delete_student(
    db: Session,
    scope: Scope,
    student: Student,
    *,
    confirm_uid: str,
    storage: Storage | None = None,
) -> None:
    """Destroy a pupil and everything that hangs off them.

    **This is the only operation in Alppy allowed to destroy evidence**
    (`docs/data-model.md` §6): `Attempt`, `MasterySnapshot` and `SheetInstance`
    all cascade from `Student`. Unenrolling is the answer to almost every
    reason a teacher reaches for this, and the API says so by keeping the two
    apart rather than by hoping the UI explains it.

    `confirm_uid` must match the pupil's own identifier. Not a boolean flag: a
    caller that sends `?confirm=true` from the wrong row deletes the wrong
    child, and the UID is the one string that is unambiguous and in front of
    the teacher on the paper.

    Restricted to the HEAD TEACHER of the pupil's HOME class — the one class
    that minted their uid (D69), and the one person accountable for the group.
    A subject teacher who co-teaches the child READS them, because D73 is
    deliberately class-grained about identity; that must not extend to erasing
    another teacher's pupil.

    `get_class` is NOT the gate here, and the distinction is the whole point:
    it answers "may I open this class", which a co-teacher can. Destroying
    evidence needs the narrower question.
    """
    if confirm_uid != student.uid:
        raise errors.unprocessable(
            "confirmation does not match this pupil's identifier",
            expected=student.uid,
        )
    from alppy.services.class_service import get_class

    # Reads as missing, not forbidden, like every other ownership failure here.
    home = get_class(db, scope, student.home_class_id)
    if home.head_teacher_id != scope.teacher_id:
        raise errors.not_found("student", id=str(student.id))
    person_id = student.person_id
    student_id = student.id
    # Read the keys BEFORE the cascade takes the rows that name them. Erasure
    # that leaves every photograph of the child's handwriting in object storage
    # is not erasure; it just makes the images unreachable through the product
    # (audit 03, B14). Collected here, deleted after the database work commits
    # — an object cannot be un-deleted, so it goes last.
    image_keys = scan_image_keys_for_student(db, student) if storage is not None else []
    db.delete(student)
    db.flush()

    # The evidence moved to `person` in 0028, so deleting the year-bound row
    # alone would now LEAVE a pupil's attempts, snapshots and notes behind —
    # this endpoint would go on reporting success while destroying nothing.
    # The person goes too, once no other year still refers to them; a pupil
    # with a second year on file is not erased by deleting one of them.
    remaining = db.execute(
        select(func.count()).select_from(Student).where(Student.person_id == person_id)
    ).scalar_one()
    if not remaining:
        person = db.get(Person, person_id)
        if person is not None:
            db.delete(person)
            db.flush()

    if storage is not None and image_keys:
        _erase_objects(storage, image_keys, student_id=student_id)


def _erase_objects(storage: Storage, keys: list[str], *, student_id: uuid.UUID) -> None:
    """Delete the stored images of one erased pupil, one failure at a time.

    A storage error must not roll back the erasure: the database rows are the
    record a parent asked to have destroyed, and refusing the whole request
    because one object had already gone would leave the pupil in the system.
    Each failure is logged with its key so an operator can finish by hand.
    """
    removed = 0
    for key in keys:
        try:
            removed += 1 if storage.delete(key) else 0
        except Exception as exc:
            log.warning(
                "student.erase.object_failed",
                student_id=str(student_id),
                key=key,
                error=str(exc),
            )
    log.info(
        "student.erase.objects",
        student_id=str(student_id),
        requested=len(keys),
        removed=removed,
    )
