"""The demo class and its history.

The definition of done asks a reviewer on a clean laptop to open class 7B and
see a five-band mastery matrix that looks like a real classroom. That means the
seed cannot be random: a uniformly random matrix reads as noise, and a
uniformly good one proves nothing. So each demo student gets a *profile* — a
per-competency ability and a work pattern — and three weeks of attempts are
simulated from it. The bands then come out of the real mastery model rather
than being written down, which also means the seed exercises the model.

No real student names. The roster below is invented, using name shapes common in
Suisse romande and Deutschschweiz so the demo reads as plausible.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

DEMO_CLASS_CODE = "7B"
DEMO_TEACHER_EMAIL = "demo@alppy.ch"
DEMO_TEACHER_PASSWORD = "alppy-demo-2026"
DEMO_SCHOOL = "Collège de démonstration"

# Invented names. Any resemblance to a real pupil is unintended.
DEMO_ROSTER: list[tuple[str, str]] = [
    ("Léa", "Progin"),
    ("Noah", "Bettschen"),
    ("Elif", "Yilmaz"),
    ("Mathis", "Chevalley"),
    ("Sofia", "Rrahmani"),
    ("Jonas", "Wyss"),
    ("Amélie", "Dubath"),
    ("Luca", "Pedrazzini"),
    ("Nora", "Steiner"),
    ("Théo", "Marchand"),
    ("Ines", "Haddad"),
    ("Robin", "Zürcher"),
    ("Clara", "Bähler"),
    ("Adrien", "Fasel"),
    ("Maya", "Lehmann"),
    ("Yanis", "Aebischer"),
    ("Julie", "Rochat"),
    ("Samuel", "Kunz"),
]


@dataclass(frozen=True, slots=True)
class StudentProfile:
    """What kind of learner this is. Drives the simulated history."""

    ability: float  # 0..1 baseline chance of getting a mid-difficulty item right
    consistency: float  # 0..1; low means erratic performance
    participation: float  # 0..1 chance of being present for a given sheet
    improving: float  # -0.3..+0.3 drift in ability across the three weeks
    weak_chapters: tuple[str, ...] = ()  # extra penalty on these chapter keys


# A deliberate spread, so the matrix shows all five bands and the adaptive
# feature has real targets. Calibrated against the band thresholds rather than
# picked by feel: the median student sits around 0.82, which lands in "to
# review" once the recency factor is applied, a few reach "solid", and a real
# tail sits in "fragile"/"fading" so there is something to differentiate for.
# A class whose median reads "fading" would be a broken demo, not a candid one.
DEMO_PROFILES: dict[str, StudentProfile] = {
    "Léa": StudentProfile(0.96, 0.92, 1.0, 0.02),
    "Noah": StudentProfile(0.74, 0.55, 0.9, 0.18, ("fractions",)),
    "Elif": StudentProfile(0.93, 0.88, 1.0, 0.05),
    "Mathis": StudentProfile(0.58, 0.45, 0.8, 0.10, ("fractions", "linear-equations")),
    "Sofia": StudentProfile(0.87, 0.78, 1.0, 0.0),
    "Jonas": StudentProfile(0.68, 0.58, 0.7, -0.12, ("proportionality",)),
    "Amélie": StudentProfile(0.94, 0.9, 1.0, 0.0),
    "Luca": StudentProfile(0.80, 0.62, 0.95, 0.08),
    "Nora": StudentProfile(0.90, 0.83, 1.0, 0.04),
    "Théo": StudentProfile(0.52, 0.48, 0.6, 0.05, ("fractions", "areas-volumes")),
    "Ines": StudentProfile(0.92, 0.87, 1.0, -0.02),
    "Robin": StudentProfile(0.82, 0.52, 0.9, 0.0, ("data-probability",)),
    "Clara": StudentProfile(0.97, 0.95, 1.0, 0.0),
    "Adrien": StudentProfile(0.71, 0.55, 0.85, 0.15),
    "Maya": StudentProfile(0.85, 0.72, 1.0, 0.06),
    "Yanis": StudentProfile(0.62, 0.48, 0.75, -0.08, ("linear-equations",)),
    "Julie": StudentProfile(0.93, 0.89, 1.0, 0.03),
    "Samuel": StudentProfile(0.78, 0.62, 0.9, 0.12, ("proportionality",)),
}

# Three weeks of lessons, most recent last. Each is (days_ago, chapter_key).
DEMO_LESSONS: list[tuple[int, str]] = [
    (19, "fractions"),
    (17, "fractions"),
    (14, "proportionality"),
    (12, "proportionality"),
    (10, "linear-equations"),
    (7, "linear-equations"),
    (5, "plane-geometry"),
    (3, "areas-volumes"),
    (1, "data-probability"),
    # "percentages" is deliberately never taught in the demo, so the matrix shows
    # the "not yet seen" band rather than implying every competency is assessed.
]


def _success_probability(
    profile: StudentProfile, difficulty: int, chapter_key: str, progress: float
) -> float:
    """Chance this student gets this item right.

    ``progress`` is 0 at the start of the three weeks and 1 at the end, so the
    ``improving`` drift shows up as a trend the curve on the student profile can
    actually display.
    """
    ability = profile.ability + profile.improving * progress
    # Difficulty 3 is the reference; each step moves the odds by ~9 points.
    ability -= (difficulty - 3) * 0.09
    if chapter_key in profile.weak_chapters:
        ability -= 0.25
    return max(0.02, min(0.98, ability))


def simulate_attempts(
    *,
    now: datetime,
    exercises_by_chapter: dict[str, list[tuple[str, int]]],
    seed: int = 20260905,
) -> list[dict[str, object]]:
    """Generate the demo attempt history.

    ``exercises_by_chapter`` maps a chapter key to ``(exercise_key, difficulty)``
    pairs. Returns plain dicts so this module stays free of SQLAlchemy and can be
    unit-tested on its own; the loader turns them into ``Attempt`` rows.
    """
    rng = random.Random(seed)
    attempts: list[dict[str, object]] = []
    total_lessons = len(DEMO_LESSONS)

    for lesson_index, (days_ago, chapter_key) in enumerate(DEMO_LESSONS):
        pool = exercises_by_chapter.get(chapter_key, [])
        if not pool:
            continue
        answered_at = now - timedelta(days=days_ago, hours=rng.uniform(0, 6))
        progress = lesson_index / max(1, total_lessons - 1)
        # A sheet is 8-12 items drawn from the chapter.
        items = rng.sample(pool, k=min(len(pool), rng.randint(8, 12)))

        for first_name, _last in DEMO_ROSTER:
            profile = DEMO_PROFILES[first_name]
            if rng.random() > profile.participation:
                continue  # absent that day
            for exercise_key, difficulty in items:
                p = _success_probability(profile, difficulty, chapter_key, progress)
                # Consistency widens the spread around the expected outcome: an
                # erratic student sometimes aces a hard item and fumbles an easy one.
                noise = (1.0 - profile.consistency) * rng.uniform(-0.35, 0.35)
                correct = rng.random() < max(0.02, min(0.98, p + noise))
                attempts.append(
                    {
                        "student_first_name": first_name,
                        "exercise_key": exercise_key,
                        "chapter_key": chapter_key,
                        "difficulty": difficulty,
                        "correct": correct,
                        "answered_at": answered_at,
                    }
                )

    return attempts
