"""A job belongs to a class, a branch and the teacher who queued it.

``job`` carried ``school_id`` and nothing else, so every predicate about one
was tenant-grained. Two things followed from that, both live (audit 02, C1):

* The in-flight guard on ``POST /adaptive/propose`` matched on school, kind and
  status alone. A second teacher clicking while a colleague's proposal ran was
  handed the colleague's job id — not an error, by design, except that the
  design assumed one teacher per school.
* ``GET /adaptive/proposal/{job_id}`` then checked only that the job's school
  matched the caller's, and served a per-pupil plan for a class the caller does
  not teach: which children are behind, on what, and what each should do next.

The alternative was to keep matching into ``payload`` by string, which several
handlers already do and which is the root cause worth removing once (M5, L1).

All three are nullable: most job kinds are not about one class. A source
ingest belongs to the staffroom corpus, and a backfill to nobody.

``created_by_id`` is ON DELETE SET NULL rather than CASCADE — a teacher leaving
the school must not take the record of the work they queued with them. The
other two cascade: a job for a class that no longer exists is not a job.

Backfill is deliberate but partial. ``class_id`` and ``subject_id`` can be
recovered for the kinds that wrote them into ``payload``; ``created_by_id``
cannot be recovered at all, because it was never recorded anywhere. Old rows
keep a null and are therefore invisible to the narrowed guard, which is the
safe direction: a stale queued job stops suppressing a new proposal.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job", sa.Column("class_id", sa.Uuid(), nullable=True))
    op.add_column("job", sa.Column("subject_id", sa.Uuid(), nullable=True))
    op.add_column("job", sa.Column("created_by_id", sa.Uuid(), nullable=True))

    op.create_foreign_key(
        "fk_job_class_id_class", "job", "class", ["class_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_job_subject_id_subject",
        "job",
        "subject",
        ["subject_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_job_created_by_id_teacher",
        "job",
        "teacher",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index("ix_job_class_id", "job", ["class_id"])
    op.create_index("ix_job_subject_id", "job", ["subject_id"])
    op.create_index("ix_job_created_by_id", "job", ["created_by_id"])

    # Recover what `payload` happens to hold. A cast through the FK's own table
    # rather than a bare cast: a payload written before the class was deleted
    # would otherwise fail the constraint that was just added.
    op.execute(
        """
        UPDATE job
           SET class_id = c.id
          FROM class c
         WHERE job.class_id IS NULL
           AND job.payload ? 'class_id'
           AND c.id = (job.payload ->> 'class_id')::uuid
        """
    )
    op.execute(
        """
        UPDATE job
           SET subject_id = s.id
          FROM subject s
         WHERE job.subject_id IS NULL
           AND job.payload ? 'subject_id'
           AND s.id = (job.payload ->> 'subject_id')::uuid
        """
    )


def downgrade() -> None:
    op.drop_index("ix_job_created_by_id", table_name="job")
    op.drop_index("ix_job_subject_id", table_name="job")
    op.drop_index("ix_job_class_id", table_name="job")
    op.drop_constraint("fk_job_created_by_id_teacher", "job", type_="foreignkey")
    op.drop_constraint("fk_job_subject_id_subject", "job", type_="foreignkey")
    op.drop_constraint("fk_job_class_id_class", "job", type_="foreignkey")
    op.drop_column("job", "created_by_id")
    op.drop_column("job", "subject_id")
    op.drop_column("job", "class_id")
