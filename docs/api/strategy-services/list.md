# Strategy List

List the strategies this API key owns, newest first.

## Endpoint URL

```http
Local Host   :  POST http://127.0.0.1:5000/api/v1/strategy/list
Ngrok Domain :  POST https://<your-ngrok-domain>.ngrok-free.app/api/v1/strategy/list
Custom Domain:  POST https://<your-custom-domain>/api/v1/strategy/list
```

## Sample API Request

```json
{
  "apikey": "<your_app_apikey>"
}
```

## Sample cURL Request

```bash
curl -X POST http://127.0.0.1:5000/api/v1/strategy/list \
  -H 'Content-Type: application/json' \
  -d '{
  "apikey": "<your_app_apikey>"
}'
```

## Sample API Response

```json
{
  "status": "success",
  "data": [
    {
      "id": 7,
      "name": "NIFTY Short Straddle",
      "strategy_kind": "batch",
      "direction": "both",
      "universe_tab": "weekly_monthly",
      "underlying": "NIFTY",
      "underlying_exchange": "NSE_INDEX",
      "strategy_type": "intraday",
      "entry_time": "09:20",
      "exit_time": "15:10",
      "product": "NRML",
      "pricetype": "MARKET",
      "overall_sl_mtm": -5000.0,
      "overall_target_mtm": 8000.0,
      "lock_profit": {
        "mode": "lock_and_trail",
        "if_profit_reaches": 5000.0,
        "lock_profit": 2500.0,
        "trail_step": 1000.0
      },
      "trail_sl_to_entry": false,
      "scheduler": {
        "enabled": true,
        "days": ["MON", "TUE", "WED", "THU", "FRI"],
        "start_time": "09:20",
        "auto_stop_time": "15:10",
        "default_mode": "sandbox"
      },
      "live_enabled": false,
      "webhook_locked": false,
      "webhook_ip_allowlist": null,
      "daily_loss_limit_inr": 10000.0,
      "status": "running",
      "current_run_id": 42,
      "created_at": "2026-08-24T04:11:52.104883+00:00",
      "updated_at": "2026-08-30T03:50:11.482913+00:00",
      "last_finalized_run": {
        "id": 41,
        "pnl_realized": 1250.0,
        "stopped_at": "2026-08-29T09:40:11.482913+00:00"
      }
    },
    {
      "id": 4,
      "name": "RELIANCE Signals",
      "strategy_kind": "signal",
      "direction": "long_only",
      "universe_tab": "stocks_fno",
      "underlying": "MULTI",
      "underlying_exchange": "NSE",
      "strategy_type": "positional",
      "entry_time": null,
      "exit_time": null,
      "product": "MIS",
      "pricetype": "MARKET",
      "overall_sl_mtm": null,
      "overall_target_mtm": null,
      "lock_profit": null,
      "trail_sl_to_entry": false,
      "scheduler": null,
      "live_enabled": true,
      "webhook_locked": false,
      "webhook_ip_allowlist": ["52.89.214.238/32"],
      "daily_loss_limit_inr": null,
      "status": "stopped",
      "current_run_id": null,
      "created_at": "2026-08-18T06:02:19.775410+00:00",
      "updated_at": "2026-08-18T06:02:19.775410+00:00",
      "last_finalized_run": {
        "id": 16,
        "pnl_realized": -52.0,
        "stopped_at": "2026-08-18T06:02:19.775410+00:00"
      }
    }
  ]
}
```

## Sample API Request (Filtered)

```json
{
  "apikey": "<your_app_apikey>",
  "status": "running",
  "q": "NIFTY"
}
```

## Request Body

| Parameter | Description | Mandatory/Optional | Default Value |
|-----------|-------------|-------------------|---------------|
| apikey | Your OpenAlgo API key | Mandatory | - |
| status | Filter by strategy status: stopped, running, paused, errored | Optional | null (no filter) |
| q | Case-insensitive substring match on the strategy name, 100 characters at most | Optional | null (no filter) |

## Response Fields

| Field | Type | Description |
|-------|------|-------------|
| status | string | "success" or "error" |
| data | array | Strategy objects, newest first by creation time |

Each object in `data`:

| Field | Type | Description |
|-------|------|-------------|
| id | integer | Strategy id, used as `strategy_id` on every other endpoint |
| name | string | Strategy name, unique per user |
| strategy_kind | string | `batch` or `signal` |
| direction | string | `both`, `long_only` or `short_only`. Signal mode only |
| universe_tab | string | Which instrument universe the strategy was built from: `weekly_monthly`, `monthly_only`, `stocks_fno` or `mcx`. It decides which segments a leg may use, and cash is offered on `stocks_fno` only. A strategy saved without one has it derived from its own legs |
| underlying | string | Underlying symbol |
| underlying_exchange | string | Exchange the underlying is quoted on |
| strategy_type | string | `intraday` or `positional` |
| entry_time | string or null | IST entry time as `HH:MM` |
| exit_time | string or null | IST square-off time as `HH:MM` |
| product | string | `CNC`, `NRML` or `MIS`, as configured. It is read as the intent rather than the literal when an order goes out: `MIS` is intraday everywhere, anything else means carry, which is sent as `NRML` on a derivatives venue and `CNC` on cash. See the `product` field on [`/orders`](./orders.md) for what was actually sent |
| pricetype | string | `MARKET`. Neither the strategy nor a leg carries a price, so a LIMIT, SL or SL-M order would go out priced at zero; exits are MARKET on every path regardless |
| overall_sl_mtm | number or null | Strategy-level stop loss in rupees of MTM |
| overall_target_mtm | number or null | Strategy-level target in rupees of MTM |
| lock_profit | object or null | `{mode, if_profit_reaches, lock_profit, trail_step}` |
| trail_sl_to_entry | boolean | Whether a stop on one leg trails the others to entry |
| scheduler | object or null | `{enabled, days, start_time, auto_stop_time, default_mode}` |
| live_enabled | boolean | Whether this strategy may run in `live` mode |
| webhook_locked | boolean | Whether the webhook kill switch is engaged |
| webhook_ip_allowlist | array or null | CIDR ranges allowed to trigger the webhook |
| daily_loss_limit_inr | number or null | Daily loss ceiling in rupees |
| status | string | `stopped`, `running`, `paused` or `errored` |
| current_run_id | integer or null | The run this strategy is executing, if any |
| created_at | string | ISO 8601 UTC |
| updated_at | string | ISO 8601 UTC |
| last_finalized_run | object or null | Most recently finalised run: `{id, pnl_realized, stopped_at}`. For a stopped strategy, `pnl_realized` is the durable final P&L and unrealised P&L is zero; do not infer final P&L from an earlier checkpoint |

## Notes

- Rows are ordered by creation time, **newest first**.
- The list form omits `legs`. Call [`/api/v1/strategy/status`](./status.md) for one strategy's legs.
- Only strategies owned by the API key's user are returned. There is no cross-user view.
- No response here or anywhere else on this surface carries a webhook token. Only its SHA-256 digest is stored, so there is nothing to return.
- An out-of-vocabulary `status` is a 400, not an empty list.
- `status` and `q` may be sent as `null` explicitly; that is the same as omitting them.
- A checkpoint is a live mark only. After a run stops, use `last_finalized_run.pnl_realized` as the final total; its unrealised P&L is `0.00` because the run has confirmed flatness.

## Use Cases

- **Dashboards**: enumerate strategies and their live status without a browser session
- **Health checks**: find every strategy whose `status` is `errored`
- **Automation**: resolve a strategy name to the `strategy_id` the other endpoints need

---

**Back to**: [API Documentation](../README.md)
