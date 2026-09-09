"""The prompt log: what was actually sent to a model, for debugging.

``model_call`` deliberately stores no content. That is not an oversight to be
corrected here — it is the claim ``docs/privacy.md`` §3 makes to a school's DPO,
that the audit trail proves *which* calls happened without holding what was in
them, and so is safe to keep for as long as the school wants it. Widening it
would make the audit log the leak it exists to detect.

So the content lives in its own table, with its own lifetime and its own switch:

* **``ai_prompt_log_enabled`` defaults to false.** Nothing is written until a
  school opts in. An existing deployment upgrading through this migration gains
  an empty table and no new data flow.
* **Rows are written only after the PII gate passed.** A prompt that fired
  ``PiiLeakError`` is by definition the one carrying a roster name; the client
  writes that refusal with no content at all.
* **Rows expire.** ``ai_prompt_log_retention_days`` and
  ``python -m alppy.cli purge-prompt-logs``. Passing the gate is not the same as
  holding no student data — a UID plus a class roster re-identifies, and a wrong
  answer is a fact about a child. A retention window nothing enforces is no
  window.

``model_call_id`` is nullable with ``SET NULL`` rather than ``CASCADE``: the two
tables have different lifetimes on purpose, and sweeping the content must not be
able to take audit rows with it — nor the reverse.

The three indexes are the point of putting this in Postgres rather than in flat
files. ``model_call`` has only its school index, which is why nothing has ever
queried it in practice.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_call_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sheet_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("purpose", sa.String(length=60), nullable=False),
        sa.Column("prompt_name", sa.String(length=80), nullable=True),
        sa.Column("prompt_version", sa.String(length=20), nullable=True),
        sa.Column("prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("system_text", sa.Text(), nullable=True),
        sa.Column("user_text", sa.Text(), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_prompt_log"),
        # The school cascade is what makes "delete a tenant" complete. The three
        # optional links do not cascade: content and audit have different
        # lifetimes, and sweeping one must not take the other with it.
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["school.id"],
            name="fk_prompt_log_school_id_school",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_call_id"],
            ["model_call.id"],
            name="fk_prompt_log_model_call_id_model_call",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["job.id"], name="fk_prompt_log_job_id_job", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["sheet_id"],
            ["sheet.id"],
            name="fk_prompt_log_sheet_id_sheet",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_prompt_log_school_id", "prompt_log", ["school_id"])
    op.create_index("ix_prompt_log_model_call_id", "prompt_log", ["model_call_id"])
    op.create_index("ix_prompt_log_job_id", "prompt_log", ["job_id"])
    op.create_index("ix_prompt_log_sheet_id", "prompt_log", ["sheet_id"])
    # The reasons this is a table and not a directory of files: sweep by age
    # within a tenant, read one purpose's recent calls, follow one run.
    op.create_index(
        "ix_prompt_log_school_created", "prompt_log", ["school_id", "created_at"]
    )
    op.create_index(
        "ix_prompt_log_purpose_created", "prompt_log", ["purpose", "created_at"]
    )
    op.create_index("ix_prompt_log_request", "prompt_log", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_prompt_log_request", table_name="prompt_log")
    op.drop_index("ix_prompt_log_purpose_created", table_name="prompt_log")
    op.drop_index("ix_prompt_log_school_created", table_name="prompt_log")
    op.drop_index("ix_prompt_log_sheet_id", table_name="prompt_log")
    op.drop_index("ix_prompt_log_job_id", table_name="prompt_log")
    op.drop_index("ix_prompt_log_model_call_id", table_name="prompt_log")
    op.drop_index("ix_prompt_log_school_id", table_name="prompt_log")
    op.drop_table("prompt_log")
