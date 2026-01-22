# 11 - Docker Configuration

## Overview

OpenAlgo provides Docker support for containerized deployment with multi-stage builds, IST timezone configuration, and proper security isolation. The Docker setup uses Python 3.12, Gunicorn with Eventlet workers, and runs as a non-root user.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Docker Architecture                                    │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                        Multi-Stage Build                                     │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Stage 1: Builder (python:3.12-bullseye)                              │  │
│  │                                                                        │  │
│  │  1. Install build dependencies (curl, build-essential)                │  │
│  │  2. Copy pyproject.toml                                               │  │
│  │  3. Create virtual environment with uv                                │  │
│  │  4. Install dependencies: uv sync                                     │  │
│  │  5. Add gunicorn + eventlet==0.35.2                                   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│                                    ▼                                         │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  Stage 2: Production (python:3.12-slim-bullseye)                      │  │
│  │                                                                        │  │
│  │  1. Set timezone to IST (Asia/Kolkata)                                │  │
│  │  2. Create non-root user (appuser)                                    │  │
│  │  3. Copy venv from builder                                            │  │
│  │  4. Copy application source                                           │  │
│  │  5. Create directories (log, db, strategies, keys)                    │  │
│  │  6. Set permissions                                                   │  │
│  │  7. Run as appuser                                                    │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Container Runtime                                     │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  start.sh                                                           │    │
│  │                                                                     │    │
│  │  1. Start WebSocket proxy (background)                             │    │
│  │  2. Start Gunicorn with Eventlet worker                            │    │
│  │     - Single worker (-w 1) for WebSocket compatibility             │    │
│  │     - Bind to 0.0.0.0:5000                                         │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  Exposed Ports:                                                             │
│  - 5000: Flask application                                                  │
│  - 8765: WebSocket proxy (internal)                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Dockerfile

```dockerfile
# ------------------------------ Builder Stage ------------------------------ #
FROM python:3.12-bullseye AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl build-essential && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir uv && \
    uv venv .venv && \
    uv pip install --upgrade pip && \
    uv sync && \
    uv pip install gunicorn eventlet==0.35.2 && \
    rm -rf /root/.cache

# ------------------------------ Production Stage --------------------------- #
FROM python:3.12-slim-bullseye AS production

# Set timezone to IST
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && \
    ln -fs /usr/share/zoneinfo/Asia/Kolkata /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home appuser
WORKDIR /app

# Copy venv and source
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser . .

# Create directories with proper permissions
RUN mkdir -p /app/log /app/log/strategies /app/db /app/strategies \
             /app/strategies/scripts /app/keys && \
    chown -R appuser:appuser /app/log /app/db /app/strategies /app/keys && \
    chmod 700 /app/keys

# Environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Kolkata \
    APP_MODE=standalone

USER appuser
EXPOSE 5000
CMD ["/app/start.sh"]
```

## Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  openalgo:
    build: .
    ports:
      - "5000:5000"
      - "8765:8765"
    volumes:
      - ./db:/app/db              # Persist databases
      - ./log:/app/log            # Persist logs
      - ./strategies:/app/strategies  # Persist strategies
      - ./.env:/app/.env:ro       # Environment config
    environment:
      - FLASK_HOST_IP=0.0.0.0
      - FLASK_PORT=5000
      - WEBSOCKET_HOST=0.0.0.0
      - WEBSOCKET_PORT=8765
    restart: unless-stopped
```

## Directory Structure

```
Container /app/
├── .venv/                 # Python virtual environment
├── db/                    # SQLite databases (mounted volume)
│   ├── openalgo.db
│   ├── logs.db
│   ├── latency.db
│   ├── sandbox.db
│   └── historify.duckdb
├── log/                   # Log files (mounted volume)
│   └── strategies/
├── strategies/            # User strategies (mounted volume)
│   └── scripts/
├── keys/                  # Encryption keys (700 permissions)
├── .env                   # Environment configuration
├── start.sh               # Entrypoint script
└── app.py                 # Main application
```

## Start Script

```bash
#!/bin/bash
# start.sh

# Start WebSocket proxy in background
python websocket_proxy/server.py &

# Start Gunicorn with Eventlet worker
# -w 1: Single worker required for WebSocket compatibility
gunicorn --worker-class eventlet \
         -w 1 \
         --bind 0.0.0.0:5000 \
         --timeout 120 \
         --keep-alive 5 \
         app:app
```

## Build Commands

```bash
# Build image
docker build -t openalgo .

# Run container
docker run -d \
  --name openalgo \
  -p 5000:5000 \
  -p 8765:8765 \
  -v $(pwd)/db:/app/db \
  -v $(pwd)/log:/app/log \
  -v $(pwd)/.env:/app/.env:ro \
  openalgo

# View logs
docker logs -f openalgo

# Stop container
docker stop openalgo

# Remove container
docker rm openalgo
```

## Docker Compose Commands

```bash
# Start services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Rebuild and start
docker-compose up -d --build
```

## Environment Variables for Docker

```bash
# .env for Docker deployment
FLASK_HOST_IP=0.0.0.0           # Listen on all interfaces
FLASK_PORT=5000
FLASK_DEBUG=False
FLASK_ENV=production

WEBSOCKET_HOST=0.0.0.0
WEBSOCKET_PORT=8765
WEBSOCKET_URL=ws://localhost:8765

HOST_SERVER=http://your-domain.com  # External URL

DATABASE_URL=sqlite:///db/openalgo.db

# Security (generate unique values)
APP_KEY=your_32_byte_hex_key
API_KEY_PEPPER=your_32_byte_hex_pepper
```

## Security Considerations

| Aspect | Implementation |
|--------|----------------|
| Non-root user | Runs as `appuser` |
| Read-only .env | Mounted with `:ro` flag |
| Keys directory | 700 permissions |
| No build tools | Slim production image |
| Minimal packages | Only runtime dependencies |

## Volume Persistence

| Volume | Purpose | Required |
|--------|---------|----------|
| `/app/db` | SQLite databases | Yes |
| `/app/log` | Application logs | Recommended |
| `/app/strategies` | User strategies | Optional |
| `/app/.env` | Configuration | Yes |

## Key Files Reference

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build configuration |
| `docker-compose.yml` | Service orchestration |
| `start.sh` | Container entrypoint |
| `.dockerignore` | Build exclusions |
