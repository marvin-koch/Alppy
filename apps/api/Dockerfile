# syntax=docker/dockerfile:1
#
# Alppy API + worker. Both services run this image; the entrypoint decides which.
#
# Layer order is deliberate: the Chromium download is the largest and least
# volatile step, so it sits above the application code and survives every
# rebuild that only touches Python source.

# Pinned by DIGEST, not by tag (D18). `python:3.12-slim` is a moving target:
# two builds a week apart are two different base images, with a different
# glibc and a different set of system libraries, and nothing records which one
# produced the image that is running. That matters here more than it usually
# does — the scan detector is numerical code, and its degradation suite is
# calibrated against a specific OpenCV/NumPy pair. Dependabot's docker
# ecosystem proposes the bumps; this line is what makes each one a reviewed,
# dated commit rather than a silent change of floor.
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS base

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
COPY apps/api/requirements.lock /app/requirements.lock
COPY apps/api/alppy/__init__.py /app/alppy/__init__.py
# Two installs, and the split is the point (D18).
#
#   1. The LOCKED dependency set, with `--require-hashes`. Every version in
#      `requirements.lock` is pinned and every artifact is hashed, so the image
#      built today and the image built in March contain the same code — and a
#      registry that served a different file for a version we already have
#      fails the build instead of shipping. `pyproject.toml` is all `>=`
#      ranges, which is right for a library and wrong for a deployment: the
#      degradation suite that calibrates the scan detector is pinned to a
#      specific OpenCV/NumPy pair, and a minor bump arriving unannounced in a
#      rebuild is exactly the change it exists to catch.
#   2. The application itself, `--no-deps`, because step 1 already installed
#      them and a second resolution could only disagree with the first.
#
# `requirements.lock` is generated from `uv.lock`; see apps/api/README or
# `make lock`. CI fails if either has drifted from `pyproject.toml`.
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir --require-hashes -r requirements.lock \
    && pip install --no-cache-dir --no-deps -e .

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
