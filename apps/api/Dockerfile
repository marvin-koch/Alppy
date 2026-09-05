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

# --- dependencies (cached until pyproject changes) -------------------------
COPY apps/api/pyproject.toml /app/pyproject.toml
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -e . 2>/dev/null || pip install --no-cache-dir \
        "fastapi>=0.115.0" "uvicorn[standard]>=0.32.0" "sqlalchemy>=2.0.36" \
        "alembic>=1.14.0" "psycopg[binary]>=3.2.3" "pgvector>=0.3.6" \
        "pydantic>=2.10.0" "pydantic-settings>=2.6.0" "python-multipart>=0.0.18" \
        "argon2-cffi>=23.1.0" "itsdangerous>=2.2.0" "arq>=0.26.1" "redis>=5.2.0" \
        "boto3>=1.35.0" "httpx>=0.28.0" "anthropic>=0.40.0" "pypdf>=5.1.0" \
        "pdfplumber>=0.11.4" "numpy>=2.1.0" "opencv-python-headless>=4.10.0" \
        "pillow>=11.0.0" "pymupdf>=1.24.0" "structlog>=24.4.0" "jinja2>=3.1.4" \
        "playwright>=1.49.0" "email-validator>=2.2.0"

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
