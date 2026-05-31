#!/bin/bash
set -e

echo "=== ROoP - Starting ==="

# Ensure writable directories exist
for dir in /app/logs /app/media/documents /app/chroma_data /app/staticfiles; do
    mkdir -p "$dir" 2>/dev/null || true
    chown -R "$(id -u):$(id -g)" "$dir" 2>/dev/null || true
done

# Wait for PostgreSQL
if [ -n "$POSTGRES_HOST" ]; then
    echo "Waiting for PostgreSQL at ${POSTGRES_HOST}:${POSTGRES_PORT:-5432}..."
    for i in $(seq 1 30); do
        if python -c "
import socket, sys
try:
    s = socket.create_connection(('${POSTGRES_HOST}', ${POSTGRES_PORT:-5432}), timeout=2)
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
            echo "PostgreSQL is ready."
            break
        fi
        echo "  attempt $i/30..."
        sleep 2
    done
fi

# Run migrations
echo "Running migrations..."
python manage.py migrate --noinput

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput 2>/dev/null || true

# Create superuser if needed
if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
    if [ -z "$DJANGO_SUPERUSER_PASSWORD" ]; then
        echo "WARNING: DJANGO_SUPERUSER_PASSWORD is not set -- skipping superuser creation."
        echo "         Set it in .env and restart to create the admin account."
    else
        echo "Creating superuser..."
        python manage.py createsuperuser --noinput 2>/dev/null || true
    fi
fi

# Sync ChromaDB metadata
echo "Syncing ChromaDB metadata..."
python manage.py sync_chroma_metadata 2>/dev/null || true

echo "=== ROoP - Ready ==="
echo "Starting Gunicorn on port 8000..."

# Start Gunicorn
exec gunicorn rag_project.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 300 \
    --access-logfile - \
    --error-logfile - \
    --log-level info
