"""Retrieval and ranking (F1), against the real demo corpus.

This module also owns the in-memory SQLite harness the other database-backed
tests import. Two Postgres-only column types need a dialect-level swap to run
on SQLite — `pgvector`'s ``Vector`` and ``JSONB``. The swap lives here, in test
code, and never in ``alppy/models/``: production runs on Postgres and the
models must say so.

The point of running the whole RAG path on SQLite with the
``HashEmbeddingsProvider`` is that CI needs neither a database server nor an
API key to prove that ranking, provenance and the approval gate behave.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from alppy.ai.client import AiClient
from alppy.core.uid import format_uid
from alppy.db.base import Base
from alppy.db.validity import today
from alppy.models import (
    Chapter,
    Class,
    Competency,
    Exercise,
    MasterySnapshot,
    Person,
    School,
    SchoolYear,
    Source,
    SourceChunk,
    Student,
    Subject,
    Teacher,
    class_student,
)
from alppy.models.enums import ExerciseOrigin, ExerciseType, MasteryBand
from alppy.seed import loader
from alppy.services import retrieval


# --------------------------------------------------------------------------
# SQLite type swap — test-only, deliberately not in alppy/models/
# --------------------------------------------------------------------------
@compiles(Vector, "sqlite")
def _compile_vector_sqlite(type_, compiler, **kw) -> str:  # type: ignore[no-untyped-def]
    """pgvector round-trips through its own text form, which SQLite can hold."""
    return "TEXT"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw) -> str:  # type: ignore[no-untyped-def]
    return "JSON"


def make_session() -> Session:
    """A fresh in-memory database with the full schema."""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


# --------------------------------------------------------------------------
# A world to retrieve from: the real seed corpus plus a class of students
# --------------------------------------------------------------------------
@dataclass(slots=True)
class World:
    db: Session
    school_id: uuid.UUID
    subject_id: uuid.UUID
    class_id: uuid.UUID
    student_ids: list[str]
    students: dict[str, uuid.UUID]
    chapters: dict[str, uuid.UUID]
    competencies: dict[str, uuid.UUID]
    exercises: dict[str, uuid.UUID]
    #: uid -> person id, the other half of `students`
    people: dict[str, uuid.UUID]
    source_id: uuid.UUID

    def chapter(self, key: str) -> uuid.UUID:
        return self.chapters[key]

    def competency(self, code: str) -> uuid.UUID:
        return self.competencies[code]

    def student(self, uid: str) -> uuid.UUID:
        return self.students[uid]

    def person(self, uid: str) -> uuid.UUID:
        """The durable identity behind a uid (D87).

        A uid is a fact about one year's paper and resolves to a ``student``;
        every attempt and every snapshot hangs off the ``person`` that student
        points at. Tests that build evidence want this one.
        """
        return self.people[uid]


ROSTER = [
    ("Livia", "Bernasconi"),
    ("Noah", "Zbinden"),
    ("Elif", "Demirtas"),
]


def build_world(db: Session | None = None) -> World:
    db = db or make_session()
    school = School(id=uuid.uuid4(), name="CO de Sion")
    db.add(school)
    db.flush()

    reference = loader.load_reference_data(db, school_id=school.id)
    subject_id = reference.subject_ids["mathematics"]
    corpus = loader.load_demo_corpus(db, school_id=school.id, subject_id=subject_id)

    year = SchoolYear(
        id=uuid.uuid4(),
        school_id=school.id,
        label="2025/26",
        starts_on=date(2025, 8, 18),
        ends_on=date(2026, 7, 3),
        is_current=True,
    )
    teacher = Teacher(
        id=uuid.uuid4(),
        home_school_id=school.id,
        email="prof@example.ch",
        password_hash="x",
        first_name="Ariane",
        last_name="Rey",
    )
    db.add_all([year, teacher])
    db.flush()

    school_class = Class(
        id=uuid.uuid4(),
        school_id=school.id,
        school_year_id=year.id,
        head_teacher_id=teacher.id,
        code="7B",
    )
    db.add(school_class)
    db.flush()

    students: dict[str, uuid.UUID] = {}
    people: dict[str, uuid.UUID] = {}
    for i, (first, last) in enumerate(ROSTER, start=1):
        # Build the uid the way the application does. A hand-rolled f-string
        # here produced "7B_01" while every real code path produces the
        # zero-padded "7B_01", and the difference only surfaced in one
        # assertion deep in the adaptive tests.
        uid = format_uid("7B", i)
        person = Person(
            id=uuid.uuid4(), school_id=school.id, first_name=first, last_name=last
        )
        db.add(person)
        student = Student(
            id=uuid.uuid4(),
            school_id=school.id,
            person_id=person.id,
            home_class_id=school_class.id,
            school_year_id=year.id,
            uid=uid,
            number=i,
            first_name=first,
            last_name=last,
        )
        db.add(student)
        students[uid] = student.id
        people[uid] = person.id
    db.flush()
    db.execute(
        class_student.insert(),
        [
            {"class_id": school_class.id, "student_id": sid, "valid_from": today()}
            for sid in students.values()
        ],
    )
    db.commit()

    return World(
        db=db,
        school_id=school.id,
        subject_id=subject_id,
        class_id=school_class.id,
        student_ids=list(students),
        students=students,
        people=people,
        chapters=reference.chapter_ids,
        competencies=reference.competency_ids,
        exercises=corpus.exercise_ids,
        source_id=corpus.source_id,
    )


def snapshot(
    world: World,
    *,
    student_uid: str,
    competency_code: str,
    score: float,
    band: MasteryBand,
    days_ago: float = 1.0,
    attempts: int = 6,
) -> MasterySnapshot:
    row = MasterySnapshot(
        id=uuid.uuid4(),
        school_id=world.school_id,
        person_id=world.person(student_uid),
        competency_id=world.competency(competency_code),
        computed_at=datetime.now(UTC) - timedelta(days=days_ago),
        score=score,
        band=band,
        attempts_count=attempts,
        last_attempt_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    world.db.add(row)
    world.db.flush()
    return row


@pytest.fixture
def world() -> World:
    return build_world()


# --------------------------------------------------------------------------
# The seed corpus loads and is retrievable at all
# --------------------------------------------------------------------------
def test_corpus_is_indexed_with_embeddings(world: World) -> None:
    chunks = world.db.query(SourceChunk).all()
    assert len(chunks) == 63
    assert all(c.embedding is not None for c in chunks)
    assert all(len(list(c.embedding)) == AiClient().embedding_dim for c in chunks)


def test_propose_returns_the_requested_count(world: World) -> None:
    proposals = retrieval.propose_exercises(
        world.db,
        school_id=world.school_id,
        class_id=world.class_id,
        subject_id=world.subject_id,
        chapter_ids=[],
        intent=None,
        count=8,
        language="fr",
        difficulty=None,
    )
    assert len(proposals) == 8
    assert len({p.exercise.id for p in proposals}) == 8


# --------------------------------------------------------------------------
# Hard filters
# --------------------------------------------------------------------------
def test_chapter_filter_is_hard(world: World) -> None:
    chapter_id = world.chapter("fractions")
    proposals = retrieval.propose_exercises(
        world.db,
        school_id=world.school_id,
        class_id=world.class_id,
        subject_id=world.subject_id,
        chapter_ids=[chapter_id],
        intent=None,
        count=12,
        language="fr",
        difficulty=None,
    )
    assert proposals
    assert all(p.exercise.chapter_id == chapter_id for p in proposals)


def test_language_follows_the_source_not_the_ui(world: World) -> None:
    """The corpus is deliberately bilingual. A French sheet gets French items,
    a German sheet German ones — the exercise's language comes from the source
    material, never from the teacher's interface locale."""
    for language in ("fr", "de"):
        proposals = retrieval.propose_exercises(
            world.db,
            school_id=world.school_id,
            class_id=world.class_id,
            subject_id=world.subject_id,
            chapter_ids=[world.chapter("fractions")],
            intent=None,
            count=4,
            language=language,
            difficulty=None,
        )
        assert proposals
        assert {p.exercise.language for p in proposals} == {language}


def test_other_languages_are_only_used_once_the_right_one_runs_out(world: World) -> None:
    """Nine French fraction exercises do not exist; rather than return four
    items when twelve were asked for, the ranker falls back — and says so."""
    proposals = retrieval.propose_exercises(
        world.db,
        school_id=world.school_id,
        class_id=world.class_id,
        subject_id=world.subject_id,
        chapter_ids=[world.chapter("fractions")],
        intent=None,
        count=9,
        language="fr",
        difficulty=None,
    )
    assert len(proposals) == 9
    languages = [p.exercise.language for p in proposals]
    assert languages[:5] == ["fr"] * 5  # all five French ones first
    assert "de" in languages[5:]
    fallback = next(p for p in proposals if p.exercise.language == "de")
    assert "not the language of this sheet" in fallback.provenance.reason or (
        "différente de la langue" in fallback.provenance.reason
    )


def test_unapproved_ai_exercises_are_never_proposed_for_a_sheet(world: World) -> None:
    """An unapproved generated item is not something the print path will
    accept, so it is not something the builder may offer."""
    pending = Exercise(
        id=uuid.uuid4(),
        school_id=world.school_id,
        subject_id=world.subject_id,
        chapter_id=world.chapter("fractions"),
        type=ExerciseType.MCQ,
        origin=ExerciseOrigin.AI_GENERATED,
        language="fr",
        statement="Calcule 3/5 + 1/5 et simplifie le resultat.",
        options=["4/5", "4/10", "3/10", "1"],
        answer_index=0,
        difficulty=2,
        approved_at=None,
    )
    world.db.add(pending)
    world.db.commit()

    def ids(**kw: object) -> set[uuid.UUID]:
        proposals = retrieval.propose_exercises(
            world.db,
            school_id=world.school_id,
            class_id=world.class_id,
            subject_id=world.subject_id,
            chapter_ids=[world.chapter("fractions")],
            intent=None,
            count=20,
            language="fr",
            difficulty=None,
        )
        return {p.exercise.id for p in proposals}

    assert pending.id not in ids()

    pending.approved_at = datetime.now(UTC)
    world.db.commit()
    assert pending.id in ids()


def test_school_scoping_is_enforced(world: World) -> None:
    other_school = uuid.uuid4()
    proposals = retrieval.propose_exercises(
        world.db,
        school_id=other_school,
        class_id=world.class_id,
        subject_id=world.subject_id,
        chapter_ids=[],
        intent=None,
        count=5,
        language="fr",
        difficulty=None,
    )
    assert proposals == []


# --------------------------------------------------------------------------
# Scoring terms
# --------------------------------------------------------------------------
def test_difficulty_proximity_pulls_the_requested_level_to_the_top(world: World) -> None:
    easy = retrieval.propose_exercises(
        world.db,
        school_id=world.school_id,
        class_id=world.class_id,
        subject_id=world.subject_id,
        chapter_ids=[],
        intent=None,
        count=6,
        language="fr",
        difficulty=1,
    )
    hard = retrieval.propose_exercises(
        world.db,
        school_id=world.school_id,
        class_id=world.class_id,
        subject_id=world.subject_id,
        chapter_ids=[],
        intent=None,
        count=6,
        language="fr",
        difficulty=5,
    )
    mean_easy = sum(p.exercise.difficulty for p in easy) / len(easy)
    mean_hard = sum(p.exercise.difficulty for p in hard) / len(hard)
    assert mean_easy < mean_hard
    assert easy[0].exercise.difficulty <= 2
    assert hard[0].exercise.difficulty >= 4


def test_difficulty_fit_is_linear_and_bottoms_out_at_four_levels() -> None:
    assert retrieval._difficulty_fit(3, 3) == 1.0
    assert retrieval._difficulty_fit(2, 3) == 0.75
    assert retrieval._difficulty_fit(1, 5) == 0.0
    assert retrieval._difficulty_fit(3, None) == 1.0


def test_intent_similarity_reorders_the_ranking(world: World) -> None:
    """With no chapter filter and no difficulty, every other term is constant,
    so the typed intent is the only thing that can move the ranking — and it
    must move it to a different chapter for a different intent."""

    def top_chapter(intent: str) -> uuid.UUID | None:
        proposals = retrieval.propose_exercises(
            world.db,
            school_id=world.school_id,
            class_id=world.class_id,
            subject_id=world.subject_id,
            chapter_ids=[],
            intent=intent,
            count=3,
            language="fr",
            difficulty=None,
        )
        assert proposals[0].provenance.similarity is not None
        assert proposals[0].provenance.similarity > 0.0
        return proposals[0].exercise.chapter_id

    assert top_chapter("révision fraction irréductible simplifie") == world.chapter(
        "fractions"
    )
    assert top_chapter("pourcentage rabais prix") == world.chapter("percentages")


def test_no_intent_means_no_similarity_and_the_provenance_says_so(world: World) -> None:
    proposals = retrieval.propose_exercises(
        world.db,
        school_id=world.school_id,
        class_id=world.class_id,
        subject_id=world.subject_id,
        chapter_ids=[world.chapter("percentages")],
        intent=None,
        count=3,
        language="fr",
        difficulty=None,
    )
    assert all(p.provenance.similarity is None for p in proposals)
    assert all("aucune intention" in p.provenance.reason for p in proposals)


def test_cosine_similarity_matches_pgvector_semantics() -> None:
    assert retrieval.cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert retrieval.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert retrieval.cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    assert retrieval.cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
    with pytest.raises(retrieval.RetrievalError):
        retrieval.cosine_similarity([1.0], [1.0, 0.0])


# --------------------------------------------------------------------------
# Diversity
# --------------------------------------------------------------------------
def test_repeats_from_the_same_chunk_are_penalised(world: World) -> None:
    """Eight variations of one exercise off one chunk is a worse sheet than
    eight merely-good items, so the same chunk is not mined twice while
    anything else is available."""
    chunk = world.db.query(SourceChunk).order_by(SourceChunk.position).first()
    assert chunk is not None
    for i in range(6):
        world.db.add(
            Exercise(
                id=uuid.uuid4(),
                school_id=world.school_id,
                subject_id=world.subject_id,
                chapter_id=world.chapter("fractions"),
                source_id=world.source_id,
                source_chunk_id=chunk.id,
                source_page=chunk.page,
                type=ExerciseType.MCQ,
                origin=ExerciseOrigin.TEXTBOOK,
                language="fr",
                statement=f"Quelle fraction est equivalente a {i + 2}/5 ?",
                options=["a", "b", "c", "d"],
                answer_index=0,
                difficulty=1,
            )
        )
    world.db.commit()

    proposals = retrieval.propose_exercises(
        world.db,
        school_id=world.school_id,
        class_id=world.class_id,
        subject_id=world.subject_id,
        chapter_ids=[world.chapter("fractions")],
        intent=None,
        count=5,
        language="fr",
        difficulty=1,
    )
    chunk_of = {
        e.id: e.source_chunk_id
        for e in world.db.query(Exercise).all()
    }
    from_chunk = [p for p in proposals if chunk_of[p.exercise.id] == chunk.id]
    assert len(from_chunk) < 5, "the ranker mined a single chunk for the whole sheet"
    assert len(from_chunk) <= 2


def test_near_duplicate_statements_are_penalised(world: World) -> None:
    statement = "Calcule 2/3 + 1/4 et donne le resultat sous forme irreductible."
    for _ in range(4):
        world.db.add(
            Exercise(
                id=uuid.uuid4(),
                school_id=world.school_id,
                subject_id=world.subject_id,
                chapter_id=world.chapter("fractions"),
                type=ExerciseType.OPEN,
                origin=ExerciseOrigin.TEXTBOOK,
                language="fr",
                statement=statement,
                difficulty=3,
            )
        )
    world.db.commit()
    proposals = retrieval.propose_exercises(
        world.db,
        school_id=world.school_id,
        class_id=world.class_id,
        subject_id=world.subject_id,
        chapter_ids=[world.chapter("fractions")],
        intent=None,
        count=6,
        language="fr",
        difficulty=3,
    )
    same = [p for p in proposals if p.exercise.statement == statement]
    assert len(same) <= 2


def test_diversity_penalty_accumulates_over_what_is_already_picked(world: World) -> None:
    candidates = retrieval.gather_candidates(
        world.db,
        school_id=world.school_id,
        subject_id=world.subject_id,
        chapter_ids=[world.chapter("fractions")],
        language="fr",
    )
    first = candidates[0]
    assert retrieval.diversity_penalty(first, []) == 0.0
    assert retrieval.diversity_penalty(first, [first]) >= retrieval.P_NEAR_DUPLICATE


# --------------------------------------------------------------------------
# Provenance — what the teacher audits
# --------------------------------------------------------------------------
def test_provenance_is_specific_enough_to_check_against_the_book(world: World) -> None:
    proposals = retrieval.propose_exercises(
        world.db,
        school_id=world.school_id,
        class_id=world.class_id,
        subject_id=world.subject_id,
        chapter_ids=[world.chapter("fractions")],
        intent="revision fractions",
        count=4,
        language="fr",
        difficulty=2,
    )
    source = world.db.get(Source, world.source_id)
    assert source is not None
    for proposal in proposals:
        prov = proposal.provenance
        assert prov.source_id == world.source_id
        assert prov.source_filename == source.filename
        assert prov.page and prov.page >= 1
        assert prov.excerpt
        assert proposal.exercise.statement.split(".")[0][:20] in prov.excerpt
        assert prov.similarity is not None
        # The reason must explain *why*, not just report a number.
        assert "chapitre Fractions" in prov.reason
        assert "difficulté" in prov.reason
        assert "p. " in prov.reason


def test_reason_is_written_in_the_language_of_the_sheet(world: World) -> None:
    expected = {
        "fr": "correspond au chapitre",
        "de": "passt zum Kapitel",
        "en": "matches chapter",
    }
    for language, phrase in expected.items():
        proposals = retrieval.propose_exercises(
            world.db,
            school_id=world.school_id,
            class_id=world.class_id,
            subject_id=world.subject_id,
            chapter_ids=[world.chapter("fractions")],
            intent=None,
            count=1,
            language=language,
            difficulty=None,
        )
        assert phrase in proposals[0].provenance.reason


def test_proposal_carries_competency_ids(world: World) -> None:
    """`ExerciseOut.competency_ids` has no matching model attribute, so a naive
    ``model_validate`` would hand the frontend an untagged exercise."""
    proposals = retrieval.propose_exercises(
        world.db,
        school_id=world.school_id,
        class_id=world.class_id,
        subject_id=world.subject_id,
        chapter_ids=[world.chapter("fractions")],
        intent=None,
        count=3,
        language="fr",
        difficulty=None,
    )
    assert all(p.exercise.competency_ids for p in proposals)
    known = set(world.competencies.values())
    assert all(set(p.exercise.competency_ids) <= known for p in proposals)


def test_competency_filter_targets_exercises_directly(world: World) -> None:
    """The adaptive path filters by competency, not chapter: a student's gap
    does not respect chapter boundaries."""
    competency_id = world.competency("MSN 32.1")
    candidates = retrieval.gather_candidates(
        world.db,
        school_id=world.school_id,
        subject_id=world.subject_id,
        competency_ids=[competency_id],
        language="fr",
    )
    assert candidates
    assert all(competency_id in c.competency_ids for c in candidates)


def test_chapters_for_competencies_resolves_back(world: World) -> None:
    chapters = retrieval.chapters_for_competencies(
        world.db, school_id=world.school_id, competency_ids=[world.competency("MSN 32.1")]
    )
    assert world.chapter("fractions") in chapters
    assert retrieval.chapters_for_competencies(
        world.db, school_id=world.school_id, competency_ids=[]
    ) == []


def test_excerpt_is_trimmed_on_a_word_boundary() -> None:
    long_text = "mot " * 200
    excerpt = retrieval._excerpt(long_text, limit=40)
    assert excerpt.endswith("…")
    assert len(excerpt) <= 41


def test_untagged_exercise_is_neither_a_match_nor_a_mismatch() -> None:
    assert retrieval._competency_fit([], []) == 0.5
    a, b = uuid.uuid4(), uuid.uuid4()
    assert retrieval._competency_fit([a], [a]) == 1.0
    assert retrieval._competency_fit([a, b], [a]) == 0.5
    assert retrieval._competency_fit([a], []) == 0.0


def test_labels_fall_back_when_the_locale_is_missing() -> None:
    assert retrieval._label({"fr": "Fractions"}, "de") == "Fractions"
    assert retrieval._label({}, "fr") == "—"


def test_competency_and_chapter_lookups_are_school_scoped(world: World) -> None:
    other = uuid.uuid4()
    assert retrieval._chapters_by_id(world.db, school_id=other) == {}
    assert retrieval._chunks_by_id(world.db, school_id=other) == {}
    assert retrieval._sources_by_id(world.db, school_id=other) == {}
    assert world.db.query(Competency).count() == 34
    # 7 seeded Themes plus the subject's `unfiled` bucket, which every
    # subject carries so `Sheet.chapter_id` (NOT NULL) always has a home.
    assert world.db.query(Chapter).count() == 8
    assert world.db.query(Subject).count() == 1


# --------------------------------------------------------------------------
# The intent must help, and the number shown must be the number used
# --------------------------------------------------------------------------
def _propose(world: World, intent: str | None, count: int = 6):
    return retrieval.propose_exercises(
        world.db,
        school_id=world.school_id,
        class_id=world.class_id,
        subject_id=world.subject_id,
        chapter_ids=[],
        intent=intent,
        count=count,
        language="fr",
        difficulty=None,
    )


def test_a_plural_intent_finds_the_singular_subject(world: World) -> None:
    """"fractions" used to score 0.0 against every chunk — the offline embedder
    hashes whole tokens, so the plural landed in a different bucket from
    "fraction" and the top result was a symmetry exercise."""
    proposals = _propose(world, "fractions")
    top = " ".join(p.exercise.statement.lower() for p in proposals[:3])
    assert "fraction" in top


def test_the_displayed_score_matches_the_order_it_is_displayed_in(world: World) -> None:
    """The list is ordered greedily with a diversity penalty; the score shown
    beside each item was computed without it, so item 5 could out-score item 2."""
    scores = [p.score for p in _propose(world, "géométrie triangle angles")]
    assert scores == sorted(scores, reverse=True), scores


def test_an_intent_never_penalises_the_whole_candidate_set(world: World) -> None:
    """Raw cosine is not comparable to NEUTRAL_SIMILARITY. Feeding it in
    subtracted ~0.22 from *every* candidate the moment a teacher typed
    anything, so an intent made the list look uniformly worse and a teacher
    was better off leaving the box empty.

    The invariant after normalising: either the intent gave no usable signal
    and every term is neutral, or it did and at least one candidate sits at the
    top of the range. Never a set that is uniformly below neutral.
    """
    from alppy.services.retrieval import NEUTRAL_SIMILARITY

    for intent in ("fractions", "géométrie triangle angles", "zzz qqq xxx"):
        candidates = retrieval.gather_candidates(
            world.db,
            school_id=world.school_id,
            subject_id=world.subject_id,
            chapter_ids=[],
            competency_ids=None,
            intent=intent,
            language="fr",
            difficulty=None,
        )
        terms = [c.similarity_term for c in candidates]
        assert max(terms) >= NEUTRAL_SIMILARITY, (intent, max(terms))


def test_similarity_terms_are_neutral_without_signal_and_spread_with_it() -> None:
    from alppy.services.retrieval import NEUTRAL_SIMILARITY, similarity_terms

    assert similarity_terms([None, None]) == [NEUTRAL_SIMILARITY] * 2
    assert similarity_terms([0.0, 0.0, 0.0]) == [NEUTRAL_SIMILARITY] * 3
    assert similarity_terms([0.3, 0.3]) == [NEUTRAL_SIMILARITY] * 2
    spread = similarity_terms([0.4, 0.2, 0.0])
    assert spread[0] == 1.0 and spread[-1] == 0.0


def test_the_reason_never_claims_a_match_at_zero_similarity(world: World) -> None:
    """It used to print "close to your intent (similarity 0.00)" on rows whose
    similarity was exactly zero — asserting the one thing that was not true."""
    for intent in ("fractions", "zzz qqq xxx"):
        for proposal in _propose(world, intent, count=12):
            reason = proposal.provenance.reason
            if proposal.provenance.similarity in (None, 0.0):
                assert "0.00" not in reason, reason
