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
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

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


def _purge_access_log() -> int:
    """Delete access-log rows past ``ALPPY_ACCESS_LOG_RETENTION_DAYS``.

    The read audit trail's one other writer (`services/access_log.py`). Meant
    for the same cron as ``purge-prompt-logs`` — a retention window nothing
    enforces is not a window, and this table grows with every profile a teacher
    opens.

    Unlike the prompt log this defaults to keeping rather than deleting: 0 or
    less means forever, and the shipped default is a year.
    """
    from alppy.services.access_log import purge_expired

    db = admin_session()
    try:
        deleted = purge_expired(db)
        log.info("access_log.purge.done", deleted=deleted)
    except Exception:
        db.rollback()
        log.exception("access_log.purge.failed")
        raise
    finally:
        db.close()
    return 0


#: Whether a reaped job of this kind is safe to run again, decided per kind
#: rather than uniformly (audit 03, B9). This is a statement about *cost and
#: idempotence*, not about likelihood of success:
#:
#: * ``PROCESS_SCAN`` and ``GRADE_OPEN_ANSWERS`` rewrite what they already
#:   wrote — detections are replaced per page, a verdict is written onto the
#:   detection it belongs to — so running one twice costs time and nothing else.
#: * ``PROPOSE_ADAPTIVE`` is the opposite and is why a blanket retry would be a
#:   mistake: a second run writes a **second set of unapproved exercises** for
#:   the same class and bills the school again for them. The teacher then has
#:   two proposals to approve and no way to tell which is which.
#: * ``GENERATE_FEEDBACK`` writes one note per pupil and bills per pupil; same
#:   argument.
#: * ``INGEST_SOURCE`` re-embeds a whole textbook.
#:
#: Nothing consumes this yet — the reaper only *records* the answer on the row —
#: and that is deliberate. Requeuing is a separate change with a separate
#: failure mode, and this constant is what any such change has to read.
RETRYABLE_JOB_KINDS: frozenset[str] = frozenset({"process_scan", "grade_open_answers"})


def _reap_jobs(*, dry_run: bool = False) -> int:
    """Fail the jobs that stopped reporting, so nothing waits on them forever.

    ``_run_job`` catches every exception and records ``FAILED`` itself, so arq's
    own retry never fires and a job that dies *without* reaching that handler —
    the worker killed, the container evicted, the 600 s timeout cancelling the
    task while its ``asyncio.to_thread`` thread runs on — leaves a ``RUNNING``
    row that nothing will ever finish.

    That is not merely untidy. ``grading_in_progress`` reads exactly those rows
    to answer "is a grader still coming for this pile?", so one dead job used to
    refuse a confirmation indefinitely, with no route to clear it short of
    editing the database. Confirmation no longer waits on a stale row by itself;
    this is what stops the row lingering, and what puts a real
    ``FAILURE_CODES`` value on it so the teacher's job list stops showing work
    in progress that ended hours ago.

    Idempotent, and safe to run on a schedule beside ``purge-prompt-logs``.
    """
    from alppy.models import Job
    from alppy.models.enums import JobStatus
    from alppy.services.job_failure import TIMEOUT
    from alppy.services.open_answer_grading import is_job_stale

    db = admin_session()
    try:
        running = db.execute(
            select(Job).where(Job.status == JobStatus.RUNNING)
        ).scalars()
        stale = [job for job in running if is_job_stale(job)]
        for job in stale:
            log.info(
                "job.reap",
                job_id=str(job.id),
                kind=str(job.kind),
                last_seen=str(job.updated_at),
                retryable=str(job.kind) in RETRYABLE_JOB_KINDS,
                dry_run=dry_run,
            )
            if dry_run:
                continue
            job.status = JobStatus.FAILED
            # A code from the closed set, never prose: `Job.error` crosses to a
            # browser (D86, services/job_failure.py). "Stopped reporting for
            # longer than the ceiling" is a timeout however it actually died.
            job.error = TIMEOUT
            job.finished_at = datetime.now(UTC)
        if not dry_run:
            db.commit()
        log.info("job.reap.done", reaped=len(stale), dry_run=dry_run)
    except Exception:
        db.rollback()
        log.exception("job.reap.failed")
        raise
    finally:
        db.close()
    return 0


def _purge_scan_images(*, older_than_days: int | None, dry_run: bool = False) -> int:
    """Delete the stored images of piles past the retention window.

    Nothing has ever deleted a scan image (audit 03, B14): every photograph of
    every child's handwriting this product has processed is still in object
    storage, and `Storage` had no `delete` at all until now.

    **Off unless somebody sets a number.** `ALPPY_SCAN_IMAGE_RETENTION_DAYS`
    defaults to 0, meaning keep forever, and this command refuses rather than
    guessing — a window a developer invented would quietly destroy the evidence
    behind a mark in the week before a parent contests it.

    **Confirmed piles first, and crops before pages.** The order is the point:
    a crop is a picture of one child's handwriting, so it is the most personal
    thing here and the least needed afterwards. Everything a grade rests on —
    the verdict, the transcription, the mark — lives on `Detection` and is
    untouched; what is lost is the ability to look at the paper again. A pile
    still in review keeps its images whatever the window says, because a
    teacher who cannot see the page cannot finish reviewing it.
    """
    from alppy.models import Detection, Scan, ScanPage
    from alppy.models.enums import ScanStatus
    from alppy.storage import get_storage

    settings = get_settings()
    days = older_than_days if older_than_days is not None else settings.scan_image_retention_days
    if days <= 0:
        log.warning(
            "scan_images.purge.disabled",
            detail=(
                "no retention window is configured; set "
                "ALPPY_SCAN_IMAGE_RETENTION_DAYS or pass --older-than-days. "
                "Nothing was deleted."
            ),
        )
        return 0

    cutoff = datetime.now(UTC) - timedelta(days=days)
    storage = get_storage()
    db = admin_session()
    deleted = 0
    try:
        scans = list(
            db.execute(
                select(Scan)
                .where(Scan.status == ScanStatus.CONFIRMED)
                .where(Scan.created_at < cutoff)
            ).scalars()
        )
        for scan in scans:
            pages = list(
                db.execute(select(ScanPage).where(ScanPage.scan_id == scan.id)).scalars()
            )
            if not pages:
                continue
            crops = [
                key
                for key in db.execute(
                    select(Detection.crop_key).where(
                        Detection.scan_page_id.in_([p.id for p in pages]),
                        Detection.crop_key.is_not(None),
                    )
                ).scalars()
                if key
            ]
            # Crops first: most personal, least needed once a verdict is stored.
            for key in [*crops, *(p.image_key for p in pages if p.image_key)]:
                if dry_run:
                    deleted += 1
                    continue
                try:
                    deleted += 1 if storage.delete(key) else 0
                except Exception as exc:
                    log.warning("scan_images.purge.failed", key=key, error=str(exc))
        log.info(
            "scan_images.purge.done",
            piles=len(scans),
            objects=deleted,
            older_than_days=days,
            dry_run=dry_run,
        )
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
    subparsers.add_parser(
        "purge-access-log",
        help="Delete read-audit rows past ALPPY_ACCESS_LOG_RETENTION_DAYS.",
    )
    reap_parser = subparsers.add_parser(
        "reap-jobs",
        help="Fail RUNNING jobs that stopped reporting past ALPPY_JOB_STALE_AFTER_S.",
    )
    reap_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be reaped without writing anything.",
    )
    purge_scans = subparsers.add_parser(
        "purge-scan-images",
        help=(
            "Delete stored page images and crops of CONFIRMED piles past the "
            "retention window. Off unless a window is configured."
        ),
    )
    purge_scans.add_argument(
        "--older-than-days",
        type=int,
        default=None,
        help="Override ALPPY_SCAN_IMAGE_RETENTION_DAYS for this run.",
    )
    purge_scans.add_argument(
        "--dry-run",
        action="store_true",
        help="Count what would be deleted without deleting anything.",
    )

    args = parser.parse_args(argv)

    if args.command == "seed":
        return _seed(allow_staging=args.allow_staging)

    if args.command == "backfill-events":
        return _backfill_events()

    if args.command == "purge-prompt-logs":
        return _purge_prompt_logs()

    if args.command == "purge-access-log":
        return _purge_access_log()

    if args.command == "reap-jobs":
        return _reap_jobs(dry_run=args.dry_run)

    if args.command == "purge-scan-images":
        return _purge_scan_images(
            older_than_days=args.older_than_days, dry_run=args.dry_run
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
