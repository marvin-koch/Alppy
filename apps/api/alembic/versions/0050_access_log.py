"""Reading a pupil's record leaves a trace.

`event` is the WRITE log — eleven verbs, product prose, written for a teacher
to read on the agenda. It answers "what happened to this class". It cannot
answer the question a parent or a cantonal DPO actually asks, which is **"who
looked at my child's file"**, because looking left no trace at all (audit H7).

`access_log` is that trace: append-only, no endpoint, nothing updates or
deletes a row but the retention sweep.

**Where the write goes, and why not where the plan said.** The plan put it in
`deps.get_membership`, which resolves actor and tenant on every request — but
not WHICH pupil was read, and this table has `subject_type`/`subject_id`
because a log without subjects cannot answer the question. So the write sits at
the two gates that already decide whether this teacher may see this child,
`mastery_service._owned_student` and `class_service.get_student`, with actor
and tenant still coming from the `Scope` that `get_membership` built. Same
columns, same guarantee that both are known; a call site that knows the answer
to all three.

**`subject_id` is not a foreign key**, and that is the point. "Who read this
pupil's file" is most worth asking about a pupil who has since been deleted; a
foreign key would cascade the answer away along with the question.

**No names.** Two ids. Resolving them is a deliberate query against the tables
that hold names, which is what keeps this table safe to keep after a pupil has
been anonymised (0041).

**RLS.** `SchoolScopedMixin`, so it needs its own policy written here — 0024's
list is a frozen snapshot and does not grow, and `scripts/check-rls.py` fails
CI on a scoped table without one.

Retention is `ALPPY_ACCESS_LOG_RETENTION_DAYS`, swept by
`python -m alppy.cli purge-access-log`, and defaults to 365 rather than the
prompt log's 30: an access trail that expires inside a school year cannot
answer a question asked at the end of one.

Revision ID: 0050
Revises: 0049
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None

CURRENT_SCHOOL = "nullif(current_setting('app.current_school_id', true), '')::uuid"
#: Member names, like every enum since 0001 — that is what SQLAlchemy sends.
_SUBJECTS = ("STUDENT", "CLASS")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(*_SUBJECTS, name="access_subject").create(bind, checkfirst=True)

    op.create_table(
        "access_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("teacher_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "subject_type",
            postgresql.ENUM(*_SUBJECTS, name="access_subject", create_type=False),
            nullable=False,
        ),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["school_id"], ["school.id"], name="fk_access_log_school_id_school",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["teacher_id"], ["teacher.id"], name="fk_access_log_teacher_id_teacher",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_access_log"),
    )
    op.create_index("ix_access_log_school_id", "access_log", ["school_id"])
    op.create_index(
        "ix_access_log_subject", "access_log", ["subject_type", "subject_id", "occurred_at"]
    )
    op.create_index("ix_access_log_teacher", "access_log", ["teacher_id", "occurred_at"])

    op.execute('ALTER TABLE "access_log" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "access_log" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY tenant_isolation ON "access_log" '
        f"USING (school_id = {CURRENT_SCHOOL}) "
        f"WITH CHECK (school_id = {CURRENT_SCHOOL})"
    )


def downgrade() -> None:
    """Drops the trail. There is no lossless way to un-keep a record."""
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "access_log"')
    op.drop_index("ix_access_log_teacher", table_name="access_log")
    op.drop_index("ix_access_log_subject", table_name="access_log")
    op.drop_index("ix_access_log_school_id", table_name="access_log")
    op.drop_table("access_log")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(name="access_subject").drop(bind, checkfirst=True)
