#!/bin/bash
set -e

echo "=== RAG Ollama - Starting ==="

# Ensure writable directories exist (volumes may be mounted as root)
for dir in /app/logs /app/media/documents /app/chroma_data /app/staticfiles; do
    mkdir -p "$dir" 2>/dev/null || true
    # Try to fix ownership if running as root (otherwise skip silently)
    chown -R "$(id -u):$(id -g)" "$dir" 2>/dev/null || true
done

# Run migrations
echo "Running migrations..."
python manage.py migrate --noinput

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput 2>/dev/null || true

# Create superuser if needed
if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
    echo "Creating superuser..."
    python manage.py createsuperuser --noinput 2>/dev/null || true
fi

echo "=== RAG Ollama - Ready ==="
echo "Starting Gunicorn on port 8000..."

# Start Gunicorn
exec gunicorn rag_project.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 300 \
    --access-logfile - \
    --error-logfile - \
    --log-level info
