#!/bin/bash

echo "[OpenAlgo] Starting up..."

mkdir -p db logs
chmod -R 777 db logs 2>/dev/null || echo "⚠️  Skipping chmod (volume may be mounted)"

# Run with gunicorn using threading worker to avoid eventlet conflicts
cd /app
exec /app/.venv/bin/gunicorn --worker-class gthread --workers 1 --threads 4 --bind 0.0.0.0:5000 app:app
