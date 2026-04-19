# Paper Price Source API

Configure which price feed the sandbox uses for order fills and MTM updates.

This setting is **persistent** — it survives server restarts and is stored in the
settings database.

Requires browser session authentication. CSRF token required for `POST`.

---

## Get Paper Price Source

### `GET /settings/paper-price-source`

Returns the current paper trading price source.

#### Response

```json
{
  "paper_price_source": "LIVE"
}
```

| Field               | Type   | Values                | Description                              |
|---------------------|--------|-----------------------|------------------------------------------|
| `paper_price_source` | string | `"LIVE"`, `"REPLAY"` | Currently active price source            |

#### Example

```bash
curl http://127.0.0.1:5000/settings/paper-price-source -b cookies.txt
```

---

## Set Paper Price Source

### `POST /settings/paper-price-source`

Update the paper trading price source.

#### Request body

```json
{
  "source": "REPLAY"
}
```

| Field    | Type   | Required | Values                | Description                       |
|----------|--------|----------|-----------------------|-----------------------------------|
| `source` | string | Yes      | `"LIVE"`, `"REPLAY"` | New price source (case-insensitive) |

#### Response (success)

```json
{
  "success": true,
  "paper_price_source": "REPLAY",
  "message": "Paper price source set to REPLAY"
}
```

#### Response (error — invalid value)

```json
{
  "error": "Invalid paper_price_source 'WEBSOCKET'. Must be one of: {'LIVE', 'REPLAY'}"
}
```

HTTP status `400` is returned for invalid values.

#### Example

```bash
# Get CSRF token
CSRF=$(curl -s http://127.0.0.1:5000/auth/csrf-token \
  -b cookies.txt | python3 -c "import sys,json; print(json.load(sys.stdin)['csrf_token'])")

# Switch to Replay
curl -X POST http://127.0.0.1:5000/settings/paper-price-source \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF" \
  -d '{"source": "REPLAY"}'

# Switch back to Live
curl -X POST http://127.0.0.1:5000/settings/paper-price-source \
  -b cookies.txt \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: $CSRF" \
  -d '{"source": "LIVE"}'
```

---

## Behaviour by Mode

| Analyzer Mode | `paper_price_source` | Price source used for fills & MTM              |
|---------------|----------------------|------------------------------------------------|
| OFF           | (any)                | Not applicable — live trading                  |
| ON            | `"LIVE"` (default)   | Live broker WebSocket / multiquotes REST API   |
| ON            | `"REPLAY"`           | DuckDB at current replay timestamp             |

**Important:** Setting `paper_price_source` to `REPLAY` while Analyzer Mode is ON
but the replay clock is **not running** causes all quote lookups to return `None`.
Pending orders will stay pending until:
- You configure a date range and start the replay clock, **or**
- You switch `paper_price_source` back to `LIVE`

See [Replay Mode User Guide](../../userguide/31-replay-mode/README.md) for the
complete setup workflow.

---

## HTTP Status Codes

| Code | Meaning                            |
|------|------------------------------------|
| 200  | Success                            |
| 400  | Invalid `source` value             |
| 401  | Not authenticated (no session)     |
| 500  | Internal server error              |
