FROM python:3.12-slim

# System deps (libpq-dev for PostgreSQL, libmagic1 for file type detection)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
ENV POETRY_VERSION=1.8.4 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN curl -sSL https://install.python-poetry.org | python3 - \
    && ln -s /opt/poetry/bin/poetry /usr/local/bin/poetry

WORKDIR /app

# Install dependencies (cached layer)
COPY pyproject.toml poetry.lock* ./
RUN poetry install --only main --no-root \
    && rm -rf /root/.cache

# Copy project
COPY . .

# Create directories
RUN mkdir -p /app/media/documents /app/chroma_data /app/logs /app/staticfiles

# Collect static files
RUN SECRET_KEY=build-placeholder python manage.py collectstatic --noinput 2>/dev/null || true

RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
