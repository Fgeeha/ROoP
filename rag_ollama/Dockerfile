# =============================================================================
# Build stage — resolves dependencies into a self-contained virtualenv.
#
# Poetry and its own dependency tree (dulwich, requests, ...) stay in this
# stage: they are build tooling, and shipping them in the runtime image only
# widened its vulnerability surface without being used at run time.
# =============================================================================
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# virtualenvs.in-project puts the environment at /app/.venv, which is the only
# thing the runtime stage copies.  A virtualenv is not relocatable — the console
# scripts in bin/ hardcode their interpreter path — so the runtime keeps it at
# exactly the same /app/.venv.
ENV POETRY_VERSION=2.3.3 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN curl -sSL https://install.python-poetry.org | python3 -

WORKDIR /app
COPY pyproject.toml poetry.lock* ./
RUN /opt/poetry/bin/poetry install --only main --no-root \
    && rm -rf /root/.cache

# =============================================================================
# Runtime stage
# =============================================================================
FROM python:3.12-slim

# libmagic1 — file type detection by magic bytes
# libpq5   — PostgreSQL client library (runtime only, no headers needed)
# antiword — .doc extraction
# curl     — container healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    libpq5 \
    antiword \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Copy project. `.venv/` is in .dockerignore, so this cannot clobber the
# environment copied above.
COPY . .

# Create directories
RUN mkdir -p /app/media/documents /app/chroma_data /app/logs /app/staticfiles

# Collect static files
RUN SECRET_KEY=build-placeholder python manage.py collectstatic --noinput 2>/dev/null || true

RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
