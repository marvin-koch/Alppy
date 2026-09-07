"""Partitioning a class into N personalised groups.

The rule has to be one a teacher can state and defend, so the tests are written
against the statement of it: *students with the same principal gap go together;
too many groups merge the smallest, too few split the largest.*

The two properties that must never break are the boring ones — nobody is lost
and nobody is duplicated — because either would show up as a child with no
sheet at the photocopier.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from alppy.models.enums import MasteryBand
from alppy.services.adaptive_service import Gap, cluster_students


@dataclass
class _Student:
    """Only what the partition reads: an id, a roster number, a uid."""

    id: uuid.UUID
    number: int
    uid: str


def _class(spec: list[tuple[str, MasteryBand, float]]) -> tuple[
    list[_Student], dict[uuid.UUID, list[Gap]]
]:
    """A class where each student is (principal gap key, band, score)."""
    gap_ids: dict[str, uuid.UUID] = {}
    students: list[_Student] = []
    gaps: dict[uuid.UUID, list[Gap]] = {}
    for i, (key, band, score) in enumerate(spec, start=1):
        student = _Student(id=uuid.uuid4(), number=i, uid=f"7B_{i:02d}")
        students.append(student)
        if key == "":
            gaps[student.id] = []  # nothing assessed: an absence, not a weakness
            continue
        cid = gap_ids.setdefault(key, uuid.uuid4())
        gaps[student.id] = [
            Gap(competency_id=cid, band=band, score=score, target_difficulty=3)
        ]
    return students, gaps


FIVE_GAPS = [
    ("FR", MasteryBand.FADING, 0.42),
    ("FR", MasteryBand.FADING, 0.51),
    ("FR", MasteryBand.WEAK, 0.63),
    ("FR", MasteryBand.WEAK, 0.71),
    ("FR", MasteryBand.OK, 0.78),
    ("OP", MasteryBand.FADING, 0.38),
    ("OP", MasteryBand.FADING, 0.55),
    ("OP", MasteryBand.WEAK, 0.66),
    ("OP", MasteryBand.WEAK, 0.73),
    ("PY", MasteryBand.OK, 0.80),
    ("PY", MasteryBand.OK, 0.84),
    ("PY", MasteryBand.WEAK, 0.69),
    ("PR", MasteryBand.WEAK, 0.61),
    ("PR", MasteryBand.FADING, 0.47),
    ("ST", MasteryBand.SOLID, 0.93),
    ("ST", MasteryBand.SOLID, 0.95),
    ("ST", MasteryBand.SOLID, 0.91),
    ("ST", MasteryBand.SOLID, 0.97),
]


def _uids(clusters: list[list[_Student]]) -> list[str]:
    return sorted(s.uid for cluster in clusters for s in cluster)


def test_every_student_lands_in_exactly_one_group_at_every_size() -> None:
    """The property a teacher notices at the photocopier, not in a test."""
    students, gaps = _class(FIVE_GAPS)
    everyone = sorted(s.uid for s in students)
    for n in range(1, len(students) + 2):
        clusters = cluster_students(students, gaps, n_groups=n)
        assert _uids(clusters) == everyone, f"n={n} lost or duplicated a student"
        assert all(cluster for cluster in clusters), f"n={n} produced an empty group"


def test_one_group_is_the_whole_class_and_matches_the_old_behaviour() -> None:
    students, gaps = _class(FIVE_GAPS)
    assert cluster_students(students, gaps, n_groups=1) == [students]


def test_students_with_the_same_principal_gap_are_kept_together() -> None:
    """At the natural number of groups, nobody is split from their own gap."""
    students, gaps = _class(FIVE_GAPS)
    clusters = cluster_students(students, gaps, n_groups=5)

    principal = {
        s.uid: (gaps[s.id][0].competency_id if gaps[s.id] else None) for s in students
    }
    for cluster in clusters:
        keys = {principal[s.uid] for s in cluster}
        assert len(keys) == 1, "a group mixes two different principal gaps"


def test_too_few_groups_merges_rather_than_dropping_anyone() -> None:
    students, gaps = _class(FIVE_GAPS)
    clusters = cluster_students(students, gaps, n_groups=3)
    assert len(clusters) == 3
    assert _uids(clusters) == sorted(s.uid for s in students)


def test_more_groups_than_gaps_splits_the_largest() -> None:
    students, gaps = _class(FIVE_GAPS)
    clusters = cluster_students(students, gaps, n_groups=8)
    assert len(clusters) == 8
    assert _uids(clusters) == sorted(s.uid for s in students)
    # A split separates by severity, so no group spans the whole band range.
    assert max(len(c) for c in clusters) <= 3


def test_the_neediest_group_comes_first() -> None:
    """Group 1 is the group that needs the most, every time it is run."""
    students, gaps = _class(FIVE_GAPS)
    clusters = cluster_students(students, gaps, n_groups=4)

    def severity(cluster: list[_Student]) -> float:
        ranks = []
        for s in cluster:
            g = gaps[s.id]
            ranks.append(0 if not g else {"fading": 0, "weak": 1, "ok": 2, "solid": 3}[g[0].band])
        return sum(ranks) / len(ranks)

    scores = [severity(c) for c in clusters]
    assert scores == sorted(scores), "groups are not ordered worst-first"


def test_the_partition_is_stable_across_runs() -> None:
    """A teacher must not be shown a reshuffled class for no reason."""
    students, gaps = _class(FIVE_GAPS)
    first = cluster_students(students, gaps, n_groups=4)
    second = cluster_students(students, gaps, n_groups=4)
    assert [[s.uid for s in c] for c in first] == [[s.uid for s in c] for c in second]


def test_a_student_with_no_assessed_gap_sorts_last_not_first() -> None:
    """An absence of evidence is not a weakness — `mastery_service` says the
    same thing about the matrix, and the grouping must not contradict it."""
    students, gaps = _class(
        [("OP", MasteryBand.FADING, 0.30), ("", MasteryBand.NONE, 0.0), ("OP", MasteryBand.WEAK, 0.7)]
    )
    clusters = cluster_students(students, gaps, n_groups=2)
    unassessed = students[1].uid
    # The unassessed student is never in the neediest group.
    assert unassessed not in [s.uid for s in clusters[0]]


def test_a_single_student_class_is_one_group() -> None:
    students, gaps = _class([("OP", MasteryBand.WEAK, 0.6)])
    assert cluster_students(students, gaps, n_groups=4) == [students]
