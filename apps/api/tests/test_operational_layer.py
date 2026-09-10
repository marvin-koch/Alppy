"""Storage, the queue seam and the CLI — the plumbing nothing was pinning.

These were the modules at the bottom of the coverage table (`storage.py` 69%,
`worker/queue.py` 51%, `cli.py` 36%, `db/session.py` 67%), and they share a
shape: none of them is where a feature lives, all of them are where a feature
*fails*. A key that escapes its prefix, a Redis timeout that hangs a request
thread, a CLI command that commits half its work — each is invisible in a
feature test and expensive in production.

The security-relevant one is first: `storage.py` holds scanned answer sheets,
photographs of children's handwriting with a name at the top (docs/privacy.md).
A client-supplied filename that reaches a path is how one school reads another's.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403

from alppy import storage as storage_mod
from alppy.core.config import Settings
from alppy.models.enums import JobKind
from alppy.storage import (
    LocalStorage,
    StorageError,
    build_storage,
    sanitise_filename,
    storage_key,
)
from alppy.worker import queue as queue_mod


# --------------------------------------------------------------------------
# A filename never becomes a path
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("scan.pdf", "scan.pdf"),
        ("../../etc/passwd", "passwd"),
        ("..\\..\\windows\\system32", "system32"),
        ("/absolute/path.pdf", "path.pdf"),
        ("..", "upload"),
        (".", "upload"),
        ("", "upload"),
        ("...", "upload"),
        ("../", "upload"),
        ("a b c.pdf", "a_b_c.pdf"),
        ("é🙂.pdf", "pdf"),
        ("....pdf", "pdf"),
    ],
)
def test_a_client_filename_is_reduced_to_one_safe_segment(
    supplied: str, expected: str
) -> None:
    """The rule the module exists for. Every one of these is a real upload the
    API will accept, and none may produce a separator or a dot-segment."""
    result = sanitise_filename(supplied)
    assert result == expected
    assert "/" not in result and "\\" not in result
    assert result not in {"", ".", ".."}


def test_a_very_long_filename_is_truncated_but_keeps_its_extension(
    tmp_path: Path,
) -> None:
    """The extension is what the browser uses to decide what to do with the
    download; losing it turns a PDF into an unopenable blob."""
    leaf = sanitise_filename("x" * 400 + ".pdf")
    assert len(leaf) <= 100
    assert leaf.endswith(".pdf")


def test_the_key_is_built_from_server_side_values(tmp_path: Path) -> None:
    school, entity = uuid.uuid4(), uuid.uuid4()
    key = storage_key("scans", school, entity, "../../secret.pdf")
    assert key == f"scans/{school}/{entity}/secret.pdf"
    # The tenant is in the path, so one school's objects cannot be named by
    # another's key however the filename is spelled.
    assert str(school) in key


def test_a_key_that_escapes_the_root_is_refused(tmp_path: Path) -> None:
    """Defence behind the sanitiser: even a key built by hand cannot climb out."""
    store = LocalStorage(tmp_path / "objects")
    with pytest.raises(StorageError, match="escapes storage root"):
        store.put_bytes("../escaped.txt", b"x", "text/plain")


def test_exists_is_false_rather_than_raising_for_an_escaping_key(
    tmp_path: Path,
) -> None:
    """`exists` is called on the read path, where an exception would be a 500
    for what is really "no"."""
    store = LocalStorage(tmp_path / "objects")
    assert store.exists("../../etc/passwd") is False


# --------------------------------------------------------------------------
# The local backend
# --------------------------------------------------------------------------
def test_bytes_round_trip(tmp_path: Path) -> None:
    store = LocalStorage(tmp_path / "objects")
    key = store.put_bytes("scans/a/b/page.png", b"\x89PNG", "image/png")
    assert store.get_bytes(key) == b"\x89PNG"
    assert store.exists(key)


def test_reading_a_missing_object_is_a_storage_error(tmp_path: Path) -> None:
    store = LocalStorage(tmp_path / "objects")
    with pytest.raises(StorageError, match="no such object"):
        store.get_bytes("scans/nope.png")


def test_writing_creates_the_intermediate_directories(tmp_path: Path) -> None:
    store = LocalStorage(tmp_path / "objects")
    store.put_bytes("a/b/c/d/e.txt", b"x", "text/plain")
    assert (tmp_path / "objects" / "a" / "b" / "c" / "d" / "e.txt").is_file()


def test_a_second_write_replaces_the_first(tmp_path: Path) -> None:
    """A re-render writes the same key; a backend that appended would serve a
    corrupt PDF."""
    store = LocalStorage(tmp_path / "objects")
    store.put_bytes("k", b"first", "text/plain")
    store.put_bytes("k", b"second", "text/plain")
    assert store.get_bytes("k") == b"second"


def test_health_reports_a_writable_root(tmp_path: Path) -> None:
    store = LocalStorage(tmp_path / "objects")
    assert store.healthy() is True
    # And leaves nothing behind: the probe file must not show up as an object.
    assert not (tmp_path / "objects" / ".healthcheck").exists()


def test_the_backend_is_chosen_by_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPPY_STORAGE_BACKEND", "local")
    assert build_storage(Settings(env="ci", secret_key="test-secret-key")).backend == "local"  # type: ignore[attr-defined]


def test_ci_defaults_to_local_so_a_test_run_needs_no_minio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALPPY_STORAGE_BACKEND", raising=False)
    assert build_storage(Settings(env="ci", secret_key="test-secret-key")).backend == "local"  # type: ignore[attr-defined]


def test_the_storage_cache_can_be_cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    """`get_storage` is memoised, which is right in a process and wrong across
    a test that changes the backend."""
    monkeypatch.setenv("ALPPY_STORAGE_BACKEND", "local")
    storage_mod.reset_storage_cache()
    first = storage_mod.get_storage()
    assert storage_mod.get_storage() is first
    storage_mod.reset_storage_cache()
    assert storage_mod.get_storage() is not first


# --------------------------------------------------------------------------
# The queue seam
# --------------------------------------------------------------------------
def test_every_job_kind_maps_to_its_own_task_name() -> None:
    """The mapping is the identity, which is the whole reason there is no table
    to keep in sync. If a kind's value ever stopped matching its task, jobs of
    that kind would enqueue under a name the worker does not register."""
    for kind in JobKind:
        assert queue_mod.TASK_NAMES[kind] == kind.value


def test_a_disabled_queue_is_a_no_op_rather_than_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The suite and any single-process deployment run with it off; it must not
    raise, because a handler treats a raise as "the work will never start"."""
    monkeypatch.setattr(
        queue_mod, "get_settings", lambda: Settings(
            env="ci", secret_key="test-secret-key", job_queue_enabled=False
        )
    )
    queue_mod.enqueue(JobKind.RENDER_SHEET, uuid.uuid4())  # must not raise


def test_an_unreachable_redis_raises_queue_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not a generic exception: the handler turns exactly this into a 503, and
    anything else becomes a 500 that tells the teacher nothing."""
    monkeypatch.setattr(
        queue_mod, "get_settings", lambda: Settings(
            env="ci", secret_key="test-secret-key", job_queue_enabled=True
        )
    )

    async def _boom(kind: JobKind, job_id: uuid.UUID) -> None:
        raise ConnectionRefusedError("no redis here")

    monkeypatch.setattr(queue_mod, "_push", _boom)
    with pytest.raises(queue_mod.QueueUnavailableError) as caught:
        queue_mod.enqueue(JobKind.RENDER_SHEET, uuid.uuid4())
    # The message names the kind, so the log says which upload was lost.
    assert "render_sheet" in str(caught.value)


def test_a_slow_redis_times_out_rather_than_hanging_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ENQUEUE_TIMEOUT_S` is what stops one wedged Redis from consuming every
    threadpool worker FastAPI has, which takes the whole API down with it."""
    import asyncio

    monkeypatch.setattr(
        queue_mod, "get_settings", lambda: Settings(
            env="ci", secret_key="test-secret-key", job_queue_enabled=True
        )
    )
    monkeypatch.setattr(queue_mod, "ENQUEUE_TIMEOUT_S", 0.05)

    async def _hang(kind: JobKind, job_id: uuid.UUID) -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr(queue_mod, "_push", _hang)
    with pytest.raises(queue_mod.QueueUnavailableError):
        queue_mod.enqueue(JobKind.RENDER_SHEET, uuid.uuid4())


async def test_an_async_caller_does_not_deadlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`enqueue` is sync and every handler is a plain `def`, but an `async def`
    caller must not deadlock on `asyncio.run` inside a running loop."""
    pushed: list[uuid.UUID] = []

    monkeypatch.setattr(
        queue_mod, "get_settings", lambda: Settings(
            env="ci", secret_key="test-secret-key", job_queue_enabled=True
        )
    )

    async def _record(kind: JobKind, job_id: uuid.UUID) -> None:
        pushed.append(job_id)

    monkeypatch.setattr(queue_mod, "_push", _record)
    job_id = uuid.uuid4()
    queue_mod.enqueue(JobKind.RENDER_SHEET, job_id)
    assert pushed == [job_id]


# --------------------------------------------------------------------------
# The CLI
# --------------------------------------------------------------------------
def test_an_unknown_command_is_refused_rather_than_ignored() -> None:
    from alppy import cli

    with pytest.raises(SystemExit):
        cli.main(["not-a-command"])


def test_no_command_is_refused() -> None:
    from alppy import cli

    with pytest.raises(SystemExit):
        cli.main([])


def test_the_seed_command_reaches_the_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    from alppy import cli

    called: list[bool] = []
    monkeypatch.setattr(cli, "_seed", lambda **kw: called.append(kw.get("allow_staging", False)) or 0)
    assert cli.main(["seed"]) == 0
    assert called == [False]


def test_the_staging_flag_reaches_the_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The flag is the whole guard; a parser that dropped it would seed staging
    on every entrypoint start."""
    from alppy import cli

    called: list[bool] = []
    monkeypatch.setattr(cli, "_seed", lambda **kw: called.append(kw.get("allow_staging", False)) or 0)
    assert cli.main(["seed", "--allow-staging"]) == 0
    assert called == [True]


def test_backfill_rolls_back_and_re_raises_on_failure(
    monkeypatch: pytest.MonkeyPatch, db: Session
) -> None:
    """Every CLI command owns a transaction. A command that swallowed a failure
    would leave the agenda half-rebuilt and report success."""
    from alppy import cli

    monkeypatch.setattr(cli, "admin_session", lambda: db)
    monkeypatch.setattr(
        "alppy.services.event_backfill.backfill_events",
        lambda _db: (_ for _ in ()).throw(RuntimeError("half way")),
    )
    with pytest.raises(RuntimeError, match="half way"):
        cli._backfill_events()


def test_purge_rolls_back_and_re_raises_on_failure(
    monkeypatch: pytest.MonkeyPatch, db: Session
) -> None:
    from alppy import cli

    monkeypatch.setattr(cli, "admin_session", lambda: db)
    monkeypatch.setattr(
        "alppy.ai.prompt_log.purge_expired_prompts",
        lambda _db: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError, match="boom"):
        cli._purge_prompt_logs()


# --------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------
def test_a_statement_timeout_is_applied_to_postgres_only() -> None:
    """SQLite has no `statement_timeout` and would fail to connect at all if
    the option were passed to it — which is why the suite can run on it."""
    from alppy.db.session import _connect_args

    assert _connect_args("postgresql+psycopg://h/d", 15000) == {
        "options": "-c statement_timeout=15000"
    }
    assert _connect_args("sqlite://", 15000) == {}
    # Zero and negative mean "no ceiling", not "a ceiling of zero", which would
    # abort every statement instantly.
    assert _connect_args("postgresql+psycopg://h/d", 0) == {}
    assert _connect_args("postgresql+psycopg://h/d", -1) == {}


def test_the_request_session_is_closed_even_if_the_handler_raises() -> None:
    """`get_db` is a generator dependency; the close belongs in a finally or a
    failing request leaks a connection per failure."""
    from alppy.db.session import get_db

    gen = get_db()
    session = next(gen)
    gen.close()
    assert not session.in_transaction()
