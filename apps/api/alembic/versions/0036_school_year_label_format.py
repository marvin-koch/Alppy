"""A school year is written `2026/27`, and the database says so.

`SchoolYear.label` was a free `String(20)`, and the label is not decoration:
`current_school_year` looks a year up BY LABEL when no row is marked current.
So `2026/2027` and `2026/27` would be two different years for one school — two
rosters, two sets of UIDs, and a class quietly created in the wrong one, which
is exactly the state B3 showed is dangerous once a UID has to resolve inside a
year.

`LIKE` with `_` wildcards rather than a regular expression: `~` is Postgres-only
and the test suite builds its schema on SQLite (D18), where a constraint the
tests cannot run is a constraint nobody has.
"""

from __future__ import annotations

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_school_year_label", "school_year", "label LIKE '____/__'"
    )


def downgrade() -> None:
    op.drop_constraint("ck_school_year_label", "school_year", type_="check")
