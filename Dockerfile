# ── Stage 1: install Python dependencies ─────────────────────────────────────
FROM python:3.12-slim AS builder
WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: compile Tailwind CSS ────────────────────────────────────────────
# Done at build time so the runtime container never depends on reaching
# cdn.tailwindcss.com - previously loaded live in the browser, which broke
# the whole layout (huge unstyled icons, no spacing) whenever the deployment
# network couldn't reach that CDN.
FROM node:20-slim AS css-builder
WORKDIR /css
COPY package.json package-lock.json .
RUN npm ci
COPY tailwind.config.js .
COPY templates/ ./templates/
COPY static/css/input.css ./static/css/input.css
RUN npx tailwindcss -i ./static/css/input.css -o ./static/css/app.css --minify

# ── Stage 3: production runtime ──────────────────────────────────────────────
FROM python:3.12-slim AS runtime
WORKDIR /app

# Non-root user for security
RUN useradd -m -u 1000 appuser

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY app/ ./app/
COPY templates/ ./templates/
COPY static/ ./static/
COPY --from=css-builder /css/static/css/app.css ./static/css/app.css

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
