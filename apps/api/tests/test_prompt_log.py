"""The prompt log: what was sent, kept apart from the audit trail that proves
a call happened.

Two tables, two lifetimes, two purposes, and the whole design lives in the gap
between them. ``model_call`` is content-free by construction and safe to keep;
``prompt_log`` holds the text and is off, capped and swept. Every test here
guards one edge of that separation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant

from alppy.ai import audit
from alppy.ai.base import ChatRequest, ChatResponse
from alppy.ai.client import AiClient, load_prompt
from alppy.ai.prompt_log import purge_expired_prompts
from alppy.ai.scrub import PiiLeakError
from alppy.core.config import Settings
from alppy.models import ModelCall, PromptLog

ROSTER = ["Lea", "Roth", "Noah", "Berger", "Mia", "Keller"]


class _Chat:
    name = "fake"
    grounded = True

    def __init__(self, text: str = '{"exercises": []}') -> None:
        self._text = text

    def complete(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(text=self._text, input_tokens=10, output_tokens=5, model="fake-1")


def _client(
    monkeypatch: pytest.MonkeyPatch, *, enabled: bool, max_chars: int = 20_000, text: str = "{}"
) -> AiClient:
    settings = Settings(
        _env_file=None,
        env="ci",
        ai_prompt_log_enabled=enabled,
        ai_prompt_log_max_chars=max_chars,
    )
    monkeypatch.setattr("alppy.ai.client.get_settings", lambda: settings)
    monkeypatch.setattr("alppy.ai.prompt_log.get_settings", lambda: settings)
    monkeypatch.setattr("alppy.ai.client.build_chat_provider", lambda: _Chat(text))
    return AiClient()


def _generate(client: AiClient, *, student_ref: str = "7B_15", names: list[str] | None = None):
    return client.complete(
        prompt=load_prompt("generate_exercises"),
        purpose="adaptive_generate",
        values={
            "language": "fr",
            "competency_labels": "Fractions",
            "difficulty": 3,
            "count": 2,
            "max_options": 4,
            "style_examples": "Calcule 3 x 4.",
            "student_ref": student_ref,
        },
        student_names=names,
    )


def test_nothing_is_logged_until_a_school_turns_it_on(
    db: Session, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off by default. An existing deployment gains an empty table, not a new
    data flow it did not ask for."""
    client = _client(monkeypatch, enabled=False)
    _generate(client)
    audit.flush(db, school_id=tenant.school.id, ai=client)

    assert client.transcripts == []
    assert db.scalars(select(PromptLog)).all() == []
    # The audit row is written either way: it is not the thing being switched.
    assert len(db.scalars(select(ModelCall)).all()) == 1


def test_the_prompt_and_the_answer_are_both_kept_when_it_is_on(
    db: Session, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(monkeypatch, enabled=True, text='{"exercises": [{"a": 1}]}')
    _generate(client)
    audit.flush(db, school_id=tenant.school.id, ai=client, request_id="run-1")

    row = db.scalars(select(PromptLog)).one()
    assert "Fractions" in (row.user_text or "")
    assert row.system_text
    assert row.response_text == '{"exercises": [{"a": 1}]}'
    assert (row.provider, row.purpose, row.ok) == ("fake", "adaptive_generate", True)
    assert (row.prompt_name, row.prompt_version) == ("generate_exercises", "v1")
    assert row.request_id == "run-1"


def test_the_content_free_audit_row_is_written_whether_or_not_the_log_is_on(
    db: Session, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ModelCall` is the audit trail and must not become conditional on a
    debugging switch — nor gain content when that switch is on (I-ai-06)."""
    client = _client(monkeypatch, enabled=True)
    _generate(client)
    audit.flush(db, school_id=tenant.school.id, ai=client)

    call = db.scalars(select(ModelCall)).one()
    assert call.prompt_sha256
    assert not hasattr(call, "user_text")
    assert not hasattr(call, "response_text")


def test_a_prompt_blocked_by_the_gate_is_never_written_to_the_prompt_log(
    db: Session, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The commonest failure at this seam is the PII gate, and the string that
    fired it is by definition the one carrying a roster name. Writing it down
    would make the debugging aid the leak the gate exists to prevent."""
    client = _client(monkeypatch, enabled=True)
    with pytest.raises(PiiLeakError):
        _generate(client, student_ref="Noah Berger", names=ROSTER)
    audit.flush(db, school_id=tenant.school.id, ai=client)

    row = db.scalars(select(PromptLog)).one()
    assert row.ok is False
    assert row.error == "PiiLeakError"
    assert (row.system_text, row.user_text, row.response_text) == (None, None, None)
    # Still traceable: the hash identifies the exact call without holding it.
    assert row.prompt_sha256


def test_the_refusal_is_still_recorded_so_the_gate_is_falsifiable(
    db: Session, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A silent gate is an unfalsifiable one (I-ai-07). Content is dropped; the
    fact of the block is not."""
    client = _client(monkeypatch, enabled=True)
    with pytest.raises(PiiLeakError):
        _generate(client, student_ref="Lea Roth", names=ROSTER)
    audit.flush(db, school_id=tenant.school.id, ai=client)

    assert db.scalars(select(ModelCall)).one().ok is False
    assert db.scalars(select(PromptLog)).one().ok is False


def test_a_prompt_too_long_to_keep_is_marked_as_cut_not_silently_shortened(
    db: Session, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An `extract_exercises` prompt carries a whole textbook chunk. A silently
    shortened one reads as the thing that was sent, which is worse than none."""
    client = _client(monkeypatch, enabled=True, max_chars=40)
    _generate(client)
    audit.flush(db, school_id=tenant.school.id, ai=client)

    row = db.scalars(select(PromptLog)).one()
    assert "[truncated at 40 characters]" in (row.user_text or "")


def test_a_prompt_log_failure_never_fails_the_call_that_produced_it(
    db: Session, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same rule as the audit writer (I-ai-08): losing a debugging row must not
    lose the class of children it was written about."""
    client = _client(monkeypatch, enabled=True)
    _generate(client)
    monkeypatch.setattr(
        "alppy.ai.prompt_log.PromptLog",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("column vanished")),
    )
    assert audit.flush(db, school_id=tenant.school.id, ai=client) == 1


def test_an_expired_row_is_swept_and_a_fresh_one_is_left_alone(
    db: Session, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A retention window nothing enforces is no window. Passing the PII gate is
    not the same as holding no student data: a UID plus a roster re-identifies."""
    settings = Settings(_env_file=None, env="ci", ai_prompt_log_retention_days=30)
    monkeypatch.setattr("alppy.ai.prompt_log.get_settings", lambda: settings)
    now = datetime(2026, 9, 9, tzinfo=UTC)

    for age_days, marker in ((90, "old"), (2, "fresh")):
        db.add(
            PromptLog(
                id=uuid.uuid4(),
                school_id=tenant.school.id,
                provider="fake",
                model="fake-1",
                purpose=marker,
                prompt_sha256="x" * 64,
                ok=True,
                created_at=now - timedelta(days=age_days),
                updated_at=now - timedelta(days=age_days),
            )
        )
    db.flush()

    assert purge_expired_prompts(db, now=now) == 1
    assert [r.purpose for r in db.scalars(select(PromptLog)).all()] == ["fresh"]


def test_a_row_belongs_to_the_school_whose_call_it_was(
    db: Session, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the tenant column the sweep cannot run per school, and the
    cascade that docs/privacy.md §4 promises on deletion would miss it."""
    client = _client(monkeypatch, enabled=True)
    _generate(client)
    audit.flush(db, school_id=tenant.school.id, ai=client)

    assert db.scalars(select(PromptLog)).one().school_id == tenant.school.id


def test_flushing_twice_does_not_write_the_same_call_twice(
    db: Session, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Some callers flush after every call, some once at the end of a job, and
    the ingest pipeline does both on different paths. The drain watermark is
    what makes those the same thing."""
    client = _client(monkeypatch, enabled=True)
    _generate(client)
    audit.flush(db, school_id=tenant.school.id, ai=client)
    audit.flush(db, school_id=tenant.school.id, ai=client)

    assert len(db.scalars(select(PromptLog)).all()) == 1
    assert len(db.scalars(select(ModelCall)).all()) == 1


def test_a_second_call_after_a_flush_is_still_written(
    db: Session, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The watermark must not swallow later work — a class batch shares one
    client across every student in it."""
    client = _client(monkeypatch, enabled=True)
    _generate(client)
    audit.flush(db, school_id=tenant.school.id, ai=client)
    _generate(client, student_ref="7B_16")
    audit.flush(db, school_id=tenant.school.id, ai=client)

    assert len(db.scalars(select(PromptLog)).all()) == 2
    assert len(db.scalars(select(ModelCall)).all()) == 2
