"""Small operational entry points that don't belong on the HTTP API.

    python -m alppy.cli seed
    python -m alppy.cli backfill-events

Seeds the demo dataset (see ``alppy.seed``) so a fresh ``docker compose up``
has a class, a subject and three weeks of history to look at instead of an
empty database — the definition of done in ``docs/plan.md`` M6 asks for
exactly that.

The seed package is owned by another workstream and may still be under
construction, so this command looks up its entry point by convention
(``alppy.seed.run_seed(db) -> None``, called once, expected to be
idempotent — safe to run again against an already-seeded database) rather
than importing it unconditionally at module load time. If that function
does not exist yet, the command logs a clear skip message and exits 0: a
container entrypoint that runs ``migrate && seed && serve`` must not fail
to start just because the seed feature has not landed.
"""

from __future__ import annotations

import argparse
import sys

from alppy.core.config import get_settings
from alppy.core.logging import configure_logging, get_logger
from alppy.db.session import SessionLocal

log = get_logger(__name__)


def _seed() -> int:
    """Run ``alppy.seed.run_seed(db)`` if it exists; skip cleanly otherwise."""
    try:
        from alppy.seed import run_seed
    except ImportError:
        log.warning(
            "seed.skipped",
            reason="alppy.seed.run_seed is not implemented yet",
        )
        return 0

    db = SessionLocal()
    try:
        log.info("seed.start")
        run_seed(db)
        db.commit()
        log.info("seed.done")
    except Exception:
        db.rollback()
        log.exception("seed.failed")
        raise
    finally:
        db.close()
    return 0


def _backfill_events() -> int:
    """Reconstruct the agenda for work that predates the event log.

    Idempotent: a second run adds nothing, so it is safe in an entrypoint that
    runs on every container start.
    """
    from alppy.services.event_backfill import backfill_events

    db = SessionLocal()
    try:
        log.info("backfill.start")
        result = backfill_events(db)
        db.commit()
        log.info("backfill.done", events=result.total)
    except Exception:
        db.rollback()
        log.exception("backfill.failed")
        raise
    finally:
        db.close()
    return 0


def _purge_prompt_logs() -> int:
    """Delete prompt-log rows past ``ALPPY_AI_PROMPT_LOG_RETENTION_DAYS``.

    The retention setting is a promise; this is what keeps it. Meant for a cron
    or the same entrypoint that runs the backfill — a window nothing enforces is
    no window, and this is the one table that holds what was actually sent.
    """
    from alppy.ai.prompt_log import purge_expired_prompts

    db = SessionLocal()
    try:
        deleted = purge_expired_prompts(db)
        db.commit()
        log.info("prompt_log.purge.done", deleted=deleted)
    except Exception:
        db.rollback()
        log.exception("prompt_log.purge.failed")
        raise
    finally:
        db.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging(debug=get_settings().debug)

    parser = argparse.ArgumentParser(prog="python -m alppy.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("seed", help="Load the demo dataset (idempotent).")
    subparsers.add_parser(
        "backfill-events",
        help="Reconstruct the agenda from existing timestamps (idempotent).",
    )
    subparsers.add_parser(
        "purge-prompt-logs",
        help="Delete prompt-log rows past the configured retention window.",
    )

    args = parser.parse_args(argv)

    if args.command == "seed":
        return _seed()

    if args.command == "backfill-events":
        return _backfill_events()

    if args.command == "purge-prompt-logs":
        return _purge_prompt_logs()

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
