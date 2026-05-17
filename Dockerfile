# ── Stage 1: install dependencies ────────────────────────────────────────────
FROM python:3.12-slim AS builder
WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: production runtime ──────────────────────────────────────────────
FROM python:3.12-slim AS runtime
WORKDIR /app

# Non-root user for security
RUN useradd -m -u 1000 appuser

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY app/ ./app/
COPY templates/ ./templates/
RUN mkdir -p /app/static

# SQLite data directory – mount as named volume in production
RUN mkdir -p /app/data && chown appuser:appuser /app/data

USER appuser

# Build metadata: passed via --build-arg from CI, surfaced as ENV so the app
# can render them in the dev-only build chip (bottom-right of every page).
ARG BUILD_SHA=""
ARG BUILD_TIME=""
ENV BUILD_SHA=$BUILD_SHA \
    BUILD_TIME=$BUILD_TIME

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# Single worker: SQLite + AsyncIOScheduler require single-process operation.
# Scale horizontally by switching to PostgreSQL + distributed scheduler.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
