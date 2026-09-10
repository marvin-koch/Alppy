"""The synthetic roster staging runs on, and the corpus that proves it is synthetic.

Staging exists to be pointed at by real browsers, real uploads and real
scanners, and the one thing it must never hold is a real child. The demo seed
(`alppy.seed.demo`) already solves the *shape* of that problem — invented names,
profile-driven histories, bands that fall out of the real mastery model rather
than being written down — but it is sized for a laptop: one class of eighteen,
one of five, one of two. A staging deployment sized like that never exercises a
class list that scrolls, a mastery matrix that has to paginate, or a batch
render of a hundred and twenty pages.

So this module scales the same idea up, and adds the part staging specifically
needs: a **closed corpus**. Every name here is invented, and every name staging
holds must come from here. That is checkable, and `test_staging_seed.py` checks
it — which is what lets "no real student data outside production" be a property
somebody can verify rather than a habit somebody maintains.

Two schools on purpose, one PER and one LP21: sharing a chapter across cantons
is D56, and it is not exercised by a single-canton dataset.

Nothing here reads a name from a public dataset or a faker locale. The names are
written by hand in shapes common to Suisse romande and Deutschschweiz so the
data reads as plausible; any resemblance to a real pupil is unintended, and no
row is ever copied from production.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Final

from alppy.models.enums import CurriculumKind
from alppy.seed.demo import StudentProfile

#: Given names. Invented pairings; the shapes are regional, the people are not.
STAGING_GIVEN_NAMES: Final[tuple[str, ...]] = (
    "Aline", "Anouk", "Arnaud", "Basile", "Bastien", "Camille", "Chiara",
    "Clément", "Colin", "Corentin", "Damien", "Delphine", "Dorian", "Elias",
    "Elodie", "Emilie", "Enzo", "Fabienne", "Fabio", "Florian", "Gaëlle",
    "Gaspard", "Hugo", "Ilias", "Ilona", "Iris", "Janis", "Jérémie", "Joana",
    "Jules", "Kenza", "Killian", "Lara", "Lena", "Leonie", "Lilou", "Livio",
    "Loris", "Louna", "Malik", "Manon", "Marius", "Mathilde", "Melina",
    "Mila", "Nadia", "Nathan", "Nicolas", "Noé", "Ophélie", "Oscar", "Pauline",
    "Quentin", "Raphaël", "Rayan", "Romain", "Salomé", "Sandro", "Selma",
    "Simon", "Sonia", "Svenja", "Tania", "Timo", "Tristan", "Valentin",
    "Vera", "Yannick", "Zoé", "Aurélien", "Blaise",
)

#: Surnames. Same rule.
STAGING_SURNAMES: Final[tuple[str, ...]] = (
    "Aeberhard", "Amrein", "Ballmer", "Baumann", "Berset", "Bonvin", "Bornet",
    "Bregy", "Brunner", "Burri", "Carron", "Chappuis", "Constantin", "Crettaz",
    "Délèze", "Dorsaz", "Eggenberger", "Emery", "Fournier", "Frei", "Gabbud",
    "Gerber", "Gillioz", "Grandjean", "Häberli", "Hagmann", "Imboden",
    "Jaquier", "Jollien", "Kämpf", "Kohler", "Lauber", "Loretan", "Maillard",
    "Métrailler", "Moret", "Nanchen", "Oggier", "Perren", "Pfyffer", "Praz",
    "Quinodoz", "Rebord", "Rieder", "Roduit", "Salamin", "Schnyder", "Sierro",
    "Tornay", "Truffer", "Udry", "Vouilloz", "Walpen", "Zenhäusern", "Zufferey",
    "Bachmann", "Egli", "Furrer", "Graf", "Hediger", "Iten", "Jenni", "Keller",
    "Lehner", "Marti", "Niederer", "Ott", "Pfister", "Rüegg", "Stucki",
)

#: The whole of what a staging roster may contain, as a set for the guard test.
STAGING_NAME_CORPUS: Final[frozenset[str]] = frozenset(
    STAGING_GIVEN_NAMES
) | frozenset(STAGING_SURNAMES)

STAGING_TEACHER_DOMAIN: Final = "staging.alppy.invalid"
"""`.invalid` is reserved by RFC 2606 and can never resolve.

A staging account that accidentally sends mail — a reset, a notification, an
error report — must not be able to reach a real inbox, least of all a real
teacher's. The demo seed uses `@alppy.ch`, which is a domain someone owns.
"""


@dataclass(frozen=True, slots=True)
class StagingClass:
    """One class in the staging dataset."""

    code: str
    school: str
    size: int
    #: A class with a roster and nothing taught yet. Every "no history" empty
    #: state is otherwise unreachable without hand-editing the database, and an
    #: empty state nobody can reach is an empty state nobody has looked at.
    taught: bool = True


STAGING_SCHOOL_PER: Final = "Cycle d'orientation de Sion (staging)"
STAGING_SCHOOL_LP21: Final = "Oberstufe Chur (staging)"

STAGING_SCHOOLS: Final[dict[str, tuple[str, CurriculumKind]]] = {
    STAGING_SCHOOL_PER: ("VS", CurriculumKind.PER),
    STAGING_SCHOOL_LP21: ("GR", CurriculumKind.LP21),
}

#: Six classes of twenty across both curricula, plus the deliberately empty one.
#: Twenty is the number that matters: a class list of five fits on any screen
#: and a batch render of five pages finishes instantly, so neither tells you
#: anything about the product a teacher actually uses.
STAGING_CLASSES: Final[tuple[StagingClass, ...]] = (
    StagingClass("7A", STAGING_SCHOOL_PER, 20),
    StagingClass("7B", STAGING_SCHOOL_PER, 20),
    StagingClass("9C", STAGING_SCHOOL_PER, 20),
    StagingClass("8A", STAGING_SCHOOL_LP21, 20),
    StagingClass("8B", STAGING_SCHOOL_LP21, 20),
    StagingClass("10A", STAGING_SCHOOL_LP21, 20),
    StagingClass("11D", STAGING_SCHOOL_LP21, 18, taught=False),
)

#: Deterministic, so a staging rebuild produces the same roster and a bug report
#: naming "9C_14" still means the same student next week.
STAGING_SEED: Final = 20260910


def roster_for(class_code: str, size: int, *, seed: int = STAGING_SEED) -> list[tuple[str, str]]:
    """`size` invented (given, surname) pairs for one class.

    Seeded on the class code as well as the run, so two classes of the same size
    do not get identical rosters — which would make a cross-class bug invisible.
    Names may repeat across the whole dataset, as they do in a real school; the
    UID (`9C_14`) is the identifier, never the name.
    """
    rng = random.Random(f"{seed}:{class_code}")
    # Given names are drawn WITHOUT replacement inside a class. Two Lénas in one
    # room is realistic, but `_get_or_create_students` and the history simulator
    # both key a roster by first name, so a repeat would silently drop a pupil —
    # a nineteen-student "class of twenty" nobody notices. Surnames may repeat:
    # they are not used as a key, and siblings exist.
    given = rng.sample(STAGING_GIVEN_NAMES, k=min(size, len(STAGING_GIVEN_NAMES)))
    return [(name, rng.choice(STAGING_SURNAMES)) for name in given]


def profiles_for(
    class_code: str, roster: list[tuple[str, str]], *, seed: int = STAGING_SEED
) -> dict[str, StudentProfile]:
    """A learner profile per student, keyed by first name.

    Drawn rather than hand-written, but drawn from the same calibrated ranges
    the demo profiles were chosen in: the median sits around 0.82, which lands
    in "to review" once recency is applied, with a real tail below. A uniformly
    random class reads as noise and a uniformly strong one proves nothing —
    staging needs a matrix that looks like a classroom, because it is where
    somebody notices the matrix is wrong.
    """
    rng = random.Random(f"{seed}:profiles:{class_code}")
    profiles: dict[str, StudentProfile] = {}
    for first, _last in roster:
        profiles[first] = StudentProfile(
            ability=min(0.98, max(0.45, rng.gauss(0.82, 0.13))),
            consistency=min(0.97, max(0.40, rng.gauss(0.72, 0.15))),
            participation=min(1.0, max(0.60, rng.gauss(0.92, 0.10))),
            improving=rng.uniform(-0.15, 0.20),
            weak_chapters=tuple(
                rng.sample(
                    ("fractions", "proportionality", "linear-equations", "areas-volumes"),
                    k=rng.randint(0, 2),
                )
            ),
        )
    return profiles


def is_synthetic(first_name: str, last_name: str) -> bool:
    """Whether this pair could have come out of the corpus above.

    The guard test's predicate. It answers "could this row have been generated
    here", not "was it" — which is the right question: a real name that happens
    to match an invented one is indistinguishable and harmless, while a real
    name that does not match is exactly what has to be caught.
    """
    return first_name in STAGING_GIVEN_NAMES and last_name in STAGING_SURNAMES


def total_students() -> int:
    return sum(c.size for c in STAGING_CLASSES)


__all__ = [
    "STAGING_CLASSES",
    "STAGING_GIVEN_NAMES",
    "STAGING_NAME_CORPUS",
    "STAGING_SCHOOLS",
    "STAGING_SCHOOL_LP21",
    "STAGING_SCHOOL_PER",
    "STAGING_SEED",
    "STAGING_SURNAMES",
    "STAGING_TEACHER_DOMAIN",
    "StagingClass",
    "is_synthetic",
    "profiles_for",
    "roster_for",
    "total_students",
]
