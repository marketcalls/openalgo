# Docker Installation Scripts - Compatibility Analysis

## Summary

All three Docker installation scripts need updates to support the numba/llvmlite/scipy fixes:

| Script | Status | Issues Found | Priority |
|--------|--------|--------------|----------|
| docker-run.sh | ❌ NEEDS UPDATE | Missing shm_size, tmp volume | HIGH |
| docker-run.bat | ❌ NEEDS UPDATE | Missing shm_size, tmp volume | HIGH |
| install-docker.sh | ❌ NEEDS UPDATE | docker-compose.yaml missing config | HIGH |

---

## Required Updates

### 1. docker-run.sh (macOS/Linux Desktop)

**Current docker run command (Lines 366-377):**
```bash
docker run -d \
    --name "$CONTAINER" \
    -p 5000:5000 \
    -p 8765:8765 \
    -v "$OPENALGO_DIR/db:/app/db" \
    -v "$OPENALGO_DIR/strategies:/app/strategies" \
    -v "$OPENALGO_DIR/log:/app/log" \
    -v "$OPENALGO_DIR/.env:/app/.env:ro" \
    --restart unless-stopped \
    "$IMAGE"
```

**Missing:**
- ❌ `--shm-size=2g` - Required for scipy memory operations
- ❌ Volume for `/app/tmp` - Required for numba cache
- ❌ Volume for `/app/keys` - Required for API keys/certificates

**Should be:**
```bash
docker run -d \
    --name "$CONTAINER" \
    --shm-size=2g \
    -p 5000:5000 \
    -p 8765:8765 \
    -v "$OPENALGO_DIR/db:/app/db" \
    -v "$OPENALGO_DIR/strategies:/app/strategies" \
    -v "$OPENALGO_DIR/log:/app/log" \
    -v "$OPENALGO_DIR/keys:/app/keys" \
    -v "$OPENALGO_DIR/tmp:/app/tmp" \
    -v "$OPENALGO_DIR/.env:/app/.env:ro" \
    --restart unless-stopped \
    "$IMAGE"
```

**Changes needed:**
1. Add `--shm-size=2g` after `--name "$CONTAINER"`
2. Add `-v "$OPENALGO_DIR/keys:/app/keys"` volume
3. Add `-v "$OPENALGO_DIR/tmp:/app/tmp"` volume
4. Update setup function to create `keys` and `tmp` directories

---

### 2. docker-run.bat (Windows Desktop)

**Current docker run command (Lines 318-327):**
```batch
docker run -d ^
    --name %CONTAINER% ^
    -p 5000:5000 ^
    -p 8765:8765 ^
    -v "%OPENALGO_DIR%\db:/app/db" ^
    -v "%OPENALGO_DIR%\strategies:/app/strategies" ^
    -v "%OPENALGO_DIR%\log:/app/log" ^
    -v "%OPENALGO_DIR%\.env:/app/.env:ro" ^
    --restart unless-stopped ^
    %IMAGE%
```

**Missing:**
- ❌ `--shm-size=2g` - Required for scipy memory operations
- ❌ Volume for `/app/tmp` - Required for numba cache
- ❌ Volume for `/app/keys` - Required for API keys/certificates

**Should be:**
```batch
docker run -d ^
    --name %CONTAINER% ^
    --shm-size=2g ^
    -p 5000:5000 ^
    -p 8765:8765 ^
    -v "%OPENALGO_DIR%\db:/app/db" ^
    -v "%OPENALGO_DIR%\strategies:/app/strategies" ^
    -v "%OPENALGO_DIR%\log:/app/log" ^
    -v "%OPENALGO_DIR%\keys:/app/keys" ^
    -v "%OPENALGO_DIR%\tmp:/app/tmp" ^
    -v "%OPENALGO_DIR%\.env:/app/.env:ro" ^
    --restart unless-stopped ^
    %IMAGE%
```

**Changes needed:**
1. Add `--shm-size=2g ^` after `--name %CONTAINER% ^`
2. Add `-v "%OPENALGO_DIR%\keys:/app/keys" ^` volume
3. Add `-v "%OPENALGO_DIR%\tmp:/app/tmp" ^` volume
4. Update setup function to create `keys` and `tmp` directories

---

### 3. install-docker.sh (Server Installation)

**Current docker-compose.yaml generation (Lines 298-348):**
```yaml
services:
  openalgo:
    image: openalgo:latest
    build:
      context: .
      dockerfile: Dockerfile

    container_name: openalgo-web

    ports:
      - "127.0.0.1:5000:5000"
      - "127.0.0.1:8765:8765"

    volumes:
      - openalgo_db:/app/db
      - openalgo_logs:/app/logs
      - openalgo_log:/app/log
      - openalgo_strategies:/app/strategies
      - openalgo_keys:/app/keys
      - ./.env:/app/.env:ro

    environment:
      - FLASK_ENV=production
      - FLASK_DEBUG=0
      - APP_MODE=standalone

    healthcheck:
      test: ["CMD", "curl", "-f", "http://127.0.0.1:5000/auth/check-setup"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

    restart: unless-stopped

volumes:
  openalgo_db:
    driver: local
  openalgo_logs:
    driver: local
  openalgo_log:
    driver: local
  openalgo_strategies:
    driver: local
  openalgo_keys:
    driver: local
```

**Missing:**
- ❌ `shm_size: '2gb'` - Required for scipy/numba memory operations
- ❌ `openalgo_tmp` volume and mount - Required for numba cache

**Should be:**
```yaml
services:
  openalgo:
    image: openalgo:latest
    build:
      context: .
      dockerfile: Dockerfile

    container_name: openalgo-web

    ports:
      - "127.0.0.1:5000:5000"
      - "127.0.0.1:8765:8765"

    volumes:
      - openalgo_db:/app/db
      - openalgo_log:/app/log
      - openalgo_strategies:/app/strategies
      - openalgo_keys:/app/keys
      - openalgo_tmp:/app/tmp
      - ./.env:/app/.env:ro

    environment:
      - FLASK_ENV=production
      - FLASK_DEBUG=0
      - APP_MODE=standalone

    # Shared memory for scipy/numba operations
    shm_size: '2gb'

    healthcheck:
      test: ["CMD", "curl", "-f", "http://127.0.0.1:5000/auth/check-setup"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

    restart: unless-stopped

volumes:
  openalgo_db:
    driver: local
  openalgo_log:
    driver: local
  openalgo_strategies:
    driver: local
  openalgo_keys:
    driver: local
  openalgo_tmp:
    driver: local
```

**Changes needed:**
1. Add `shm_size: '2gb'` after environment section
2. Add `openalgo_tmp:/app/tmp` volume mount
3. Add `openalgo_tmp:` volume definition
4. Remove duplicate `openalgo_logs` volume (unused)

---

## Impact if Not Updated

### Without `--shm-size=2g`:
- ❌ scipy operations may fail with memory errors
- ❌ Option Greeks calculations will fail
- ❌ Statistical analysis functions will be unreliable

### Without `/app/tmp` volume:
- ❌ numba JIT compilation will fail
- ❌ Master contract CSV processing errors
- ❌ Strategy indicators (Supertrend, EMA, TEMA) won't work

### Without `/app/keys` volume:
- ⚠️  API keys/certificates not persisted across container rebuilds
- ⚠️  Need to reconfigure on every restart

---

## Backward Compatibility

All changes are **backward compatible**:
- ✅ Existing installations can pull new image without breaking
- ✅ New volumes will be created automatically
- ✅ Shared memory allocation is transparent to application
- ✅ No database migrations required

---

## Testing Checklist

After updating scripts:

### docker-run.sh
- [ ] Create new installation: `./docker-run.sh start`
- [ ] Verify directories created: `db/`, `strategies/`, `log/`, `keys/`, `tmp/`
- [ ] Test numba: `docker exec openalgo python -c "import numba; print('OK')"`
- [ ] Check shared memory: `docker inspect openalgo --format='{{.HostConfig.ShmSize}}'`

### docker-run.bat
- [ ] Create new installation: `docker-run.bat start`
- [ ] Verify directories created: `db\`, `strategies\`, `log\`, `keys\`, `tmp\`
- [ ] Test numba: `docker exec openalgo python -c "import numba; print('OK')"`
- [ ] Check shared memory: `docker inspect openalgo --format='{{.HostConfig.ShmSize}}'`

### install-docker.sh
- [ ] Run full installation on clean Ubuntu/Debian server
- [ ] Verify docker-compose.yaml has all volumes
- [ ] Test strategy execution with indicators
- [ ] Confirm SSL and Nginx configuration works

---

## Priority

**HIGH PRIORITY** - These updates should be applied **immediately** because:

1. Without these changes, users running strategies with numba/scipy will experience errors
2. Client is already facing these issues in production
3. Desktop users (docker-run.sh/bat) will have the same problems
4. Server installations (install-docker.sh) will be deployed with incomplete configuration

---

## Recommended Actions

1. ✅ Update all three scripts
2. ✅ Test each script thoroughly
3. ✅ Update Docker Hub image with fixes
4. ✅ Document changes in CHANGELOG
5. ✅ Notify users to update their installations

---

## Notes

- The root `docker-compose.yaml` has already been updated correctly
- These installation scripts still reference the old configuration
- Users who clone the repo and use `docker-compose up` will get the correct config
- Users who use the standalone installation scripts need these updates
