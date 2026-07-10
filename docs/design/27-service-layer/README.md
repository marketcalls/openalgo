# 27 - Service Layer

## Boundary

Services sit between Flask resources/blueprints and broker, database, sandbox, messaging, or calculation modules. A service should accept plain validated values, return plain result data plus status, and remain reusable outside a specific HTTP route where practical.

```text
RESTX or blueprint
  -> input/session validation
  -> services/<domain>_service.py
     -> auth/mode policy
     -> broker module, sandbox manager, database, or pure calculation
  -> HTTP response
```

## Service Families

| Family | Representative modules |
|---|---|
| Order execution | `place_order_service.py`, `place_smart_order_service.py`, `basket_order_service.py`, `split_order_service.py`, `place_options_order_service.py`, `options_multiorder_service.py` |
| Order lifecycle | `modify_order_service.py`, `cancel_order_service.py`, `cancel_all_order_service.py`, `close_position_service.py`, `orderstatus_service.py` |
| Routing/approval | `order_router_service.py`, `action_center_service.py`, `pending_order_execution_service.py` |
| GTT | `place_gtt_order_service.py`, `modify_gtt_order_service.py`, `cancel_gtt_order_service.py`, `gtt_orderbook_service.py` |
| Account | `funds_service.py`, `margin_service.py`, `orderbook_service.py`, `tradebook_service.py`, `positionbook_service.py`, `holdings_service.py`, `openposition_service.py` |
| Market data | `quotes_service.py`, `depth_service.py`, `history_service.py`, `instruments_service.py`, `intervals_service.py`, `search_service.py`, `symbol_service.py`, `expiry_service.py` |
| Options analytics | `option_chain_service.py`, `option_greeks_service.py`, `option_symbol_service.py`, `synthetic_future_service.py` |
| Tools | `gex_service.py`, `gamma_density_service.py`, `iv_chart_service.py`, `iv_smile_service.py`, `oi_tracker_service.py`, `oi_profile_service.py`, `vol_surface_service.py`, `straddle_chart_service.py`, `custom_straddle_service.py`, `arbitrage_service.py` |
| Automation | `flow_executor_service.py`, `flow_scheduler_service.py`, `flow_price_monitor_service.py`, `flow_openalgo_client.py`, `historify_service.py`, `historify_scheduler_service.py` |
| Messaging | `telegram_alert_service.py`, `telegram_bot_service.py`, `whatsapp_alert_service.py`, `whatsapp_bot_service.py` |
| Runtime | `broker_keepalive_service.py`, `websocket_service.py`, `websocket_client.py`, `scalping_risk_monitor_service.py` |

Use `rg --files services` for the exact inventory; this table describes ownership rather than freezing a file count.

## Order Policy

Order services are responsible for:

1. Verifying the API key and resolving the active broker/user context.
2. Respecting analyzer mode and routing supported requests to sandbox managers.
3. Respecting auto/semi-auto policy and Action Center eligibility.
4. Lazy-importing the correct broker module in live mode.
5. Returning normalized status and publishing one appropriate typed event.

Batch services suppress per-child EventBus publication and emit one summary event. Basket execution sorts BUY before SELL and uses live concurrent batches of 10; split execution caps at 100 children and paces live calls from `ORDER_RATE_LIMIT`.

## Market And Options Policy

Market-data services normalize broker access without claiming every broker payload is identical. `history_service.py` owns `source=api` versus `source=db`. Option Greeks use Black-76 with automatic per-expiry synthetic forward resolution and spot fallback. Multi-Greeks batches option quotes and caps input at 50 symbols.

## Long-Lived Services

Long-lived services need explicit start/stop ownership and cannot retain request-scoped sessions. The scalping risk monitor is a singleton that owns an internal market-data client; the WebSocket proxy has separate lifecycle integration; schedulers restore persisted jobs at startup.

## Errors And Logging

- Validation errors belong at the resource/schema boundary when possible.
- Services translate expected unsupported/missing-module states to stable status codes.
- Do not include decrypted secrets or raw API keys in logs or returned error strings.
- Subscriber failures must not change the order HTTP result; EventBus dispatch is asynchronous and isolated.

## Adding A Service

1. Confirm behavior is shared or complex enough to live outside the route.
2. Use the existing auth, result tuple, logging, and broker import patterns for the domain.
3. Keep Flask globals out of reusable logic unless the surrounding services already define that boundary.
4. Add mode and failure-path tests proportional to risk.
5. Update this family map only if ownership changes meaningfully.
