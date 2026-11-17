# Docker Documentation

Current Docker setup starts with [Docker Deployment](docker.md), [environment settings](docker_env_changes.md), and the [build guide](DOCKER_BUILD_GUIDE.md). Dated scripts-analysis and numba-fix reports below preserve their original implementation history.

---

## Table of Contents

### Getting Started

- **[docker.md](docker.md)** - Basic Docker deployment guide
- **[Optional gthread worker](../gthread/README.md#installing-with-gthread)** - Select gthread, configure the 45-second shutdown grace, verify it, and switch back to eventlet
- **[DOCKER_BUILD_GUIDE.md](DOCKER_BUILD_GUIDE.md)** - Complete build and deployment guide (12 KB)
  - Build process details
  - Configuration requirements
  - Verification steps
  - Platform-specific instructions
  - Troubleshooting common issues

### Configuration

- **[docker_env_changes.md](docker_env_changes.md)** - Environment variable changes and configuration
- Environment variables for Docker deployment
- Configuration differences between local and container

### Issues & Fixes

- **[DOCKER_NUMBA_FIX.md](DOCKER_NUMBA_FIX.md)** - numba/llvmlite/scipy troubleshooting (6.9 KB)
  - Fixes for `KeyError: 'LLVMPY_AddSymbol'`
  - Fixes for `OSError: failed to map segment from shared object`
  - Fixes for master contract CSV errors
  - Step-by-step resolution guide
  - Verification procedures

### Installation Scripts

- **[DOCKER_SCRIPTS_ANALYSIS.md](DOCKER_SCRIPTS_ANALYSIS.md)** - Analysis of installation scripts (7.9 KB)
  - Detailed analysis of docker-run.sh, docker-run.bat, install-docker.sh
  - Before/after comparisons
  - Impact assessment
  - Testing checklist

- **[UPDATES_SUMMARY.md](UPDATES_SUMMARY.md)** - Installation scripts update summary (12 KB)
  - Complete update summary
  - Side-by-side code comparisons
  - Migration guide for existing users
  - Troubleshooting section

- **[QUICK_REFERENCE.md](QUICK_REFERENCE.md)** - Quick reference guide (3.5 KB)
  - Quick testing commands
  - Common issues and solutions
  - Desktop and server update procedures

---

## Quick Start

### Desktop Installation (macOS/Linux)
```bash
curl -O https://raw.githubusercontent.com/marketcalls/openalgo/main/install/docker-run.sh
chmod +x docker-run.sh
./docker-run.sh
```

### Desktop Installation (Windows)
```powershell
curl.exe -O https://raw.githubusercontent.com/marketcalls/openalgo/main/install/docker-run.bat
docker-run.bat
```

### Server Installation (Ubuntu/Debian)
```bash
curl -O https://raw.githubusercontent.com/marketcalls/openalgo/main/install/install-docker.sh
chmod +x install-docker.sh
sudo ./install-docker.sh
```

---

## Common Issues

### numba/scipy Errors
If you see errors like:
- `KeyError: 'LLVMPY_AddSymbol'`
- `OSError: failed to map segment from shared object`
- `FileNotFoundError: tmp/NSE_CM.csv`

**Solution:** See [DOCKER_NUMBA_FIX.md](DOCKER_NUMBA_FIX.md)

### Build Issues
For build-related problems, see [DOCKER_BUILD_GUIDE.md](DOCKER_BUILD_GUIDE.md)

### Configuration Issues
For environment variable issues, see [docker_env_changes.md](docker_env_changes.md)

---

## Document Index

| Document | Size | Purpose | Audience |
|----------|------|---------|----------|
| [docker.md](docker.md) | 3.8 KB | Basic Docker guide | Beginners |
| [DOCKER_BUILD_GUIDE.md](DOCKER_BUILD_GUIDE.md) | 12 KB | Complete build guide | Developers |
| [DOCKER_NUMBA_FIX.md](DOCKER_NUMBA_FIX.md) | 6.9 KB | Troubleshooting numba/scipy | Users with errors |
| [docker_env_changes.md](docker_env_changes.md) | 1.6 KB | Environment config | DevOps |
| [DOCKER_SCRIPTS_ANALYSIS.md](DOCKER_SCRIPTS_ANALYSIS.md) | 7.9 KB | Script analysis | Maintainers |
| [UPDATES_SUMMARY.md](UPDATES_SUMMARY.md) | 12 KB | Update guide | Existing users |
| [QUICK_REFERENCE.md](QUICK_REFERENCE.md) | 3.5 KB | Quick commands | All users |

**Total:** 7 documents, ~48 KB

---

## Docker Configuration

### Current Setup

OpenAlgo uses a **multi-stage build** with the following configuration:

```yaml
services:
  openalgo:
    image: openalgo:latest
    container_name: openalgo-web

    ports:
      - "5000:5000"   # Web UI
      - "8765:8765"   # WebSocket

    volumes:
      - openalgo_db:/app/db
      - openalgo_log:/app/log
      - openalgo_strategies:/app/strategies
      - openalgo_keys:/app/keys
      - openalgo_tmp:/app/tmp
      - ./.env:/app/.env  # Existing file, writable by container UID 1000

    shm_size: ${SHM_SIZE:-512m}  # Repository Compose default; size for available RAM

    restart: unless-stopped
```

### Runtime Dependencies

The Docker image includes:
- **Python 3.12** (required)
- **libopenblas0** - BLAS/LAPACK for linear algebra
- **libgomp1** - OpenMP for parallel operations
- **libgfortran5** - Fortran runtime for scipy
- **Chromium + fonts-liberation** - Kaleido/Telegram chart rendering
- **numba, llvmlite, scipy** - Versions resolved from the current Python dependency files

---

## Testing

### Verify Installation
```bash
# Check container status
docker ps --filter "name=openalgo"

# Test numba/scipy
docker exec openalgo-web python -c "import numba, scipy; print('OK')"

# View logs
docker-compose logs -f
```

### Verify Shared Memory
```bash
docker inspect openalgo-web --format='{{.HostConfig.ShmSize}}'
# Repository Compose default: 536870912 (512 MiB); helpers size it from RAM
```

### Verify Volumes
```bash
docker inspect openalgo-web --format='{{range .Mounts}}{{.Destination}} {{end}}'
# Should include: /app/tmp /app/keys
```

---

## Recent Updates

### Historical: 2026-01-28 - numba/scipy Support
- Added runtime dependencies (libopenblas0, libgomp1, libgfortran5)
- Configured TMPDIR and NUMBA_CACHE_DIR environment variables
- Added 2GB shared memory allocation
- Fixed /app/tmp permissions using named volume
- Updated all installation scripts

This records the changes made at that time; current troubleshooting still depends on the error, image and resource limits.

---

## Support

If you encounter issues:

1. **Check Documentation**
   - Start with [QUICK_REFERENCE.md](QUICK_REFERENCE.md)
   - For errors, see [DOCKER_NUMBA_FIX.md](DOCKER_NUMBA_FIX.md)
   - For builds, see [DOCKER_BUILD_GUIDE.md](DOCKER_BUILD_GUIDE.md)

2. **Check Logs**
   ```bash
   docker-compose logs -f
   ```

3. **Verify Configuration**
   ```bash
   docker inspect openalgo
   ```

4. **Community Support**
   - Discord: https://discord.com/invite/UPh7QPsNhP
   - GitHub Issues: https://github.com/marketcalls/openalgo/issues

---

## Related Documentation

- [Installation Scripts](/install/) - Desktop and server installation scripts
- [Main Documentation](https://docs.openalgo.in) - Official documentation site
- [CLAUDE.md](/CLAUDE.md) - Development guide

---

**Current configuration sources:** `Dockerfile`, `docker-compose.yaml`, `start.sh`
**Docker Image:** marketcalls/openalgo:latest
**Python Version:** 3.12+
