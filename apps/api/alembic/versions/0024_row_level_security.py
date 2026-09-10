"""Row-level security: the database stops taking the application's word for it.

Tenancy was entirely application-level. Every query carried its own
``.where(school_id == ...)``, `deps.scoped_get` was the blessed way to fetch a
row, and services took `school_id` as a required argument so forgetting it was
a type error. That is a good design and it stays — but its failure mode was
an unbounded cross-school read with nothing underneath it, and "nothing
underneath it" is the part this migration removes (D84).

Three pieces:

**Policies.** Every school-scoped table gets ``ENABLE`` *and* ``FORCE`` row
level security and one policy comparing its `school_id` to
``app.current_school_id``, set per transaction by `alppy/db/tenancy.py`.
``FORCE`` is not decoration: without it the table's owner is exempt, and the
owner is who alembic and the CLI connect as. ``WITH CHECK`` carries the same
predicate as ``USING``, so a write *into* another school is refused as firmly
as a read out of one.

The predicate is ``nullif(current_setting('app.current_school_id', true), '')::uuid``
rather than a bare cast. ``current_setting(..., true)`` returns NULL for a GUC
that was never set, and the empty string for one that was set to ''; the
``nullif`` collapses both to NULL, and a comparison against NULL admits no
rows. Unset therefore means **see nothing**, not see everything, and a bare
cast of '' would have raised instead — an error page where an empty list
belongs.

**The six association tables.** `class_student`, `class_subject`,
`class_teacher_subject`, `chapter_competency`, `exercise_competency` and
`sheet_source` carry no `school_id`, deliberately: the models argue that both
ends already do and tenancy holds transitively (I-platform-02). A policy is
where that argument stops being a comment and starts being enforced, so each
one is written as an EXISTS against the parent that does carry the column. No
column was added: adding one would have contradicted the models' own reasoning
and put a redundant, backfilled, drift-prone `school_id` on six tables to save
a primary-key lookup.

**`alppy_job_school`.** The worker's chicken-and-egg — the tenant is on the job
row it has not been allowed to read yet. A ``SECURITY DEFINER`` function that
takes a job id and returns a school id, and can say nothing else. One uuid of
escalation, in the spirit of `ModelCall` being content-free.

Not covered, each on purpose: `teacher` and `teacher_school` (a teacher spans
schools since D74, and both are read *before* any tenant is known, during
login), `competency` (the cantonal curriculum, shared by every school), and
`alembic_version`. `school` gets a policy of its own shape — see below.

Revision ID: 0024
Revises: 0023
"""

from __future__ import annotations

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


#: Frozen at the time this migration was written, NOT derived from
#: ``Base.metadata``. A migration is a snapshot: deriving the list would make
#: this one silently start covering tables added years later, which is both a
#: lie about what ran on any given database and a way for the coverage to look
#: complete while a policy was never actually created. Keeping every future
#: table covered is `scripts/check-rls.py`'s job, and it fails CI on a
#: `SchoolScopedMixin` table with no policy.
SCOPED_TABLES = (
    "adaptive_proposal",
    "answer_box_placement",
    "attempt",
    "chapter",
    "class",
    "detection",
    "event",
    "exercise",
    "exercise_variant",
    "job",
    "mastery_branch_snapshot",
    "mastery_snapshot",
    "misconception_note",
    "model_call",
    "prompt_log",
    "scan",
    "scan_page",
    "school_year",
    "sheet",
    "sheet_instance",
    "sheet_item",
    "source",
    "source_chunk",
    "source_section",
    "student",
    "subject",
)

#: table -> (local column, parent table, parent column). The parent carries the
#: `school_id`; the child is visible exactly when its parent is.
LINKED_TABLES = {
    "class_student": ("class_id", "class", "id"),
    "class_subject": ("class_id", "class", "id"),
    "class_teacher_subject": ("class_id", "class", "id"),
    "chapter_competency": ("chapter_id", "chapter", "id"),
    "exercise_competency": ("exercise_id", "exercise", "id"),
    "sheet_source": ("sheet_id", "sheet", "id"),
}

CURRENT_SCHOOL = "nullif(current_setting('app.current_school_id', true), '')::uuid"
CURRENT_TEACHER = "nullif(current_setting('app.current_teacher_id', true), '')::uuid"

POLICY = "tenant_isolation"


def _enable(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')


def _policy(table: str, predicate: str) -> None:
    op.execute(
        f'CREATE POLICY {POLICY} ON "{table}" '
        f"USING ({predicate}) WITH CHECK ({predicate})"
    )


def upgrade() -> None:
    for table in SCOPED_TABLES:
        _enable(table)
        _policy(table, f"school_id = {CURRENT_SCHOOL}")

    for table, (local, parent, parent_col) in LINKED_TABLES.items():
        _enable(table)
        # Spelled with the parent's own `school_id` rather than relying on the
        # parent's policy to filter the subquery. Policies DO apply inside
        # another policy's expression, so the short form would work — but it
        # would work for a reason a reader has to already know, and it would
        # stop working the day someone exempts the parent.
        _policy(
            table,
            f'EXISTS (SELECT 1 FROM "{parent}" p '
            f'WHERE p.{parent_col} = "{table}".{local} '
            f"AND p.school_id = {CURRENT_SCHOOL})",
        )

    # `school` is the one table a request legitimately reads across the tenant
    # boundary: since D74 a teacher may work at several, and login, `/auth/me`
    # and `POST /auth/school/{id}` all have to list or open one the current GUC
    # does not name. So the policy admits the current school OR any school this
    # teacher is a member of — which is the same question
    # `deps.get_membership` asks, asked again one layer down. Without the
    # second arm, switching school would 404 every school including the one you
    # are already in the middle of leaving.
    _enable("school")
    op.execute(
        f"CREATE POLICY {POLICY} ON school "
        f"USING (id = {CURRENT_SCHOOL} OR EXISTS ("
        f"  SELECT 1 FROM teacher_school ts"
        f"  WHERE ts.school_id = school.id AND ts.teacher_id = {CURRENT_TEACHER}"
        f")) "
        # A school is CREATED before anybody can be a member of it (D79), and
        # at that moment neither arm of USING can be true. The write side
        # therefore only asks that the row not claim to be a school the session
        # is not acting for.
        f"WITH CHECK (id = {CURRENT_SCHOOL} OR {CURRENT_SCHOOL} IS NULL)"
    )

    # The worker's one uuid of escalation. `search_path` is pinned because a
    # SECURITY DEFINER function that resolves `job` through a caller-controlled
    # search_path is a privilege-escalation bug with a CVE number waiting.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION alppy_job_school(job_id uuid)
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = public, pg_temp
        AS $$ SELECT school_id FROM job WHERE id = job_id $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION alppy_job_school(uuid) FROM PUBLIC")

    # The runtime role is created by `infra/postgres/init.sql`, which a
    # database restored from a dump or created by hand may never have run.
    # Grant what it needs when it is there and say nothing when it is not — a
    # migration that fails on a missing role would make the role mandatory for
    # everyone, including the unit suite's throwaway databases.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alppy_app') THEN
                EXECUTE 'GRANT EXECUTE ON FUNCTION alppy_job_school(uuid) TO alppy_app';
                EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE '
                        'ON ALL TABLES IN SCHEMA public TO alppy_app';
                EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO alppy_app';
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS alppy_job_school(uuid)")
    for table in ("school", *LINKED_TABLES, *SCOPED_TABLES):
        op.execute(f'DROP POLICY IF EXISTS {POLICY} ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
