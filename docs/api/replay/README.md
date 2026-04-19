# Replay API Reference

Endpoints for uploading market data ZIPs and controlling the replay clock for
sandbox paper trading.

All endpoints require a valid **browser session** (the same session cookie used
by the React frontend). They are **not** accessible with an API key.

CSRF protection is enforced on all `POST` endpoints — include the `X-CSRFToken`
header with a token obtained from `GET /auth/csrf-token`.

---

## Upload Market Data

### `POST /replay/api/upload`

Upload a ZIP file containing market data (NSE bhavcopy or intraday 1-minute CSVs)
and import it into the Historify DuckDB database.

#### Request

`Content-Type: multipart/form-data`

| Field         | Type   | Required | Description                                   |
|---------------|--------|----------|-----------------------------------------------|
| `file`        | File   | Yes      | ZIP file to upload (`.zip` extension only)    |
| `upload_type` | String | Yes      | `CM_BHAVCOPY`, `FO_BHAVCOPY`, or `INTRADAY_1M` |

**Upload type details:**

| `upload_type`   | Exchange stored | Interval | Typical source                 |
|-----------------|-----------------|----------|--------------------------------|
| `CM_BHAVCOPY`   | `NSE`           | `D`      | NSE equity daily bhavcopy      |
| `FO_BHAVCOPY`   | `NFO`           | `D`      | NSE F&O daily bhavcopy         |
| `INTRADAY_1M`   | `NSE` (default) | `1m`     | Any 1-minute OHLCV source      |

#### Response

```json
{
  "status": "success",
  "message": "Import successful",
  "upload_type": "CM_BHAVCOPY",
  "rows_upserted": 2065,
  "symbols_count": 1532,
  "min_timestamp": 1713187800,
  "max_timestamp": 1713187800,
  "files_processed": 1,
  "errors": []
}
```

| Field             | Type           | Description                                      |
|-------------------|----------------|--------------------------------------------------|
| `status`          | string         | `"success"` or `"error"`                         |
| `message`         | string         | Human-readable summary                           |
| `upload_type`     | string         | Echo of the requested `upload_type`              |
| `rows_upserted`   | integer        | Number of OHLCV rows written to DuckDB           |
| `symbols_count`   | integer        | Unique symbols imported                          |
| `min_timestamp`   | integer / null | Earliest epoch timestamp in imported data        |
| `max_timestamp`   | integer / null | Latest epoch timestamp in imported data          |
| `files_processed` | integer        | Number of CSV files processed inside the ZIP     |
| `errors`          | string[]       | Per-file warnings (non-fatal)                    |

#### Error response

```json
{
  "status": "error",
  "message": "Only .zip files are accepted"
}
```

#### Example (curl)

```bash
# Get CSRF token
CSRF=$(curl -s http://127.0.0.1:5000/auth/csrf-token \
  -b cookies.txt | python3 -c "import sys,json; print(json.load(sys.stdin)['csrf_token'])")

# Upload CM bhavcopy
curl -X POST http://127.0.0.1:5000/replay/api/upload \
  -b cookies.txt \
  -H "X-CSRFToken: $CSRF" \
  -F "file=@cm15APR2024bhav.csv.zip" \
  -F "upload_type=CM_BHAVCOPY"
```

#### Constraints

- Maximum file size: **200 MB** (override with `REPLAY_MAX_ZIP_SIZE_MB` env var)
- Only `.csv` and `.txt` files inside the ZIP are processed
- Zip-slip (path traversal) protection is enforced
- Uploading the same data again is safe — rows are **upserted** (no duplicates)

---

## Get Replay Status

### `GET /replay/api/replay/status`

Returns the current replay session state.

#### Response

```json
{
  "status": "success",
  "replay": {
    "enabled": true,
    "status": "running",
    "current_ts": 1713193200,
    "start_ts": 1713160200,
    "end_ts": 1713505800,
    "speed": 60.0,
    "universe_mode": "all"
  }
}
```

**`replay` object fields:**

| Field           | Type             | Description                                                   |
|-----------------|------------------|---------------------------------------------------------------|
| `enabled`       | boolean          | `true` when replay clock is active                            |
| `status`        | string           | `"stopped"`, `"running"`, or `"paused"`                       |
| `current_ts`    | integer / null   | Current replay timestamp (epoch seconds, IST-based)           |
| `start_ts`      | integer / null   | Configured start timestamp                                    |
| `end_ts`        | integer / null   | Configured end timestamp                                      |
| `speed`         | float            | Playback speed multiplier                                     |
| `universe_mode` | string           | `"all"` (all symbols) or `"active"` (symbols with positions) |

#### Example

```bash
curl http://127.0.0.1:5000/replay/api/replay/status -b cookies.txt
```

---

## Configure Replay

### `POST /replay/api/replay/config`

Configure replay parameters (date range, speed, universe mode). Must be called
before starting replay.

#### Request body

```json
{
  "start_ts": 1713160200,
  "end_ts": 1713505800,
  "speed": 60.0,
  "universe_mode": "all"
}
```

| Field           | Type    | Required | Description                                         |
|-----------------|---------|----------|-----------------------------------------------------|
| `start_ts`      | integer | No       | Start timestamp (epoch seconds). Sets `current_ts` if stopped/paused. |
| `end_ts`        | integer | No       | End timestamp (epoch seconds)                       |
| `speed`         | float   | No       | Speed multiplier. Range: `0.1` – `3600`. Default: `1.0` |
| `universe_mode` | string  | No       | `"all"` or `"active"`. Default: `"all"`             |

**Speed reference:**

| `speed` value | Market time advance per real second |
|---------------|-------------------------------------|
| `1`           | 1 minute                            |
| `5`           | 5 minutes                           |
| `10`          | 10 minutes                          |
| `30`          | 30 minutes                          |
| `60`          | 1 hour                              |
| `300`         | 5 hours                             |

All fields are optional — only provided fields are updated.

#### Response

```json
{
  "status": "success",
  "replay": {
    "enabled": false,
    "status": "stopped",
    "current_ts": 1713160200,
    "start_ts": 1713160200,
    "end_ts": 1713505800,
    "speed": 60.0,
    "universe_mode": "all"
  }
}
```

#### Example

```bash
curl -X POST http://127.0.0.1:5000/replay/api/replay/config \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF" \
  -d '{
    "start_ts": 1713160200,
    "end_ts": 1713505800,
    "speed": 60
  }'
```

**Computing timestamps:**

```python
from datetime import datetime
import pytz

IST = pytz.timezone("Asia/Kolkata")
start = IST.localize(datetime(2024, 4, 15, 9, 15, 0))
end   = IST.localize(datetime(2024, 4, 19, 15, 30, 0))
print(int(start.timestamp()))  # 1713160200
print(int(end.timestamp()))    # 1713505800
```

---

## Start / Resume Replay

### `POST /replay/api/replay/start`

Start the replay clock. If previously paused, resumes from the paused timestamp.
If stopped, resets to `start_ts` and begins advancing.

#### Request

No body required.

#### Response (success)

```json
{
  "status": "success",
  "message": "Replay started",
  "replay": {
    "enabled": true,
    "status": "running",
    "current_ts": 1713160200,
    "start_ts": 1713160200,
    "end_ts": 1713505800,
    "speed": 60.0,
    "universe_mode": "all"
  }
}
```

#### Response (error — not configured)

```json
{
  "status": "error",
  "message": "Start and end timestamps must be configured first",
  "replay": { ... }
}
```

#### Example

```bash
curl -X POST http://127.0.0.1:5000/replay/api/replay/start \
  -b cookies.txt \
  -H "X-CSRFToken: $CSRF"
```

---

## Pause Replay

### `POST /replay/api/replay/pause`

Freeze the replay clock at the current timestamp.

#### Request

No body required.

#### Response

```json
{
  "status": "success",
  "message": "Replay paused",
  "replay": {
    "enabled": true,
    "status": "paused",
    "current_ts": 1713193200,
    ...
  }
}
```

#### Example

```bash
curl -X POST http://127.0.0.1:5000/replay/api/replay/pause \
  -b cookies.txt \
  -H "X-CSRFToken: $CSRF"
```

---

## Seek Replay

### `POST /replay/api/replay/seek`

Jump the replay clock to any timestamp within the configured range.
Works in any state (running, paused, stopped — except when not configured).

#### Request body

```json
{
  "target_ts": 1713210000
}
```

| Field       | Type    | Required | Description                                           |
|-------------|---------|----------|-------------------------------------------------------|
| `target_ts` | integer | Yes      | Target epoch timestamp. Must be between `start_ts` and `end_ts`. |

#### Response

```json
{
  "status": "success",
  "message": "Replay seeked",
  "replay": {
    "current_ts": 1713210000,
    ...
  }
}
```

#### Example

```bash
# Seek to 15 Apr 2024 11:30 IST
curl -X POST http://127.0.0.1:5000/replay/api/replay/seek \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF" \
  -d '{"target_ts": 1713172200}'
```

---

## Stop Replay

### `POST /replay/api/replay/stop`

Stop the replay clock and reset to the start timestamp. Positions in the sandbox
remain open — they are NOT automatically closed.

#### Request

No body required.

#### Response

```json
{
  "status": "success",
  "message": "Replay stopped",
  "replay": {
    "enabled": false,
    "status": "stopped",
    "current_ts": 1713160200,
    ...
  }
}
```

#### Example

```bash
curl -X POST http://127.0.0.1:5000/replay/api/replay/stop \
  -b cookies.txt \
  -H "X-CSRFToken: $CSRF"
```

---

## Full Workflow Example (Python)

```python
import requests
import pytz
from datetime import datetime

BASE = "http://127.0.0.1:5000"
session = requests.Session()

# 1. Login (assumes you have a session cookie already, or use requests.Session with login)
# session.post(f"{BASE}/auth/login", data={...})

def get_csrf():
    return session.get(f"{BASE}/auth/csrf-token").json()["csrf_token"]

IST = pytz.timezone("Asia/Kolkata")
start_ts = int(IST.localize(datetime(2024, 4, 15, 9, 15)).timestamp())
end_ts   = int(IST.localize(datetime(2024, 4, 19, 15, 30)).timestamp())

# 2. Upload CM bhavcopy ZIPs (repeat for each file)
csrf = get_csrf()
with open("cm15APR2024bhav.csv.zip", "rb") as f:
    r = session.post(
        f"{BASE}/replay/api/upload",
        files={"file": f},
        data={"upload_type": "CM_BHAVCOPY"},
        headers={"X-CSRFToken": csrf},
    )
    print(r.json())

# 3. Configure replay
csrf = get_csrf()
r = session.post(
    f"{BASE}/replay/api/replay/config",
    json={"start_ts": start_ts, "end_ts": end_ts, "speed": 60},
    headers={"Content-Type": "application/json", "X-CSRFToken": csrf},
)
print(r.json())

# 4. Set price source to REPLAY
csrf = get_csrf()
r = session.post(
    f"{BASE}/settings/paper-price-source",
    json={"source": "REPLAY"},
    headers={"Content-Type": "application/json", "X-CSRFToken": csrf},
)
print(r.json())

# 5. Start replay
csrf = get_csrf()
r = session.post(f"{BASE}/replay/api/replay/start", headers={"X-CSRFToken": csrf})
print(r.json())

# 6. Poll status
import time
for _ in range(5):
    status = session.get(f"{BASE}/replay/api/replay/status").json()
    print(status["replay"]["current_ts"])
    time.sleep(2)

# 7. Pause
csrf = get_csrf()
session.post(f"{BASE}/replay/api/replay/pause", headers={"X-CSRFToken": csrf})

# 8. Stop
csrf = get_csrf()
session.post(f"{BASE}/replay/api/replay/stop", headers={"X-CSRFToken": csrf})
```

---

## HTTP Status Codes

| Code | Meaning                            |
|------|------------------------------------|
| 200  | Success                            |
| 400  | Bad request (validation error)     |
| 401  | Not authenticated (no session)     |
| 429  | Rate limit exceeded                |
| 500  | Internal server error              |

---

## Rate Limits

These endpoints share the general API rate limit (`API_RATE_LIMIT` env var, default
`50 per second`).
