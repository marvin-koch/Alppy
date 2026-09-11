"""`class_kind` labels join the convention every other enum follows.

0026 created the type with its Python enum's VALUES — `homeroom`, `course` —
where every enum since 0001 uses the member NAMES: `UPLOADED`, `SOLID`,
`LP21`. That is not cosmetic. SQLAlchemy sends the member name for an
`Enum(PyEnum)` column, so the first write to `Class.kind` would have been
`invalid input value for enum class_kind: "HOMEROOM"`.

Nothing had written it yet — 0026 shipped the column as a discriminator with
no writer — which is why this is a rename and not a repair. There is no data
to migrate, and `ALTER TYPE ... RENAME VALUE` keeps any there might be.

Revision ID: 0052
Revises: 0051
"""

from __future__ import annotations

from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

_RENAMES = (("homeroom", "HOMEROOM"), ("course", "COURSE"))


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for old, new in _RENAMES:
        op.execute(f"ALTER TYPE class_kind RENAME VALUE '{old}' TO '{new}'")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for old, new in _RENAMES:
        op.execute(f"ALTER TYPE class_kind RENAME VALUE '{new}' TO '{old}'")
