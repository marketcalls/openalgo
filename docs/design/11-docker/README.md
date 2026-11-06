# 11 - Docker Configuration

## Overview

OpenAlgo provides Docker support for containerized deployment with **3-stage builds** (Python builder, Frontend builder, Production), IST timezone configuration, and proper security isolation. The Docker setup uses Python 3.12, Gunicorn with one eventlet worker by default or one optional gthread worker with 64 threads, and runs as a non-root user. It includes Railway/cloud deployment support with automatic `.env` generation.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Docker Architecture (3-Stage Build)                    │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                        Stage 1: Python Builder                               │
│                        (python:3.12-trixie)                                  │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  1. Install build dependencies (curl, build-essential)                │  │
│  │  2. Copy pyproject.toml                                               │  │
│  │  3. Create virtual environment with uv                                │  │
│  │  4. Install dependencies: uv sync                                     │  │
│  │  5. Add gunicorn>=25.0,<26 + eventlet==0.41.2                                   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Stage 2: Frontend Builder                             │
│                        (node:22-trixie-slim)                                 │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  1. Copy frontend/package*.json                                       │  │
│  │  2. npm ci                                                            │  │
│  │  3. Copy frontend source                                              │  │
│  │  4. npm run build (React production build)                            │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Stage 3: Production                                   │
│                        (python:3.12-slim-trixie)                             │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │  1. Set timezone to IST (Asia/Kolkata)                                │  │
│  │  2. Install runtime dependencies (curl, libopenblas0, libgomp1,       │  │
│  │     libgfortran5) for scipy/numba                                     │  │
│  │  3. Create non-root user (appuser)                                    │  │
│  │  4. Copy venv from python-builder                                     │  │
│  │  5. Copy application source                                           │  │
│  │  6. Copy frontend/dist from frontend-builder                          │  │
│  │  7. Create directories (log, db, strategies, keys, tmp, numba_cache)  │  │
│  │  8. Set permissions (keys: 700, others: 755)                          │  │
│  │  9. Run as appuser                                                    │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Container Runtime (start.sh)                          │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │  1. Railway/Cloud Detection & .env Generation                       │    │
│  │     - Detects HOST_SERVER environment variable                      │    │
│  │     - Auto-generates .env with all required variables               │    │
│  │     - Supports 40+ configuration options                            │    │
│  │  2. Directory Setup                                                 │    │
│  │  3. Database Migrations (if /app/upgrade/migrate_all.py exists)     │    │
│  │  4. WebSocket Proxy (background, PID tracked)                       │    │
│  │  5. Signal Handling (SIGTERM, SIGINT cleanup)                       │    │
│  │  6. Gunicorn: eventlet default / optional gthread                                          │    │
│  │     - Single worker (-w 1) for WebSocket compatibility              │    │
│  │     - Timeout: 300s, Graceful timeout: 30s                          │    │
│  │     - Worker temp dir: /tmp/gunicorn_workers                        │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  Application ports:                                                             │
│  - 5000: Flask application (or PORT env var for Railway)                    │
│  - 8765: WebSocket proxy                                                    │
│  - 5555: ZeroMQ message bus (loopback only, not published)                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Build And Compose Sources

The maintained build is [`Dockerfile`](../../../Dockerfile); [`docker-compose.yaml`](../../../docker-compose.yaml) is the runnable Compose source. Use those files instead of a copied Dockerfile or service definition from an older guide.

- Python and production stages use Python 3.12 on Debian trixie; the frontend builder uses Node 22.
- Gunicorn is pinned to `>=25.0,<26` while eventlet `0.41.2` remains the default/fallback.
- Production includes BLAS/OpenMP/Fortran libraries plus Chromium and fonts for Kaleido chart export.
- `appuser` has fixed UID/GID 1000, owns `/app` for atomic file replacement, and runs the application without root.
- The `.env` bind mount is read/write and must exist as a file. UID 1000 needs write access for placeholder rotation and server-setting saves.
- Named volumes persist `/app/db`, `/app/log`, `/app/strategies`, `/app/keys`, and `/app/tmp`.
- Repository Compose defaults shared memory to `${SHM_SIZE:-512m}`; install helpers size shared memory and numerical-library threads from available RAM.
- The Compose health check uses `/auth/check-setup`, not the HTML `/health` page.

The first-run helpers create `.env` with fresh installation secrets and no broker; keys are then added through Broker Configuration. Existing `.env` broker settings retain precedence. See [Docker Deployment](../../docker/docker.md) and [environment settings](../../docker/docker_env_changes.md).

### Named Volumes vs Bind Mounts

| Approach | Pros | Cons |
|----------|------|------|
| **Named Volumes** (recommended) | Better performance, managed by Docker | Data in Docker's volume directory |
| **Bind Mounts** (`./db:/app/db`) | Easy access to files | Permission issues possible |

## Directory Structure

```
Container /app/
├── .venv/                 # Python virtual environment
├── frontend/
│   └── dist/              # Built React frontend (from frontend-builder stage)
├── db/                    # SQLite databases (mounted volume)
│   ├── openalgo.db
│   ├── logs.db
│   ├── latency.db
│   ├── sandbox.db
│   └── historify.duckdb
├── log/                   # Log files (mounted volume)
│   └── strategies/
├── strategies/            # User strategies (mounted volume)
│   ├── scripts/
│   └── examples/
├── tmp/                   # Temporary files (internal volume)
│   ├── numba_cache/       # Numba JIT cache
│   └── matplotlib/        # Matplotlib config
├── keys/                  # Encryption keys (700 permissions)
├── .env                   # Environment configuration (666 for Railway)
├── start.sh               # Entrypoint script (246 lines)
├── upgrade/
│   └── migrate_all.py     # Database migrations (run on startup)
└── app.py                 # Main application
```

## Start Script And Worker Lifecycle

`start.sh` prepares directories, generates configuration for supported cloud environments, runs `upgrade/migrate_all.py`, and starts the market-data proxy separately. The normal production path uses one eventlet worker. When `.env` selects gthread, it uses `install/openalgo-gunicorn.sh` with one worker and 64 request threads, supervision for the proxy, and graceful shutdown handling.

Both modes keep the proxy outside the web worker. The proxy SUB socket binds the fixed loopback ZMQ endpoint; all broker and cache-invalidation PUB sockets connect. Port 5555 is internal and is not mapped to the host.

For gthread, configure at least 45 seconds of container stop grace to allow the 30-second request drain plus cleanup. The supplied desktop runners set this; Compose users must add `stop_grace_period: 45s`. See the [gthread guide](../../gthread/README.md#switch-on-docker) for selection, verification and rollback.

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
  --stop-timeout 45 \
  -v $(pwd)/.env:/app/.env \
  openalgo

# View logs
docker logs -f openalgo

# Stop container
docker stop --time 45 openalgo

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

## Resource Configuration for Python Strategies

Running Python strategies with numerical libraries (NumPy, SciPy, Numba) in Docker requires careful resource configuration to prevent `RLIMIT_NPROC` exhaustion errors.

### Thread Limiting Environment Variables

OpenBLAS, NumPy, and other numerical libraries spawn threads by default. In containers with limited process/thread limits, this causes crashes. The Dockerfile and docker-compose.yaml include these limits:

| Variable | Purpose | Default |
|----------|---------|---------|
| `OPENBLAS_NUM_THREADS` | OpenBLAS thread limit | 2 |
| `OMP_NUM_THREADS` | OpenMP thread limit | 2 |
| `MKL_NUM_THREADS` | Intel MKL thread limit | 2 |
| `NUMEXPR_NUM_THREADS` | NumExpr thread limit | 2 |
| `NUMBA_NUM_THREADS` | Numba JIT thread limit | 2 |

### Resource Scaling by Container RAM

| Container RAM | Thread Limit | Strategy Memory | SHM Size | Max Strategies |
|---------------|--------------|-----------------|----------|----------------|
| 2GB | 1 | 256MB | 256MB | 5 |
| 4GB | 2 | 512MB | 512MB | 5-8 |
| 8GB | 2-4 | 1024MB | 1GB | 10+ |
| 16GB+ | 4 | 1024MB | 2GB | 20+ |

### Configuration in docker-compose.yaml

```yaml
services:
  openalgo:
    environment:
      # Thread limits (adjust based on container RAM)
      - OPENBLAS_NUM_THREADS=${OPENBLAS_NUM_THREADS:-2}
      - OMP_NUM_THREADS=${OMP_NUM_THREADS:-2}
      - MKL_NUM_THREADS=${MKL_NUM_THREADS:-2}
      - NUMEXPR_NUM_THREADS=${NUMEXPR_NUM_THREADS:-2}
      - NUMBA_NUM_THREADS=${NUMBA_NUM_THREADS:-2}
      # Strategy memory limit (MB)
      - STRATEGY_MEMORY_LIMIT_MB=${STRATEGY_MEMORY_LIMIT_MB:-1024}
    # Shared memory for scipy/numba (25% of container RAM)
    shm_size: ${SHM_SIZE:-512m}
```

### Install Script Dynamic Calculation

The `install/install-docker.sh` script automatically calculates optimal values:

```bash
# Thread limits based on RAM
# <3GB: 1 thread | 3-6GB: 2 threads | 6GB+: min(4, cores)
if [ $TOTAL_RAM_MB -lt 3000 ]; then
    THREAD_LIMIT=1
elif [ $TOTAL_RAM_MB -lt 6000 ]; then
    THREAD_LIMIT=2
else
    THREAD_LIMIT=$((CPU_CORES < 4 ? CPU_CORES : 4))
fi
```

> **Reference**: See [GitHub Issue #822](https://github.com/marketcalls/openalgo/issues/822) for details on the RLIMIT_NPROC fix.

## Security Considerations

| Aspect | Implementation |
|--------|----------------|
| Non-root user | Runs as `appuser` |
| Private writable .env | Bind-mounted read/write for UID 1000; retain original installation secrets |
| Keys directory | 700 permissions |
| No build tools | Slim production image |
| Minimal packages | Only runtime dependencies |

## Volume Persistence

| Volume | Purpose | Required |
|--------|---------|----------|
| `/app/db` | SQLite databases and Historify DuckDB | Yes |
| `/app/log` | Application logs | Recommended |
| `/app/strategies` | User strategies | Optional |
| `/app/keys` | API keys/certificates used by integrations | Yes when used |
| `/app/tmp` | Scientific-library temporary/cache files | Writable storage required |
| `/app/.env` | Configuration and installation encryption secrets | Yes |

## Key Files Reference

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build configuration |
| `docker-compose.yaml` | Service orchestration |
| `start.sh` | Container entrypoint |
| `.dockerignore` | Build exclusions |
