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

# Best-effort: seeds the demo dataset the first time (idempotent), but a
# still-unfinished seed feature or a transient failure must never keep the
# API from serving traffic. `python -m alppy.cli seed` already exits 0 when
# alppy.seed.run_seed does not exist yet; `|| true` is the last line of
# defense if it starts raising for some other reason.
python -m alppy.cli seed || echo "entrypoint: seed step failed, continuing to serve" >&2

exec uvicorn alppy.main:app --host 0.0.0.0 --port 8000
