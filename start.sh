#!/bin/bash

echo "[OpenAlgo] Starting up..."

mkdir -p db logs
chmod -R 777 db logs 2>/dev/null || echo "⚠️  Skipping chmod (volume may be mounted)"

# Run gunicorn using full path inside virtualenv
exec /app/.venv/bin/gunicorn --bind=0.0.0.0:5000 \
                              --worker-class=eventlet \
                              --workers=1 \
                              --log-level=info \
                              app:app
