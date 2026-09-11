# Drain and restart workers

**Usable.**

## What you are protecting

The worker runs the scan pipeline, the sheet renderer, the ingest, the adaptive
generation and the open-answer grader. Everything expensive, and everything a
teacher is waiting on.

Two facts about arq decide this procedure:

* **A job in progress is killed with the process.** arq does not drain on
  SIGTERM the way a web server does. A `process_scan` cancelled halfway leaves a
  `RUNNING` row in Postgres with nobody behind it.
* **A `RUNNING` row blocks a confirmation.** `grading_in_progress` reads exactly
  those rows to answer "is a grader still coming for this pile?", so a killed
  job used to refuse a teacher's confirmation indefinitely.

What makes the restart safe rather than merely survivable: `reap-jobs` now runs
**every five minutes and at worker startup**, so a row orphaned by a restart is
cleared within minutes by the worker that replaces it — and marked `FAILED` with
a real code rather than left saying work is in progress that ended hours ago.

## Restarting

```bash
# What is in flight right now.
fly ssh console -a alppy -C "python -m alppy.cli reap-jobs --dry-run"

fly machine restart <worker-machine-id> -a alppy

# The replacement reaps at startup; this is just confirmation.
fly logs -a alppy | grep -E "worker.startup|cron.start|job.reap"
```

## Waiting for quiet instead

There is no drain command. To restart without killing anything, restart when
nothing is running:

```bash
fly ssh console -a alppy -C "python -m alppy.cli reap-jobs --dry-run"
```

It prints the stale ones. For *all* running jobs, ask the database:

```sql
select kind, count(*), min(updated_at)
from job where status = 'RUNNING' group by kind;
```

Empty means restart freely. A `PROCESS_SCAN` or `GRADE_OPEN_ANSWERS` is
re-runnable — they rewrite what they already wrote — so killing one costs time
and nothing else. **A `PROPOSE_ADAPTIVE` or `GENERATE_FEEDBACK` is not**: a
second run writes a second set of unapproved exercises for the same class and
bills the school again, leaving the teacher two proposals with no way to tell
which is which. `RETRYABLE_JOB_KINDS` in `cli.py` is the list, and it is a
statement about idempotence and cost, not about likelihood of success.

So: wait out an adaptive proposal. Do not wait out a scan.

## Scaling the worker

```bash
fly scale count worker=2 -a alppy
```

Each worker runs `ALPPY_WORKER_MAX_JOBS` (4) concurrently and holds a database
session per job for the job's whole life. Raise `ALPPY_DB_POOL_SIZE` with it, or
the worker blocks on its own pool while Postgres sits idle. And note that a scan
pipeline pins a core in OpenCV: past the container's CPU allocation, more
concurrency buys contention rather than throughput.

**The schedule runs on every worker.** With two workers, the nightly purges run
twice. All four are idempotent, so this is waste rather than damage — but it is
worth knowing before reading the logs and wondering.

## The worker is down and nobody noticed

The symptom is not an error. It is uploads that succeed and piles that never
finish, because the API enqueues to Redis perfectly happily with nothing
consuming.

```bash
fly logs -a alppy | grep worker.startup     # last start
fly status -a alppy                         # is the process group there at all
```
```sql
select status, count(*) from job group by status;   -- QUEUED piling up
```

There is no alert for this. It is the single best argument for the error
tracking that is wired and inert in `core/observability.py`.
