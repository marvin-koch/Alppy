"""``misconception_note``, sheet lineage, and the group label on a copy.

Three things the "common sheet -> N personalised groups" workflow needs, and
one of them is only a column because a bug forced it to be.

``sheet.derived_from_id`` is the lineage. A teaching unit is a common sheet and
the differentiated sheets its corrected results justify; nothing recorded that
one sheet answers another, so two rows with adjacent dates was all a timeline
could ever have shown.

``sheet_instance.group_label`` is a **label, not a foreign key**. There is no
group table: the partition is recomputed from mastery every time the teacher
asks for it, so a stored group would be stale as soon as the next scan lands,
and nothing downstream — mastery, attempts, scans — needs to know that a copy
belonged to one. ``sheet.target`` finally takes ``SheetTarget.GROUP``, which has
sat in the enum unused since 0001.

``sheet.feedback_pdf_key`` is the bug. Feedback pages are their own document,
never extra pages inside a copy, because ``scan_processing._copies_by_uid``
recomputes a copy's page count by re-paginating its *items* and the detector
then maps a photographed page with ``seen[uid] % len(printed_pages)``. A page
the renderer emits and that count does not know about rotates every later page
of the copy onto the wrong item list — silently, with confident detections, and
with every unit test still green. A separate document cannot desynchronise,
whatever is approved, discarded or regenerated afterwards.

``misconception_note`` carries the per-student explanation. It is gated by
``approved_at`` exactly as ``exercise`` is: an unreviewed generated exercise is
a bad question a teacher can spot on the page, an unreviewed generated note is
a claim about how a named child thinks, handed to that child.

``job_kind`` gains ``GENERATE_FEEDBACK``: one model call per student is worker
work, not something a request handler may block on.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Adding a value to a Postgres enum cannot share a transaction with DDL
        # that then uses it. On SQLite (the unit-test database) Enum is a
        # VARCHAR + CHECK rebuilt from the model metadata: nothing to alter.
        op.execute("COMMIT")
        op.execute("ALTER TYPE job_kind ADD VALUE IF NOT EXISTS 'GENERATE_FEEDBACK'")

    op.create_table(
        "misconception_note",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("based_on_sheet_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("language", sa.String(length=5), nullable=False),
        sa.Column("notes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "competency_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generation_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_misconception_note"),
        sa.ForeignKeyConstraint(
            ["school_id"], ["school.id"], name="fk_misconception_note_school", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["student_id"], ["student.id"], name="fk_misconception_note_student",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subject.id"], name="fk_misconception_note_subject",
            ondelete="CASCADE",
        ),
        # SET NULL, not CASCADE: deleting the sheet must not silently delete the
        # explanation of what a child misunderstood.
        sa.ForeignKeyConstraint(
            ["based_on_sheet_id"], ["sheet.id"], name="fk_misconception_note_sheet",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_misconception_note_student_sheet",
        "misconception_note",
        ["student_id", "based_on_sheet_id"],
    )
    # `models._fk` declares index=True on every foreign key, so each one needs
    # its index here under the name SQLAlchemy would generate — otherwise the
    # schema and the ORM disagree and autogenerate proposes them forever.
    for column in ("school_id", "student_id", "subject_id", "based_on_sheet_id"):
        op.create_index(f"ix_misconception_note_{column}", "misconception_note", [column])

    op.add_column("sheet", sa.Column("derived_from_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_sheet_derived_from", "sheet", "sheet", ["derived_from_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_sheet_derived_from_id", "sheet", ["derived_from_id"])
    op.add_column("sheet", sa.Column("feedback_pdf_key", sa.String(length=500), nullable=True))

    op.add_column("sheet_instance", sa.Column("group_label", sa.String(length=60), nullable=True))
    op.add_column(
        "sheet_instance", sa.Column("feedback_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_sheet_instance_feedback",
        "sheet_instance",
        "misconception_note",
        ["feedback_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_sheet_instance_feedback_id", "sheet_instance", ["feedback_id"])


def downgrade() -> None:
    op.drop_index("ix_sheet_instance_feedback_id", table_name="sheet_instance")
    op.drop_constraint("fk_sheet_instance_feedback", "sheet_instance", type_="foreignkey")
    op.drop_column("sheet_instance", "feedback_id")
    op.drop_column("sheet_instance", "group_label")
    op.drop_column("sheet", "feedback_pdf_key")
    op.drop_index("ix_sheet_derived_from_id", table_name="sheet")
    op.drop_constraint("fk_sheet_derived_from", "sheet", type_="foreignkey")
    op.drop_column("sheet", "derived_from_id")
    for column in ("school_id", "student_id", "subject_id", "based_on_sheet_id"):
        op.drop_index(f"ix_misconception_note_{column}", table_name="misconception_note")
    op.drop_index("ix_misconception_note_student_sheet", table_name="misconception_note")
    op.drop_table("misconception_note")
    # 'GENERATE_FEEDBACK' is deliberately left in job_kind: removing a value
    # from a Postgres enum means rebuilding the type, and any job row still
    # carrying it would have to be rewritten first. Leaving it is inert.
