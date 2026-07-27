# Docker Scripts Update - Quick Reference

## What Was Changed

### All 3 Installation Scripts Updated

| Script | Desktop/Server | Platform | Status |
|--------|---------------|----------|--------|
| `docker-run.sh` | Desktop | macOS/Linux | ✅ Updated |
| `docker-run.bat` | Desktop | Windows | ✅ Updated |
| `install-docker.sh` | Server | Ubuntu/Debian | ✅ Updated |

---

## Key Changes at a Glance

### 1. Shared Memory (All Scripts)
```bash
--shm-size=2g  # Added to all docker run commands
```
**Fixes:** scipy "failed to map segment" errors

### 2. Temp Directory (All Scripts)
```bash
-v "$DIR/tmp:/app/tmp"  # macOS/Linux
-v "%DIR%\tmp:/app/tmp"  # Windows
```
**Fixes:** numba "LLVMPY_AddSymbol" and master contract errors

### 3. Keys Directory (All Scripts)
```bash
-v "$DIR/keys:/app/keys"  # macOS/Linux
-v "%DIR%\keys:/app/keys"  # Windows
```
**Fixes:** API key persistence across restarts

---

## Testing Quick Commands

### Verify Shared Memory
```bash
docker inspect openalgo --format='{{.HostConfig.ShmSize}}'
# Should show: 2147483648 (2GB)
```

### Verify Volumes
```bash
docker inspect openalgo --format='{{range .Mounts}}{{.Destination}} {{end}}'
# Should include: /app/tmp /app/keys
```

### Test numba/scipy
```bash
docker exec openalgo python -c "import numba, llvmlite, scipy; print('✓ Working')"
```

### Test Strategy Indicators
```bash
docker exec openalgo python -c "
from numba import jit
import numpy as np
@jit(nopython=True)
def ema(prices, period):
    alpha = 2.0 / (period + 1.0)
    ema = np.zeros_like(prices)
    ema[0] = prices[0]
    for i in range(1, len(prices)):
        ema[i] = alpha * prices[i] + (1 - alpha) * ema[i-1]
    return ema
result = ema(np.array([100.0, 102.0, 98.0, 101.0]), 3)
print('✓ EMA calculation works:', result[-1])
"
```

---

## For Desktop Users

### Update Existing Installation

**macOS/Linux:**
```bash
./docker-run.sh stop
mkdir -p keys tmp
./docker-run.sh pull
./docker-run.sh start
```

**Windows:**
```batch
docker-run.bat stop
md keys tmp
docker-run.bat pull
docker-run.bat start
```

---

## For Server Users

### Update Existing Installation

```bash
cd /opt/openalgo
sudo docker compose down
# Edit docker-compose.yaml to add shm_size and tmp volume
sudo docker compose up -d
```

**Or re-run installer:**
```bash
curl -O https://raw.githubusercontent.com/marketcalls/openalgo/main/install/install-docker.sh
chmod +x install-docker.sh
sudo ./install-docker.sh
```

---

## Issues Resolved

| Error | Status | Solution |
|-------|--------|----------|
| `KeyError: 'LLVMPY_AddSymbol'` | ✅ Fixed | Added /app/tmp volume |
| `OSError: failed to map segment` | ✅ Fixed | Added shm_size=2g |
| `FileNotFoundError: tmp/NSE_CM.csv` | ✅ Fixed | Added /app/tmp volume |
| API keys lost on restart | ✅ Fixed | Added /app/keys volume |

---

## Backward Compatibility

✅ **100% Compatible**
- Existing installations won't break
- New volumes created automatically
- No database migrations needed
- Works with all Docker versions

---

## Documentation

Full details in:
- `DOCKER_SCRIPTS_ANALYSIS.md` - Detailed analysis
- `UPDATES_SUMMARY.md` - Complete update guide
- `DOCKER_BUILD_GUIDE.md` - Build documentation
- `DOCKER_NUMBA_FIX.md` - Troubleshooting guide

---

## Support

If issues persist:
1. Check logs: `docker-compose logs -f`
2. Verify volumes: `docker inspect openalgo`
3. Test imports: `docker exec openalgo python -c "import numba, scipy"`
4. Join Discord: https://discord.com/invite/UPh7QPsNhP
5. GitHub Issues: https://github.com/marketcalls/openalgo/issues

---

**Last Updated:** 2026-01-28
**Version:** 2.0.0.0
**Python:** 3.12+
**Docker:** Latest
