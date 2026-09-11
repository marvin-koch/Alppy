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
from typing import Any

from sqlalchemy import select

from alppy.api import errors
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


def _purge_model_calls() -> int:
    """Delete `ModelCall` rows past ``ALPPY_MODEL_CALL_RETENTION_DAYS``.

    The content-free audit trail — "did any of our data go to provider X" — and
    the one table written on every single model call. It had no window at all,
    which is a decision nobody took rather than a decision to keep forever;
    three years is the shipped one, and 0 still means forever for a school that
    wants it.
    """
    from alppy.ai.audit import purge_expired_calls

    db = admin_session()
    try:
        deleted = purge_expired_calls(db)
        db.commit()
        log.info("model_call.purge.done", deleted=deleted)
    except Exception:
        db.rollback()
        log.exception("model_call.purge.failed")
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


# --------------------------------------------------------------------------
# Accounts (D12)
# --------------------------------------------------------------------------
# There was no way to create a teacher, reset a password or revoke access. The
# only account-minting path was `seed`, which creates the DEMO teacher with a
# password that is a constant in this repository — so onboarding an
# establishment, and unlocking a teacher before a lesson, both meant hand-written
# SQL. See `services/account_service.py` for why these are commands rather than
# endpoints (no e-mail transport exists, and membership IS the permission model).


def _accounts_session() -> Any:
    """The owner's session. These are cross-school reads and writes by nature —
    "which account is this" is the question the tenant boundary exists to refuse
    inside a request, which is also why none of this is an endpoint."""
    return admin_session()


def _print_teacher_credentials(
    email: str, password: str | None, *, school_name: str
) -> None:
    """Print a generated password ONCE, and say what it is and is not.

    Nothing stores it: `password_hash` is Argon2id. If this scrolls past, the
    answer is `set-password`, not a recovery — which is the property that makes
    the store safe and the moment inconvenient.
    """
    print(f"\n  account : {email}")
    print(f"  school  : {school_name}")
    if password is not None:
        print(f"  password: {password}")
        print(
            "\n  Shown once and stored only as an Argon2id hash — there is no way to\n"
            "  read it back. Hand it over in person or through a channel the school\n"
            "  already trusts, and ask them to change it at first sign-in\n"
            "  (Settings, or POST /api/v1/auth/password).\n"
        )
    else:
        print("  password: (the one you supplied)\n")


def _create_teacher(
    *, email: str, first_name: str, last_name: str, school: str, password: str | None
) -> int:
    from alppy.services.account_service import AccountError, create_teacher, find_school

    db = _accounts_session()
    try:
        resolved = find_school(db, name_or_id=school)
        created = create_teacher(
            db,
            email=email,
            first_name=first_name,
            last_name=last_name,
            school=resolved,
            password=password,
        )
        db.commit()
    except AccountError as exc:
        db.rollback()
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except Exception:
        db.rollback()
        log.exception("account.create.failed")
        raise
    finally:
        db.close()
    _print_teacher_credentials(
        email.lower(), created.generated_password, school_name=resolved.name
    )
    return 0


def _set_password(*, email: str, password: str | None) -> int:
    from alppy.services.account_service import AccountError, find_teacher, set_password

    db = _accounts_session()
    try:
        teacher = find_teacher(db, email=email)
        generated = set_password(db, teacher=teacher, password=password)
        db.commit()
    except AccountError as exc:
        db.rollback()
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except Exception:
        db.rollback()
        log.exception("account.set_password.failed")
        raise
    finally:
        db.close()
    print(f"\n  account : {email.lower()}")
    if generated is not None:
        print(f"  password: {generated}")
    print(
        "\n  NOTE: live sessions are NOT signed out. The cookie is signed with the\n"
        "  server key and carries no password, and there is no session store to\n"
        "  revoke against. If the old password is believed to be known by someone\n"
        "  else, rotate ALPPY_SECRET_KEY as well — docs/runbook/rotate-a-secret.md.\n"
    )
    return 0


def _grant_school(*, email: str, school: str) -> int:
    from alppy.services.account_service import AccountError, find_school, find_teacher, grant_school

    db = _accounts_session()
    try:
        teacher = find_teacher(db, email=email)
        resolved = find_school(db, name_or_id=school)
        grant_school(db, teacher=teacher, school=resolved)
        db.commit()
        print(f"{email.lower()} now works at {resolved.name}")
    except AccountError as exc:
        db.rollback()
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except Exception:
        db.rollback()
        log.exception("account.grant.failed")
        raise
    finally:
        db.close()
    return 0


def _revoke_school(*, email: str, school: str) -> int:
    from alppy.services.account_service import (
        AccountError,
        find_school,
        find_teacher,
        revoke_school,
    )

    db = _accounts_session()
    try:
        teacher = find_teacher(db, email=email)
        resolved = find_school(db, name_or_id=school)
        revoke_school(db, teacher=teacher, school=resolved)
        db.commit()
        print(
            f"{email.lower()} no longer works at {resolved.name} as of today.\n"
            "The membership row is kept — 'they were here from August to February'\n"
            "is what justifies every grade they recorded."
        )
    except AccountError as exc:
        db.rollback()
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except errors.ApiError as exc:
        # `leave_school` raises the API's conflict type for its two refusals:
        # a staffroom cannot be emptied, and a head teacher cannot be removed
        # from a class that still names them. Both read fine at a shell.
        db.rollback()
        print(f"refused: {exc.message}", file=sys.stderr)
        if exc.details:
            print(f"         {exc.details}", file=sys.stderr)
        return 2
    except Exception:
        db.rollback()
        log.exception("account.revoke.failed")
        raise
    finally:
        db.close()
    return 0


def _list_teachers(*, school: str | None) -> int:
    from alppy.services.account_service import AccountError, find_school, list_teachers

    db = _accounts_session()
    try:
        resolved = find_school(db, name_or_id=school) if school else None
        rows = list_teachers(db, school=resolved)
    except AccountError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()
    if not rows:
        print("no teachers")
        return 0
    width = max(len(r.email) for r in rows)
    for row in rows:
        schools = ", ".join(row.current_schools) or "— no current staffroom —"
        print(f"{row.email:<{width}}  {row.name:<28}  {schools}")
    return 0


def _list_schools() -> int:
    from alppy.models import School

    db = _accounts_session()
    try:
        schools = list(db.execute(select(School).order_by(School.name)).scalars())
    finally:
        db.close()
    if not schools:
        print("no schools")
        return 0
    for school in schools:
        canton = school.canton or "--"
        print(f"{school.id}  {canton}  {school.default_curriculum.value:<4}  {school.name}")
    return 0


def _health_signals(*, days: int) -> int:
    """Compute and log the override rate and the confidence distribution (D8).

    The two signals that would show grading quality degrading in the field, and
    both are already in Postgres — `Detection` keeps what the machine read
    beside what the teacher stored, and `machine_confidence` is on every row.
    Neither has ever been queried.

    Cross-school on purpose, so it runs as the owner: the question is *which*
    school is drifting, and a tenant-bound session cannot answer it. Nothing it
    emits identifies a pupil, a teacher or a page — every value is a count.
    """
    from alppy.services.health_signals import report

    db = admin_session()
    try:
        report(db, days=days)
    except Exception:
        log.exception("health_signals.failed")
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
    subparsers.add_parser(
        "purge-model-calls",
        help="Delete model-call audit rows past ALPPY_MODEL_CALL_RETENTION_DAYS.",
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
    # --- accounts (D12) ---
    create = subparsers.add_parser(
        "create-teacher",
        help="Create a teacher account and put it in a staffroom.",
        description=(
            "Creates the account AND the school membership, because a teacher "
            "without one signs in successfully and then finds an empty product. "
            "Omit --password and a strong one is generated and printed once."
        ),
    )
    create.add_argument("--email", required=True)
    create.add_argument("--first-name", required=True)
    create.add_argument("--last-name", required=True)
    create.add_argument(
        "--school", required=True, help="School id, or its exact name. `list-schools` shows both."
    )
    create.add_argument(
        "--password",
        default=None,
        help="Leave this out. A generated password is stronger and is never typed into a shell's history.",
    )

    setpw = subparsers.add_parser(
        "set-password",
        help="Reset a teacher's password (they are NOT signed out).",
    )
    setpw.add_argument("--email", required=True)
    setpw.add_argument("--password", default=None, help="Omit to generate one.")

    grant = subparsers.add_parser(
        "grant-school", help="Add an existing teacher to another staffroom."
    )
    grant.add_argument("--email", required=True)
    grant.add_argument("--school", required=True)

    revoke = subparsers.add_parser(
        "revoke-school",
        help="End a teacher's membership of a staffroom, as of today.",
        description=(
            "An UPDATE, never a DELETE: the row is kept, because 'they were here "
            "from August to February' is what justifies every grade they recorded. "
            "Refused for the last teacher in a school, and for a teacher who is "
            "still head of a class."
        ),
    )
    revoke.add_argument("--email", required=True)
    revoke.add_argument("--school", required=True)

    listed = subparsers.add_parser("list-teachers", help="Every teacher, or one staffroom's.")
    listed.add_argument("--school", default=None, help="School id or exact name.")

    subparsers.add_parser("list-schools", help="Every school, with its id and curriculum.")

    signals = subparsers.add_parser(
        "health-signals",
        help=(
            "Log the override rate, the confidence distribution and the "
            "registration failure rate, per school."
        ),
    )
    signals.add_argument(
        "--days",
        type=int,
        default=7,
        help="How far back to look. Default 7, matching the weekly schedule.",
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

    if args.command == "purge-model-calls":
        return _purge_model_calls()

    if args.command == "reap-jobs":
        return _reap_jobs(dry_run=args.dry_run)

    if args.command == "create-teacher":
        return _create_teacher(
            email=args.email,
            first_name=args.first_name,
            last_name=args.last_name,
            school=args.school,
            password=args.password,
        )

    if args.command == "set-password":
        return _set_password(email=args.email, password=args.password)

    if args.command == "grant-school":
        return _grant_school(email=args.email, school=args.school)

    if args.command == "revoke-school":
        return _revoke_school(email=args.email, school=args.school)

    if args.command == "list-teachers":
        return _list_teachers(school=args.school)

    if args.command == "list-schools":
        return _list_schools()

    if args.command == "health-signals":
        return _health_signals(days=args.days)

    if args.command == "purge-scan-images":
        return _purge_scan_images(
            older_than_days=args.older_than_days, dry_run=args.dry_run
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
