"""Small operational entry points that don't belong on the HTTP API.

    python -m alppy.cli seed

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


def main(argv: list[str] | None = None) -> int:
    configure_logging(debug=get_settings().debug)

    parser = argparse.ArgumentParser(prog="python -m alppy.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("seed", help="Load the demo dataset (idempotent).")

    args = parser.parse_args(argv)

    if args.command == "seed":
        return _seed()

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
