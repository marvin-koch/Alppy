"""The arq (Redis-backed) background worker.

Everything slower than a request/response cycle — ingestion, PDF rendering,
scan processing, adaptive batch generation — runs here, never inside a
FastAPI handler. See ``docs/architecture.md`` §3 ("nothing blocks a
handler on a model call") and ``alppy.worker.tasks`` for the job lifecycle
every task shares.
"""

from __future__ import annotations
