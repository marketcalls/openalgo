# Docker Deployment

Use the repository's `Dockerfile`, `docker-compose.yaml`, and build helpers. They build Python 3.12 dependencies and the React frontend in separate stages, then run a non-root production container. The current Docker build installs dependencies with `uv sync` from `pyproject.toml`; the old Python 3.11 development-only recipe is superseded by these files.

## Start From A Source Checkout

Install Docker Engine or Docker Desktop with Docker Compose, then run from the OpenAlgo repository root:

```bash
./docker-build.sh
```

On Windows:

```powershell
docker-build.bat
```

The helpers create a missing `.env` for a fresh install with unique installation secrets, no broker selected, and the container listener settings. They preserve an existing `.env`. If the database volume already exists but `.env` is missing, restore the original `.env` before starting: its keys protect the saved data.

Open `http://localhost:5000`, complete app setup and sign in, then add your broker keys under **Select Broker → Configure**. Register the callback address shown by Broker Configuration in your broker's developer console. Existing installations that keep a broker in `.env` retain that configuration and its precedence.

## Manual Compose Operation

With a valid `.env` already prepared (see [Docker environment settings](docker_env_changes.md)):

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f openalgo
```

The service is `openalgo`; the default container name is `openalgo-web`. The repository Compose file maps web port 5000 and market-data WebSocket port 8765, and persists databases, logs, strategies, keys and temporary files in named volumes. Its `.env` bind mount is writable by container UID 1000 so startup key rotation and server settings can be saved. The host `.env` must exist as a file before Compose starts.

For updates, back up `.env` and the persistent volumes, update the source, then rebuild and recreate:

```bash
docker compose up -d --build
```

A restart alone keeps the existing image. `docker compose down` keeps named volumes; deleting volumes deletes their stored data.

## Worker Selection And Shutdown

The default is one Gunicorn eventlet worker. Optional gthread uses one worker with 64 request threads and requires a 45-second container stop grace; follow the [gthread Docker instructions](../gthread/README.md#switch-on-docker). Both modes run the market-data proxy separately through `start.sh`. Do not increase the Gunicorn worker count.

## Verify

```bash
curl -f http://127.0.0.1:5000/auth/check-setup
docker compose exec openalgo python -c "import numba, llvmlite, scipy; print('Imports successful')"
```

For resource sizing, build troubleshooting and persistent storage details, see [DOCKER_BUILD_GUIDE.md](DOCKER_BUILD_GUIDE.md) and the [Docker architecture](../design/11-docker/README.md).
