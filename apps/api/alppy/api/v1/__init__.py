"""Version 1 of the HTTP API.

One module per area, assembled here. The prefix lives on the aggregate router
so an eventual ``/api/v2`` is a new package rather than an edit of every file.
"""

from __future__ import annotations

from fastapi import APIRouter

from alppy.api.v1 import (
    adaptive,
    auth,
    classes,
    curriculum,
    health,
    jobs,
    mastery,
    scans,
    sheets,
    sources,
    timeline,
)

api_router = APIRouter(prefix="/api/v1")

for module in (
    health,
    auth,
    classes,
    curriculum,
    sources,
    sheets,
    scans,
    mastery,
    adaptive,
    timeline,
    jobs,
):
    api_router.include_router(module.router)

__all__ = ["api_router"]
