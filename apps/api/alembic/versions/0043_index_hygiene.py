"""Three indexes nothing could use, and eighteen nothing ever did.

Two halves of the same audit finding, shipped together because they are one
question asked twice: does a lookup this schema actually performs have a btree
that answers it, and is every btree answering one?

**The three that were missing (M1).** A foreign key with no index makes the
referenced side's DELETE scan the whole child table, and the tree reads here
go the same direction:

* ``chapter_competency.competency_id`` — the composite PK indexes
  ``(chapter_id, competency_id)``, so "what does this Theme credit" is fast and
  "which Themes credit this competency" is a seq scan. 0039 made exactly this
  argument for ``exercise_competency``; this is its other half.
* ``class_subject.subject_id`` — same shape, and it is what a subject delete
  has to ask.
* ``competency.parent_id`` — the curriculum tree walks children-of-a-node on
  every tree render, and ``ondelete="SET NULL"`` makes Postgres find every
  child of a deleted row.

**The eighteen that were redundant (M2).** Each is a single-column index whose
column is already the LEADING column of a composite on the same table, so the
btree prefix answers every lookup the standalone one could. They were written
on every insert and chosen by the planner never.

The list is derived, not copied. The audit named seventeen; the schema has
moved eleven migrations since, and re-deriving it against the live catalogue
gives eighteen — which is the point of deriving it. The rule: non-unique,
non-partial, btree, single column, and some other non-partial btree on the same
table starts with that column.

Of those eighteen, seven are ``school_id``. That one deserves its own sentence,
because dropping a tenancy index sounds like exactly the wrong thing to do:
`0024`'s RLS policy compares ``school_id`` on **every statement**, so an
unindexed one is a seq scan per policy evaluation. These seven are dropped only
because a composite on the same table *starts* with ``school_id`` —
``uq_student_uid``, ``uq_class_code``, ``ix_event_school_occurred`` and so on —
and a prefix scan is the same scan. The tables where nothing leads with it keep
theirs; ``attempt`` is one, and its ``ix_attempt_school_id`` is untouched here.

The models say the same thing, so the drift gate can check it: an opt-out on
``SchoolScopedMixin`` for the first kind, ``_fk(index=False)`` for the second,
and each site names the index that covers it.

**No ``CONCURRENTLY``.** Dropping an index takes a brief ``ACCESS EXCLUSIVE``
lock and nothing is rebuilt, so the transactional form is both safe and
honest — unlike 0042, which had to leave the transaction to avoid holding one
for the length of an HNSW build. The three creations are on tables that are
small and stay small (the curriculum is seeded reference data, and a class's
declared branches are single digits).

Reversible exactly: ``downgrade`` recreates the eighteen and drops the three.

Revision ID: 0043
Revises: 0042
"""

from __future__ import annotations

from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None

#: index name -> (table, columns). Missing, and each one a lookup the schema
#: actually performs.
_MISSING = {
    "ix_chapter_competency_competency_id": ("chapter_competency", ["competency_id"]),
    "ix_class_subject_subject_id": ("class_subject", ["subject_id"]),
    "ix_competency_parent_id": ("competency", ["parent_id"]),
}

#: index name -> (table, columns, the composite whose prefix already answers it)
_REDUNDANT = {
    "ix_answer_box_placement_sheet_id": (
        "answer_box_placement", ["sheet_id"], "uq_answer_box_placement_slot",
    ),
    "ix_attempt_person_id": ("attempt", ["person_id"], "ix_attempt_person_answered"),
    "ix_chapter_school_id": ("chapter", ["school_id"], "uq_chapter_key"),
    "ix_class_school_id": ("class", ["school_id"], "uq_class_code"),
    "ix_event_school_id": ("event", ["school_id"], "ix_event_school_occurred"),
    "ix_exercise_source_section_id": (
        "exercise", ["source_section_id"], "ix_exercise_source_section",
    ),
    "ix_exercise_subject_id": ("exercise", ["subject_id"], "ix_exercise_subject_origin"),
    "ix_idempotency_key_school_id": (
        "idempotency_key", ["school_id"], "uq_idempotency_key",
    ),
    "ix_mastery_branch_snapshot_person_id": (
        "mastery_branch_snapshot", ["person_id"], "ix_mastery_branch_person",
    ),
    "ix_mastery_snapshot_person_id": (
        "mastery_snapshot", ["person_id"], "ix_mastery_person_competency",
    ),
    "ix_misconception_note_person_id": (
        "misconception_note", ["person_id"], "ix_misconception_note_person_sheet",
    ),
    "ix_prompt_log_school_id": ("prompt_log", ["school_id"], "ix_prompt_log_school_created"),
    "ix_sheet_instance_sheet_id": ("sheet_instance", ["sheet_id"], "uq_instance_student"),
    "ix_sheet_item_sheet_id": ("sheet_item", ["sheet_id"], "uq_sheet_item_position"),
    "ix_source_chunk_source_id": (
        "source_chunk", ["source_id"], "ix_source_chunk_source_page",
    ),
    "ix_source_section_source_id": (
        "source_section", ["source_id"], "ix_source_section_source",
    ),
    "ix_student_school_id": ("student", ["school_id"], "uq_student_uid"),
    "ix_subject_school_id": ("subject", ["school_id"], "uq_subject_key"),
}


def upgrade() -> None:
    for name, (table, columns) in _MISSING.items():
        op.create_index(name, table, columns)

    for name, (table, _columns, _covered_by) in _REDUNDANT.items():
        op.drop_index(name, table_name=table)


def downgrade() -> None:
    """Exact. Nothing here holds data, so nothing here can lose any."""
    for name, (table, columns, _covered_by) in _REDUNDANT.items():
        op.create_index(name, table, columns)

    for name, (table, _columns) in _MISSING.items():
        op.drop_index(name, table_name=table)
