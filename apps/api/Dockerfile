# syntax=docker/dockerfile:1
#
# Alppy API + worker. Both services run this image; the entrypoint decides which.
#
# Layer order is deliberate: the Chromium download is the largest and least
# volatile step, so it sits above the application code and survives every
# rebuild that only touches Python source.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

# System libraries: OpenCV headless and PyMuPDF need these, and libpq is for
# psycopg. Chromium's own dependencies arrive with `playwright install --with-deps`.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libpq5 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- dependencies (cached until pyproject or the package root changes) ------
#
# `pyproject.toml` is the ONLY dependency list. There used to be a second one
# inlined here behind `pip install -e . 2>/dev/null || pip install <list>`, and
# it had drifted: it was missing `openai` (the default chat provider) and
# `pillow-heif` (the iPhone HEIC scan path), and `2>/dev/null` hid which of the
# two branches had actually run. An image that silently builds without the
# decoder for the format most scans arrive in is worse than a build that fails
# (D16). So: one install, no fallback, loud on failure.
#
# The package root is copied in beside the manifest because setuptools resolves
# `[tool.setuptools.packages.find]` at install time — with only `pyproject.toml`
# present it finds no package and the editable install has nothing to point at.
# `alppy/__init__.py` is three lines and changes about once a year, so the
# dependency layer still survives every rebuild that only touches source.
COPY apps/api/pyproject.toml /app/pyproject.toml
COPY apps/api/alppy/__init__.py /app/alppy/__init__.py
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -e .

# --- Chromium for server-side PDF rendering --------------------------------
# The teacher's print preview and the generated PDF must come from the same
# markup and the same print.css, which is why the PDF is rendered by a browser
# rather than by a separate PDF library that would drift from it.
RUN playwright install --with-deps chromium

# --- application ------------------------------------------------------------
COPY apps/api/ /app/
# The renderer inlines the design CSS at render time so the PDF cannot drift
# from the design system.
COPY packages/ui/src/design/ /app/design-css/

RUN useradd --create-home --uid 10001 alppy \
    && chown -R alppy:alppy /app /opt/playwright
USER alppy

EXPOSE 8000
CMD ["uvicorn", "alppy.main:app", "--host", "0.0.0.0", "--port", "8000"]
