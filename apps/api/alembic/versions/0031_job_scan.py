"""The pile a job is about, as a column.

``grading_in_progress`` answered "is a grader still coming for this scan?" by
loading every ``QUEUED`` or ``RUNNING`` job **in the deployment** and comparing
``payload["scan_id"]`` in Python. Three things wrong with that, and the third
is the one that reaches a teacher:

* it is unfiltered by school, so one school's confirmation walks another's rows;
* it cannot use an index, and it is asked on every confirmation;
* a job that died without writing a terminal status kept the answer at "yes"
  forever, and the only route past it was a database edit.

The column is what lets the question be a lookup, and it is what the stale-job
reaper keys on too (B9). CASCADE, because a job about a pile that no longer
exists has nothing left to be about.

Backfilled from the payload the handlers already wrote, so live jobs crossing
the deploy keep answering correctly.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job", sa.Column("scan_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_job_scan_id_scan", "job", "scan", ["scan_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_job_scan_id", "job", ["scan_id"])
    # The handlers have always written this into the payload; a job in flight
    # across the deploy must not read as "no scan" and slip past the guard.
    # Guarded by a uuid cast that cannot raise on a malformed value.
    op.execute(
        """
        UPDATE job
        SET scan_id = (payload ->> 'scan_id')::uuid
        WHERE payload ->> 'scan_id' ~
              '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
          AND EXISTS (SELECT 1 FROM scan WHERE scan.id = (payload ->> 'scan_id')::uuid)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_job_scan_id", table_name="job")
    op.drop_constraint("fk_job_scan_id_scan", "job", type_="foreignkey")
    op.drop_column("job", "scan_id")
