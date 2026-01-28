# OpenAlgo Docker Build Guide

Complete guide to building and deploying OpenAlgo with numba/llvmlite/scipy support.

## Quick Start

### Option 1: Automated Build Script (Recommended)

**macOS/Linux:**
```bash
./docker-build.sh
```

**Windows:**
```powershell
docker-build.bat
```

The automated script will:
- ✅ Verify environment configuration
- ✅ Build Docker image with all dependencies
- ✅ Run comprehensive tests
- ✅ Start the container
- ✅ Verify numba/llvmlite/scipy work correctly

### Option 2: Manual Build with Docker Compose

```bash
# Stop existing containers
docker-compose down

# Build with no cache (ensures fresh build)
docker-compose build --no-cache

# Start the container
docker-compose up -d

# Verify it's working
docker-compose exec openalgo python -c "import numba; import llvmlite; import scipy; print('✓ Success')"
```

### Option 3: Manual Build with Docker CLI

```bash
# Build the image
docker build --no-cache -t openalgo:latest .

# Run the container
docker run -d \
  --name openalgo-web \
  --shm-size=2g \
  -p 5000:5000 \
  -p 8765:8765 \
  -v openalgo_db:/app/db \
  -v openalgo_log:/app/log \
  -v openalgo_strategies:/app/strategies \
  -v openalgo_keys:/app/keys \
  -v "$(pwd)/.env:/app/.env:ro" \
  --tmpfs /app/tmp:size=1g,mode=1777 \
  --restart unless-stopped \
  openalgo:latest
```

## Build Process Details

### What Gets Built

The Dockerfile uses **multi-stage builds** for optimization:

1. **Python Builder Stage** (`python:3.12-bullseye`)
   - Installs `uv` package manager
   - Creates virtual environment
   - Installs all Python dependencies from `pyproject.toml`
   - Installs Gunicorn with eventlet support

2. **Frontend Builder Stage** (`node:20-bullseye-slim`)
   - Installs npm dependencies
   - Builds React frontend (`npm run build`)
   - Outputs to `frontend/dist/`

3. **Production Stage** (`python:3.12-slim-bullseye`)
   - Minimal base image
   - **Installs runtime libraries for numba/scipy:**
     - `libopenblas0` - BLAS/LAPACK for linear algebra
     - `libgomp1` - OpenMP for parallel operations
     - `libgfortran5` - Fortran runtime for scipy
   - Copies virtual environment from builder stage
   - Copies built frontend from builder stage
   - **Configures numba/scipy support:**
     - Sets `TMPDIR=/app/tmp`
     - Sets `NUMBA_CACHE_DIR=/app/tmp/numba_cache`
     - Creates cache directories with proper permissions

### Build Arguments

None required - all configuration is in `.env` file.

### Build Time

- **First build**: 8-12 minutes (downloads all dependencies)
- **Subsequent builds**: 5-8 minutes (uses layer caching)
- **No-cache builds**: 8-12 minutes (recommended for deployment)

### Image Size

- **Base image** (`python:3.12-slim-bullseye`): ~145 MB
- **Python dependencies**: ~650 MB
- **Runtime libraries**: ~15 MB
- **Frontend dist**: ~5 MB
- **Total final image**: ~815 MB

## Configuration Requirements

### Before Building

1. **Create .env file:**
   ```bash
   cp .sample.env .env
   ```

2. **Configure broker credentials in .env:**
   ```bash
   # Example for Fyers
   BROKER_API_KEY = 'Y2DJQVBAU4-100'
   BROKER_API_SECRET = 'your_secret_here'
   REDIRECT_URL = 'http://127.0.0.1:5000/fyers/callback'
   ```

3. **Generate security keys:**
   ```bash
   # APP_KEY
   python -c "import secrets; print(secrets.token_hex(32))"

   # API_KEY_PEPPER
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

4. **Update .env with generated keys:**
   ```bash
   APP_KEY = 'generated_key_1'
   API_KEY_PEPPER = 'generated_key_2'
   ```

## Verification Steps

### Step 1: Check Container is Running

```bash
docker ps | grep openalgo
```

Expected output:
```
CONTAINER ID   IMAGE             COMMAND          CREATED          STATUS          PORTS                                            NAMES
abc123def456   openalgo:latest   "/app/start.sh"  10 seconds ago   Up 9 seconds    0.0.0.0:5000->5000/tcp, 0.0.0.0:8765->8765/tcp   openalgo-web
```

### Step 2: Check Application Health

```bash
curl -f http://127.0.0.1:5000/auth/check-setup
```

Expected output: HTTP 200 response

### Step 3: Test Python Dependencies

**Test imports:**
```bash
docker-compose exec openalgo python -c "import numba; import llvmlite; import scipy; print('✓ Imports successful')"
```

**Test numba JIT:**
```bash
docker-compose exec openalgo python -c "
from numba import jit
import numpy as np

@jit(nopython=True)
def calculate_ema(prices, period):
    alpha = 2.0 / (period + 1.0)
    ema = np.zeros_like(prices)
    ema[0] = prices[0]
    for i in range(1, len(prices)):
        ema[i] = alpha * prices[i] + (1 - alpha) * ema[i-1]
    return ema

prices = np.random.randn(100)
ema = calculate_ema(prices, 20)
print(f'✓ EMA calculated: {ema[-1]:.4f}')
"
```

**Test scipy:**
```bash
docker-compose exec openalgo python -c "
from scipy import stats
result = stats.norm.cdf(0)
print(f'✓ SciPy works: {result:.4f}')
"
```

### Step 4: Check Logs

```bash
# View all logs
docker-compose logs

# Follow logs (live tail)
docker-compose logs -f

# View last 50 lines
docker-compose logs --tail=50

# View only errors
docker-compose logs | grep -i error
```

### Step 5: Test WebSocket Server

```bash
# Check if WebSocket server is running
docker-compose exec openalgo ps aux | grep websocket_proxy
```

Expected output showing `python -m websocket_proxy.server`

## Troubleshooting

### Issue: Build fails with "libopenblas0 not found"

**Solution:** Clear Docker cache and rebuild:
```bash
docker system prune -a
docker-compose build --no-cache
```

### Issue: Container starts but app doesn't respond

**Solution 1:** Check logs for errors:
```bash
docker-compose logs --tail=100
```

**Solution 2:** Verify .env file is mounted:
```bash
docker-compose exec openalgo ls -la /app/.env
docker-compose exec openalgo head -5 /app/.env
```

**Solution 3:** Restart container:
```bash
docker-compose restart
```

### Issue: "failed to map segment from shared object" error

**Solution:** Verify docker-compose.yaml has shm_size and tmpfs:
```bash
# Check configuration
cat docker-compose.yaml | grep -A 5 "shm_size\|tmpfs"

# Should show:
#   shm_size: '2gb'
#   - type: tmpfs
#     target: /app/tmp
```

If missing, rebuild with the updated docker-compose.yaml.

### Issue: Permission denied errors

**Solution:** Check directory permissions inside container:
```bash
docker-compose exec openalgo ls -la /app/
docker-compose exec openalgo ls -la /app/tmp/

# Fix if needed (run as root)
docker-compose exec -u root openalgo chown -R appuser:appuser /app/tmp
docker-compose exec -u root openalgo chmod -R 755 /app/tmp
```

### Issue: Numba compilation is slow

**Solution:** Verify cache directory is writable:
```bash
docker-compose exec openalgo bash -c '
echo "Testing numba cache..."
python -c "
from numba import jit
import os
print(f\"Cache dir: {os.getenv(\"NUMBA_CACHE_DIR\")}\")
print(f\"Exists: {os.path.exists(os.getenv(\"NUMBA_CACHE_DIR\"))}\")
print(f\"Writable: {os.access(os.getenv(\"NUMBA_CACHE_DIR\"), os.W_OK)}\")
"
'
```

### Issue: Container runs out of memory

**Solution:** Increase shared memory in docker-compose.yaml:
```yaml
shm_size: '4gb'  # Increase from 2gb
```

Then rebuild and restart:
```bash
docker-compose down
docker-compose up -d
```

## Advanced Build Options

### Build for Specific Platform

```bash
# For ARM64 (Apple Silicon, ARM servers)
docker buildx build --platform linux/arm64 -t openalgo:arm64 .

# For AMD64 (Intel/AMD)
docker buildx build --platform linux/amd64 -t openalgo:amd64 .

# Multi-platform (requires buildx)
docker buildx build --platform linux/amd64,linux/arm64 -t openalgo:latest .
```

### Build with Custom Tag

```bash
docker-compose build --no-cache
docker tag openalgo:latest openalgo:v2.0.0
docker tag openalgo:latest myregistry.com/openalgo:latest
```

### Build and Push to Registry

```bash
# Build
docker-compose build --no-cache

# Tag for registry
docker tag openalgo:latest your-registry.com/openalgo:latest

# Push
docker push your-registry.com/openalgo:latest
```

### Development Build (with source code mounted)

For development, you can mount source code as volume:

```bash
docker run -d \
  --name openalgo-dev \
  --shm-size=2g \
  -p 5000:5000 \
  -p 8765:8765 \
  -v "$(pwd):/app" \
  -v openalgo_db:/app/db \
  --tmpfs /app/tmp:size=1g,mode=1777 \
  -e FLASK_DEBUG=1 \
  openalgo:latest
```

**Warning:** Don't use mounted source in production!

## Performance Optimization

### Enable BuildKit

```bash
# Set environment variable
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

# Build with BuildKit
docker-compose build --no-cache
```

Benefits:
- Faster builds (parallel stage execution)
- Better caching
- Smaller images

### Use Build Cache from CI/CD

The GitHub Actions workflow caches build layers:

```yaml
cache-from: type=gha
cache-to: type=gha,mode=max
```

This speeds up subsequent builds in CI/CD.

### Prune Build Cache

If builds are slow or disk space is low:

```bash
# Remove all build cache
docker builder prune -a

# Remove unused images
docker image prune -a

# Complete cleanup (WARNING: removes all unused Docker data)
docker system prune -a --volumes
```

## Environment-Specific Builds

### Local Development
```bash
# Use docker-compose.yaml
docker-compose up -d
```

### Production (Railway/Render)
Platforms auto-detect Dockerfile and build automatically.

**Railway:**
- Automatically builds from Dockerfile
- Uses `PORT` environment variable
- Mounts persistent volumes

**Render:**
- Automatically builds from Dockerfile
- Uses `PORT` environment variable
- Configure volumes in render.yaml

### Kubernetes
```bash
# Build
docker build -t openalgo:latest .

# Push to registry
docker tag openalgo:latest your-registry/openalgo:latest
docker push your-registry/openalgo:latest

# Deploy with kubectl
kubectl apply -f k8s/deployment.yaml
```

## Security Considerations

### Build-time Security

1. **Never commit .env to git:**
   ```bash
   # .gitignore includes:
   .env
   ```

2. **Use BuildKit secrets for CI/CD:**
   ```dockerfile
   RUN --mount=type=secret,id=env_file \
       cat /run/secrets/env_file > .env
   ```

3. **Scan image for vulnerabilities:**
   ```bash
   # Using Trivy (included in CI/CD)
   docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
     aquasec/trivy:latest image openalgo:latest
   ```

### Runtime Security

1. **Runs as non-root user:** Container runs as `appuser`
2. **Restricted permissions:** Keys directory has `chmod 700`
3. **Read-only .env:** Mounted with `:ro` flag
4. **No privilege escalation:** No `--privileged` flag

## CI/CD Integration

The repository includes GitHub Actions workflow (`.github/workflows/ci.yml`):

**On Push to Main:**
1. Runs linting and tests
2. Builds Docker image
3. Scans for vulnerabilities
4. Pushes to Docker Hub (if secrets configured)

**To Use CI/CD:**
1. Add Docker Hub credentials to GitHub Secrets:
   - `DOCKERHUB_USERNAME`
   - `DOCKERHUB_TOKEN`

2. Push to main branch:
   ```bash
   git add .
   git commit -m "feat: update docker build"
   git push origin main
   ```

3. Check GitHub Actions tab for build status

4. Pull the built image:
   ```bash
   docker pull marketcalls/openalgo:latest
   ```

## Resources

- **Docker Documentation:** https://docs.docker.com
- **Dockerfile Reference:** https://docs.docker.com/engine/reference/builder/
- **Docker Compose Reference:** https://docs.docker.com/compose/compose-file/
- **OpenAlgo Documentation:** https://docs.openalgo.in
- **Numba Documentation:** https://numba.readthedocs.io
- **SciPy Documentation:** https://scipy.org

## Support

If you encounter issues:

1. Check logs: `docker-compose logs -f`
2. Review this guide's Troubleshooting section
3. Check GitHub Issues: https://github.com/marketcalls/openalgo/issues
4. Join Discord: https://discord.com/invite/UPh7QPsNhP

## Quick Reference

```bash
# Build
docker-compose build --no-cache

# Start
docker-compose up -d

# Stop
docker-compose down

# Restart
docker-compose restart

# Logs
docker-compose logs -f

# Shell access
docker-compose exec openalgo bash

# Run Python script
docker-compose exec openalgo uv run python /app/strategies/scripts/your_script.py

# Test dependencies
docker-compose exec openalgo python -c "import numba; import scipy; print('OK')"

# Update image
docker-compose pull
docker-compose up -d

# Complete rebuild
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```
