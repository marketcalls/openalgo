# Rate Limiting

To protect OpenAlgo from abuse and ensure fair usage, rate limits are enforced at both login and API levels. These limits are configurable via the `.env` file and apply globally per IP address.

## UI Login Rate Limits

OpenAlgo applies two login-specific rate limits:

| Scope | Limit | Description |
|-------|-------|-------------|
| Per Minute | 5 per minute | Allows a maximum of 5 login attempts per minute |
| Per Hour | 25 per hour | Allows a maximum of 25 login attempts per hour |

These limits help prevent brute-force login attempts and secure user accounts.

## API Rate Limits

OpenAlgo implements differentiated rate limiting for various types of operations:

### Order Management APIs

| Scope | Limit | Description |
|-------|-------|-------------|
| Per Second | 10 per second | Order placement, modification, cancellation, and GTT writes |

**Applies to:**
- `/api/v1/placeorder` - Place new orders
- `/api/v1/modifyorder` - Modify existing orders
- `/api/v1/cancelorder` - Cancel orders
- `/api/v1/optionsorder` and `/api/v1/optionsmultiorder` - Options execution
- `/api/v1/placegttorder`, `/api/v1/modifygttorder`, and `/api/v1/cancelgttorder` - GTT writes

### Smart Order API

| Scope | Limit | Description |
|-------|-------|-------------|
| Per Second | 10 per second | Position-aware smart order operations |

**Applies to:**
- `/api/v1/placesmartorder` - Reconcile a symbol position to a target size

`SMART_ORDER_RATE_LIMIT` is independent from `ORDER_RATE_LIMIT`, even though both currently default to 10 per second.

### General APIs

| Scope | Limit | Description |
|-------|-------|-------------|
| Per Second | 50 per second | All other API endpoints including market data |

**Applies to all other API endpoints including:**
- Market data APIs (quotes, depth, history)
- Account APIs (funds, positions, holdings)
- Information APIs (orderbook, tradebook)
- Search and symbol APIs

### Webhook APIs

| Scope | Limit | Description |
|-------|-------|-------------|
| Per Minute | 100 per minute | External webhook endpoints from trading platforms |

**Applies to:**
- `/chartink/webhook/<webhook_id>` - ChartInk webhook from external platforms
- `/flow/webhook/<token>` - Flow workflow webhook from external platforms
- `/flow/webhook/<token>/<symbol>` - the same, with the symbol in the path

These limits protect against external DoS attacks and webhook flooding.

The Flow webhook is counted twice at this budget, once by caller address and
once by workflow token, because the two bound different things. The address
limit is what stops a caller walking the token space; the token limit is what
caps the order flow a single leaked token can drive, however many addresses
replay it. Both routes above share one budget per key, so alternating between
them does not double the rate.

Unlike the rest of the product, a throttled Flow webhook answers `429` with a
JSON body rather than redirecting to the `/rate-limited` page. Automated
callers such as TradingView do not read an HTML page, and would otherwise
record a redirect as a delivered alert.

### Strategy Management APIs

| Scope | Limit | Description |
|-------|-------|-------------|
| Per Minute | 200 per minute | Strategy creation, modification, and deletion |

**Applies to:**
- `/chartink/new` - Create new ChartInk strategies
- `/chartink/<id>/delete` - Delete ChartInk strategies
- `/chartink/<id>/configure` - Configure ChartInk strategy symbols

## Configuration via .env

You can adjust the rate limits by editing the following variables in your `.env` file:

```env
# Login rate limits
LOGIN_RATE_LIMIT_MIN="5 per minute"
LOGIN_RATE_LIMIT_HOUR="25 per hour"

# API rate limits
API_RATE_LIMIT="50 per second"
ORDER_RATE_LIMIT="10 per second"
SMART_ORDER_RATE_LIMIT="10 per second"
WEBHOOK_RATE_LIMIT="100 per minute"
STRATEGY_RATE_LIMIT="200 per minute"
```

These limits follow [Flask-Limiter syntax](https://flask-limiter.readthedocs.io/en/stable/#rate-limit-string-format) and support formats like:
- `10 per second`
- `100 per minute`
- `1000 per day`
- `10 per second;40 per minute` (compound — both limits enforced simultaneously)

## WebSocket Connection Limits

OpenAlgo exposes a single WebSocket server (default `ws://127.0.0.1:8765`) that downstream client applications connect to for streaming market data. These limits are independent of the HTTP rate limits above and split into three dimensions: upstream broker capacity, downstream client connections, and per-client buffering.

### Upstream broker capacity

These variables control how OpenAlgo talks to the broker's market-data feed:

| Variable | Default | Description |
|---|---|---|
| `MAX_SYMBOLS_PER_WEBSOCKET` | 1000 | Maximum symbols multiplexed on one broker WebSocket |
| `MAX_WEBSOCKET_CONNECTIONS` | 3 | Maximum broker WebSocket connections per user/broker pool |

Total upstream symbol capacity is approximately `MAX_SYMBOLS_PER_WEBSOCKET × MAX_WEBSOCKET_CONNECTIONS` (for example, 1000 × 3 = 3000 symbols).

### Downstream client connections

There is **no application-level cap** on how many separate client applications or processes can connect to OpenAlgo's own WebSocket server. `websocket_proxy/server.py` calls `websockets.serve()` without a connection limit and registers each client in `self.clients` with no count check. The practical ceiling is the server's file-descriptor / `ulimit -n` budget.

### Per-client settings

Each client connection has its own send queue and keepalive timers:

| Variable | Default | Description |
|---|---|---|
| `WS_MAX_QUEUE` | 1024 | Per-client send queue; absorbs tick bursts without disconnecting slow clients |
| `WS_PING_INTERVAL` | 20 | Seconds between keepalive pings |
| `WS_PING_TIMEOUT` | 20 | Seconds to wait for a pong before closing the connection |

### Shared upstream feed and refcounting

The broker feed is pooled per user/broker (`{broker}_{user_id}`) in `websocket_proxy/broker_factory.py` and shared across all connected clients. Subscriptions are refcounted by `ConnectionPool` in `websocket_proxy/connection_manager.py`. A second client subscribing to the same symbol does **not** open a new upstream broker connection or consume another `MAX_SYMBOLS_PER_WEBSOCKET` slot — upstream capacity is consumed by unique symbols, not by the number of downstream client connections.

## What Happens When Limits Are Exceeded

If a client exceeds any configured rate limit:

1. The server will respond with HTTP status `429 Too Many Requests`
2. Further requests will be blocked until the moving window permits another request

Clients should not require a `Retry-After` header because header emission is not explicitly enabled in `limiter.py`.

## Error Response

```json
{
  "status": "error",
  "message": "Rate limit exceeded. Please try again later."
}
```

## Security Impact

The rate limiting implementation provides essential protection:

### Critical Protection

| Protection | Description |
|------------|-------------|
| External DoS Attacks | Webhook endpoints are protected from unlimited external requests |
| System Overload | Strategy operations are protected from flooding |
| Resource Exhaustion | Prevents accidental system overwhelming |

### Attack Vector Mitigation

| Attack | Protection |
|--------|------------|
| Webhook Flooding | External platforms cannot flood webhook endpoints |
| Strategy Abuse | Prevents rapid strategy creation/deletion attempts |
| Order Flooding | Prevents overwhelming the order management system |

## Implementation Details

### Rate Limiting Strategy

OpenAlgo uses the **moving-window** strategy for rate limiting, which provides more accurate rate limiting compared to fixed-window approaches.

### Storage Backend

Rate limit counters are stored in memory (`memory://`), which means:
- Fast performance with minimal latency
- Counters reset when the application restarts
- Suitable for single-user deployments

### Key Function

Rate limits are applied per IP address using `get_remote_address` as the key function. Each unique IP address has its own rate limit counter.

## Recommendations

### For API Consumers

- Avoid retrying failed login attempts rapidly
- Spread out API requests using sleep/delay logic or a rate-limiter in your client code
- Use queues or batching when dealing with large volumes of data or orders
- Implement exponential backoff when receiving 429 errors

### For Webhook Integration

- Ensure webhook calls are spread out appropriately
- Implement retry logic with delays for webhook failures
- Monitor webhook success rates to detect rate limiting

### For Strategy Management

- Avoid rapid creation/deletion of strategies
- Batch symbol configuration operations when possible
- Implement proper error handling for strategy operations

## Troubleshooting

### Common Issues

**"Rate limit exceeded" errors**
- Check your request frequency
- Implement proper retry logic with delays
- Consider using batch operations

**Webhook failures**
- Verify webhook rate limits are appropriate for your platform
- Check if external platforms are respecting rate limits
- Monitor webhook logs for patterns

**Strategy operation failures**
- Ensure strategy operations are not happening too rapidly
- Check for automated scripts that might be creating excessive requests
- Verify proper error handling in strategy management code

## Customization

To modify rate limits:

1. Update the values in your `.env` file
2. Restart the application for changes to take effect

Example customization:

```env
# Increase webhook rate limit for high-frequency platforms
WEBHOOK_RATE_LIMIT="200 per minute"

# Decrease strategy operations for tighter control
STRATEGY_RATE_LIMIT="100 per minute"

# Increase order rate limit for active trading
ORDER_RATE_LIMIT="20 per second"
```

---

**Back to**: [API Documentation](./README.md)
