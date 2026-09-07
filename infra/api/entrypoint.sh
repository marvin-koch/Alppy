#!/bin/sh
# Entrypoint for the `api` service in docker-compose.yml.
#
# docker-compose already makes `api` wait for postgres/redis/minio to report
# *healthy* (depends_on: condition: service_healthy) before this script even
# starts, so no wait-loop is needed here — but a healthy Postgres can still
# reject the very first connection for a moment while it finishes recovery,
# so `alembic upgrade head` is retried a few times rather than failing the
# whole container on one bad connection attempt.
set -eu

cd /app

attempt=1
max_attempts=10
until alembic -c alembic.ini upgrade head; do
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "entrypoint: alembic upgrade head failed after ${max_attempts} attempts" >&2
    exit 1
  fi
  echo "entrypoint: alembic upgrade head failed (attempt ${attempt}/${max_attempts}), retrying in 2s..."
  attempt=$((attempt + 1))
  sleep 2
done

# `serve` (the api service) or `worker` (the worker service); docker-compose
# passes one as the container command. This script used to ignore its argument
# and exec uvicorn unconditionally, so the `worker` container ran a second copy
# of the API: jobs were enqueued to Redis and nothing ever consumed them.
ROLE="${1:-serve}"

case "$ROLE" in
  serve)
    # Best-effort: seeds the demo dataset the first time (idempotent), but a
    # still-unfinished seed feature or a transient failure must never keep the
    # API from serving traffic. `python -m alppy.cli seed` already exits 0 when
    # alppy.seed.run_seed does not exist yet.
    python -m alppy.cli seed || echo "entrypoint: seed step failed, continuing to serve" >&2

    # Reconstruct the agenda from timestamps that predate the event log.
    # Without this the demo seed's three weeks of history are invisible on
    # /timeline: the log only records what happens after it exists, so a
    # database that plainly has a past would open on the empty state and read
    # as a broken feature rather than an empty one.
    #
    # Idempotent, which is what makes it safe here rather than a one-off: it
    # keys on (kind, subject) and adds nothing on a second run, so it costs one
    # query per start once the history is in. Best-effort for the same reason
    # as the seed — bookkeeping must never stop the API serving.
    python -m alppy.cli backfill-events \
      || echo "entrypoint: event backfill failed, continuing to serve" >&2

    exec uvicorn alppy.main:app --host 0.0.0.0 --port 8000
    ;;
  worker)
    # The API owns migrations and the seed; the worker only consumes the queue.
    exec python -m alppy.worker.main
    ;;
  *)
    echo "entrypoint: unknown role '$ROLE' (expected 'serve' or 'worker')" >&2
    exit 2
    ;;
esac
