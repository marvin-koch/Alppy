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

Every command here opens an ``admin_session`` rather than the API's own, and
that is not a convenience. All three sweep **every school** — the seed creates
one, the backfill reconstructs the agenda across all of them, the purge
enforces one retention window over the whole ``PromptLog`` table — and since
D84 the runtime role sees only the school named by ``app.current_school_id``.
No value of that GUC means "all of them", so these run as the schema owner,
which carries ``BYPASSRLS``. It is the deliberate hole in D84 and it is why it
lives here, in three commands an operator runs, rather than anywhere a request
can reach.
"""

from __future__ import annotations

import argparse
import sys

from alppy.core.config import get_settings
from alppy.core.logging import configure_logging, get_logger
from alppy.db.session import admin_session

log = get_logger(__name__)


#: Environments the demo seed may run in **unattended**. It is a *demo* dataset:
#: two teacher accounts whose passwords are constants in `alppy.seed.demo`, a
#: school, and 18 invented students. Idempotency makes re-running it safe; it
#: does not make running it *here* safe, and those are different questions.
SEEDABLE_ENVS = frozenset({"local", "ci"})

#: Environments that may be seeded, but only when a human asks for it by name.
#: Staging needs a dataset — an empty staging deployment is the condition under
#: which somebody loads a real roster "just to test with", which is the outcome
#: this whole arrangement exists to prevent. What it must not have is an
#: entrypoint that reseeds it on every container start: `infra/api/entrypoint.sh`
#: calls `seed` with no arguments, so staging is refused there and reachable only
#: as `python -m alppy.cli seed --allow-staging`.
EXPLICITLY_SEEDABLE_ENVS = frozenset({"staging"})


def _seed(*, allow_staging: bool = False) -> int:
    """Run ``alppy.seed.run_seed(db)`` if it exists; skip cleanly otherwise.

    Refuses outright in staging and production. `infra/api/entrypoint.sh` calls
    this on every start of the `serve` role, which is exactly right for
    `docker compose up` and exactly wrong pointed at a real database: it would
    plant two logins whose passwords are published in this repository, next to a
    roster of real children. The guard lives here rather than in the entrypoint
    because the entrypoint is one caller of several — a console, a migration
    runbook, a cron — and a rule enforced at one door is not enforced.

    A refusal is a skip, not a failure: the entrypoint treats a non-zero seed as
    survivable and serves anyway, so exiting 0 keeps the log honest about what
    happened instead of adding a scary line to a correct deployment.
    """
    settings = get_settings()
    env = settings.env
    permitted = env in SEEDABLE_ENVS or (allow_staging and env in EXPLICITLY_SEEDABLE_ENVS)
    if not permitted:
        log.warning(
            "seed.refused",
            env=env,
            reason=(
                "the demo seed creates accounts with published passwords"
                if env not in EXPLICITLY_SEEDABLE_ENVS
                else "seeding this environment requires --allow-staging"
            ),
        )
        return 0

    if env in EXPLICITLY_SEEDABLE_ENVS and not settings.seed_teacher_password:
        # The flag says a human meant it; this says they brought a password.
        # Falling back to the published constant here would put two known
        # logins in front of whatever staging can reach — the demo seed's own
        # refusal to run outside development, walked around by the flag that
        # was supposed to make it safe.
        log.error(
            "seed.refused",
            env=env,
            reason="ALPPY_SEED_TEACHER_PASSWORD is unset; refusing to seed with "
            "the passwords published in this repository",
        )
        return 1

    staging = env in EXPLICITLY_SEEDABLE_ENVS
    try:
        from alppy.seed import run_seed, run_staging_seed
    except ImportError:
        log.warning(
            "seed.skipped",
            reason="alppy.seed.run_seed is not implemented yet",
        )
        return 0

    db = admin_session()
    try:
        log.info("seed.start", env=env, dataset="staging" if staging else "demo")
        if staging:
            # A different dataset, not the same one with a different password:
            # six classes of twenty across both curricula, from a closed corpus
            # of invented names (`alppy.seed.staging`). The demo's eighteen
            # never exercise a list that scrolls or a batch that takes a minute.
            assert settings.seed_teacher_password is not None  # checked above
            run_staging_seed(db, password=settings.seed_teacher_password)
        else:
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

    db = admin_session()
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

    db = admin_session()
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
    seed_parser = subparsers.add_parser("seed", help="Load the demo dataset (idempotent).")
    seed_parser.add_argument(
        "--allow-staging",
        action="store_true",
        help=(
            "Permit seeding a staging deployment. Requires "
            "ALPPY_SEED_TEACHER_PASSWORD. Never set by the container entrypoint."
        ),
    )
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
        return _seed(allow_staging=args.allow_staging)

    if args.command == "backfill-events":
        return _backfill_events()

    if args.command == "purge-prompt-logs":
        return _purge_prompt_logs()

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
