"""Asking a model which children belong together — carefully, and never alone.

`cluster_students` groups by principal gap, deterministically, and D33 chose that
because a teacher has to be able to state the rule to a parent: *students with
the same principal gap go together; if that gives more groups than you asked for,
the smallest merge; if fewer, the largest splits by severity.*

A model can see things that rule cannot — two children failing the same
competency for visibly different reasons, a group of one that would be better
absorbed. So this module offers it as an **opt-in second opinion**, and every
part of the design is about keeping the first opinion in charge:

* The deterministic partition is computed first and **sent as the seed**, so the
  model is revising a defensible answer rather than inventing one.
* The result is **validated against the roster** — every student exactly once,
  the right number of groups, none empty — and any deviation returns the seed.
* A provider failure, an unparsable answer, or the offline provider's honest
  empty all return the seed. There is no path where a model failure produces a
  worse partition rather than the deterministic one.
* **No group is persisted** either way (I-adaptive-10). The partition is
  recomputed from mastery every run, because a stored group is stale the moment
  the next scan lands.

The prompt sees opaque row ids — S1, S2 — and never a UID or a name. It does not
need to know who anyone is to say who belongs with whom.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from alppy.ai.audit import flush as flush_ai_log
from alppy.ai.client import AiClient, load_prompt, parse_json_response
from alppy.core.logging import get_logger
from alppy.models import Student
from alppy.models.enums import MasteryBand

if TYPE_CHECKING:
    from alppy.services.adaptive_service import Gap

log = get_logger(__name__)

CLUSTER_TEMPERATURE = 0.0
"""A partition a teacher cannot reproduce is one they cannot defend."""


def cluster_students_with_model(
    db: Session,
    *,
    school_id: uuid.UUID,
    students: Sequence[Student],
    gaps_by_student: dict[uuid.UUID, list[Gap]],
    seed: list[list[Student]],
    n_groups: int,
    competency_labels: dict[uuid.UUID, str],
    roster_names: list[str],
    ai: AiClient,
) -> tuple[list[list[Student]], bool]:
    """The model's partition when it is valid, the seed otherwise.

    Returns the partition and whether the model's answer was the one used, so
    the teacher can be told which rule produced the groups they are looking at.
    """
    if len(students) <= 1 or n_groups <= 1:
        return seed, False

    rows = {f"S{i}": student for i, student in enumerate(students, start=1)}
    by_id = {student.id: key for key, student in rows.items()}

    try:
        response, _record = ai.complete(
            prompt=load_prompt("cluster_students"),
            purpose="adaptive_cluster",
            values={
                "n_groups": n_groups,
                "seed_partition": _render_seed(seed, by_id),
                "students": _render_students(rows, gaps_by_student, competency_labels),
            },
            # Armed with the real roster: a competency label can carry a pupil's
            # name (a textbook's Léa is also in the class), and this prompt is
            # made of labels.
            student_names=roster_names,
            temperature=CLUSTER_TEMPERATURE,
        )
        flush_ai_log(db, school_id=school_id, ai=ai)
        payload = parse_json_response(response.text)
    except Exception as exc:
        log.warning("adaptive.cluster.failed", error=type(exc).__name__, groups=n_groups)
        return seed, False

    partition = _validate(payload, rows=rows, n_groups=n_groups)
    if partition is None:
        # Includes the offline provider's honest empty answer, which is the
        # common case in CI and in a keyless deployment.
        log.info("adaptive.cluster.rejected", groups=n_groups)
        return seed, False
    return partition, True


def _render_seed(seed: Sequence[Sequence[Student]], by_id: dict[uuid.UUID, str]) -> str:
    return "\n".join(
        f"Group {i}: " + ", ".join(by_id[s.id] for s in group)
        for i, group in enumerate(seed, start=1)
    ) or "(none)"


def _render_students(
    rows: dict[str, Student],
    gaps_by_student: dict[uuid.UUID, list[Gap]],
    competency_labels: dict[uuid.UUID, str],
) -> str:
    """One condensed line per pupil: the band and score of each weak competency.

    Condensed on purpose — the whole class in one call, and the model needs the
    shape of the need, not the history that produced it.
    """
    lines: list[str] = []
    for key, student in rows.items():
        gaps = gaps_by_student.get(student.id) or []
        if not gaps:
            lines.append(f"{key}: no assessed gaps")
            continue
        parts = [
            f"{competency_labels.get(g.competency_id, str(g.competency_id))}"
            f" ({_band_word(g.band)} {g.score:.2f})"
            for g in gaps[:4]
        ]
        lines.append(f"{key}: " + "; ".join(parts))
    return "\n".join(lines)


_BAND_WORDS: dict[MasteryBand, str] = {
    MasteryBand.FADING: "fading",
    MasteryBand.WEAK: "fragile",
    MasteryBand.OK: "ok",
    MasteryBand.SOLID: "solid",
    MasteryBand.NONE: "unassessed",
}


def _band_word(band: MasteryBand) -> str:
    return _BAND_WORDS.get(band, "unknown")


def _validate(
    payload: dict[str, Any], *, rows: dict[str, Student], n_groups: int
) -> list[list[Student]] | None:
    """The model's answer, or None if it is not a partition of this class.

    Not a repair. A partition that drops a child, seats one twice, or invents an
    id is not "nearly right" — it is a different question answered, and the
    deterministic rule is standing right there.
    """
    groups = payload.get("groups")
    if not isinstance(groups, list) or len(groups) != n_groups:
        return None

    assigned: list[list[Student]] = []
    seen: set[str] = set()
    for entry in groups:
        if not isinstance(entry, dict):
            return None
        members = entry.get("students")
        if not isinstance(members, list) or not members:
            return None  # an empty group is a sheet nobody receives
        group: list[Student] = []
        for key in members:
            if not isinstance(key, str) or key not in rows or key in seen:
                return None  # unknown id, or a child seated twice
            seen.add(key)
            group.append(rows[key])
        assigned.append(group)

    if seen != set(rows):
        return None  # somebody was left out
    return assigned


__all__ = ["cluster_students_with_model"]
