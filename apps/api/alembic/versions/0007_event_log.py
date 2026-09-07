"""``event`` — the append-only log the agenda reads.

Why a log and not more columns
------------------------------
Every row already carries ``created_at`` and ``updated_at``, and neither can
answer what a teacher asks of a term. ``updated_at`` is overwritten by whatever
edit came last, so it can never say when a pile was *confirmed*; and the two
moments that matter most to the chronology — a sheet going to the photocopier,
a scan being confirmed — left no trace anywhere in the schema. A column per
moment would mean a migration every time the product learns a new verb, and
would still not give one ordered query across all of them.

``subject_id`` is deliberately NOT a foreign key. The log has to outlive what
it describes: deleting a sheet does not un-print it, and one column cannot
point at four different tables. The reader resolves a title when the row is
still there and falls back to the stored ``summary`` when it is not — which is
why ``summary`` is NOT NULL and why it may never hold a student name.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_EVENT_KIND = (
    "SOURCE_IMPORTED",
    "CHAPTER_READ",
    "SHEET_CREATED",
    "SHEET_RENDERED",
    "SHEET_PRINTED",
    "SCAN_UPLOADED",
    "SCAN_CONFIRMED",
    "ADAPTIVE_PROPOSED",
    "ADAPTIVE_EXPORTED",
    "FEEDBACK_WRITTEN",
    "FEEDBACK_APPROVED",
)
_EVENT_SUBJECT = ("SOURCE", "SHEET", "SCAN", "CLASS")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Both types are new here, so they are created outright rather than
        # altered — no COMMIT dance is needed for a CREATE TYPE. The columns
        # below then reference them with `create_type=False`, exactly as 0001
        # does: a bare `sa.Enum` would ignore that flag (it is a postgresql
        # dialect kwarg) and CREATE TYPE a second time inside create_table.
        postgresql.ENUM(*_EVENT_KIND, name="event_kind").create(bind, checkfirst=True)
        postgresql.ENUM(*_EVENT_SUBJECT, name="event_subject").create(bind, checkfirst=True)

    op.create_table(
        "event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(*_EVENT_KIND, name="event_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "subject_type",
            postgresql.ENUM(*_EVENT_SUBJECT, name="event_subject", create_type=False),
            nullable=False,
        ),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("class_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_area_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("summary", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("id", name="pk_event"),
        sa.ForeignKeyConstraint(
            ["school_id"], ["school.id"], name="fk_event_school", ondelete="CASCADE"
        ),
        # The record of the lesson outlives the account that taught it.
        sa.ForeignKeyConstraint(
            ["actor_id"], ["teacher.id"], name="fk_event_teacher", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["class_id"], ["class.id"], name="fk_event_class", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["subject_area_id"], ["subject.id"], name="fk_event_subject", ondelete="SET NULL"
        ),
    )
    op.create_index("ix_event_school_occurred", "event", ["school_id", "occurred_at"])
    op.create_index("ix_event_subject", "event", ["subject_type", "subject_id"])
    op.create_index("ix_event_class_id", "event", ["class_id"])
    op.create_index("ix_event_actor_id", "event", ["actor_id"])
    op.create_index("ix_event_subject_area_id", "event", ["subject_area_id"])
    op.create_index("ix_event_school_id", "event", ["school_id"])


def downgrade() -> None:
    op.drop_index("ix_event_school_id", table_name="event")
    op.drop_index("ix_event_subject_area_id", table_name="event")
    op.drop_index("ix_event_actor_id", table_name="event")
    op.drop_index("ix_event_class_id", table_name="event")
    op.drop_index("ix_event_subject", table_name="event")
    op.drop_index("ix_event_school_occurred", table_name="event")
    op.drop_table("event")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(name="event_kind").drop(bind, checkfirst=True)
        postgresql.ENUM(name="event_subject").drop(bind, checkfirst=True)
