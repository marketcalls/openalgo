# 09 - API Key Management

## Overview

An OpenAlgo API key authenticates external REST clients such as TradingView alerts, Amibroker, and SDK scripts. It is separate from the web password and broker credentials.

Each user has one current OpenAlgo API key. Generating another key replaces the existing record, so clients using the old key stop authenticating.

## Generate or View the Key

1. Sign in to OpenAlgo.
2. Open **API Key** or visit `/apikey`.
3. Generate a key if one does not exist, or copy the current key shown on the page.

The server generates 32 random bytes and hex-encodes them, producing a 64-character hexadecimal key. The database stores both an Argon2 hash for verification and an encrypted copy for authenticated UI and integration use.

Treat the displayed value as a trading credential:

- keep it in a password manager or secret store;
- pass it to scripts through an environment variable;
- never commit it, paste it into an issue, or include it in screenshots;
- regenerate it immediately after suspected exposure.

## Use the Key

Most `/api/v1` request schemas require an `apikey` field in the JSON body:

```json
{
  "apikey": "<your-64-character-key>",
  "strategy": "MyStrategy",
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": 1,
  "pricetype": "MARKET",
  "product": "MIS"
}
```

Do not assume that `Authorization` or `X-API-KEY` works for every endpoint. A small number of Telegram and WhatsApp service endpoints explicitly accept `X-API-KEY`, but the maintained [REST API documentation](../../api/README.md) defines authentication for each public route.

### Python SDK

```python
import os
from openalgo import api

client = api(
    api_key=os.environ["OPENALGO_API_KEY"],
    host="http://127.0.0.1:5000",
)
```

## Order Mode

The API Key page also stores the user's order mode:

| Mode | Behavior |
|---|---|
| `auto` | Supported requests execute immediately in the active live or analyzer path |
| `semi_auto` | Eligible live order types are queued in Action Center for approval |

The approval executor dispatches regular, smart, basket, split, options, options-multi, and place-GTT orders. Multi-order executions retain their child order IDs, while GTT execution retains its trigger ID. GTT placement is currently available only for Dhan and Zerodha; unsupported brokers return HTTP 501 through the service capability gate. Destructive close, cancel, cancel-all, modify, modify-GTT, and cancel-GTT operations are blocked by their services in semi-auto live mode.

Read-only account and market-data calls are not approval jobs.

## Regenerate a Key

1. Open `/apikey` while signed in.
2. Generate a replacement key.
3. Update every webhook, strategy, SDK client, and MCP configuration that used the old value.
4. Test a read-only call, then test order behavior in Analyzer Mode.

Replacement is immediate; there is no grace period and no collection of concurrently active keys for one user.

## Scope and Security Boundary

A valid API key maps to the user's active broker session and can call the public REST operations exposed by that instance. The application does not currently provide per-key scopes or operation checkboxes. Request schemas, Analyzer Mode, Action Center mode, service-level restrictions, and rate limits still apply.

The key does not authenticate the web administration routes, change the application password, or edit broker credentials. Remote MCP uses a separate OAuth scope and token system even though it calls OpenAlgo tools on the server side.

## Troubleshooting

| Error | Check |
|---|---|
| Invalid API key | Exact value, surrounding whitespace, and whether the key was regenerated |
| Broker session not found | Reconnect the broker from `/broker` |
| Validation error | Use the exact request fields in `docs/api`; most routes require body authentication |
| Order waits for approval | Check whether order mode is `semi_auto` and open Action Center |
| Rate-limit response | Review the endpoint-specific limit configured in `.env` |

Traffic Logs records request metadata but not the API-key-bearing request body.

---

**Previous**: [08 - Understanding the Interface](../08-understanding-interface/README.md)

**Next**: [10 - Placing Your First Order](../10-placing-first-order/README.md)
