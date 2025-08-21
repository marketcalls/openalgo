# Rate Limiting

To protect OpenAlgo from abuse and ensure fair usage, rate limits are enforced at both login and API levels. These limits are configurable via the `.env` file and apply globally per IP address.

## UI Login Rate Limits

OpenAlgo applies two login-specific rate limits:

| Scope      | Limit        | Description                                      |
| ---------- | ------------ | ------------------------------------------------ |
| Per Minute | 5 per minute | Allows a maximum of 5 login attempts per minute. |
| Per Hour   | 25 per hour  | Allows a maximum of 25 login attempts per hour.  |

These limits help prevent brute-force login attempts and secure user accounts.

## API Rate Limits

OpenAlgo implements differentiated rate limiting for various types of operations:

### Order Management APIs

| Scope      | Limit         | Description                                     |
| ---------- | ------------- | ----------------------------------------------- |
| Per Second | 10 per second | Order placement, modification, and cancellation |

Applies to:
- `/api/v1/placeorder` - Place new orders
- `/api/v1/modifyorder` - Modify existing orders  
- `/api/v1/cancelorder` - Cancel orders

### Smart Order API

| Scope      | Limit        | Description                                  |
| ---------- | ------------ | -------------------------------------------- |
| Per Second | 2 per second | Multi-leg smart order placement operations   |

Applies to:
- `/api/v1/placesmartorder` - Place multi-leg smart orders

Smart orders have the most restrictive limit due to their complexity and additional processing requirements.

### General APIs

| Scope      | Limit         | Description                                     |
| ---------- | ------------- | ----------------------------------------------- |
| Per Second | 50 per second | All other API endpoints including market data  |

Applies to all other API endpoints including:
- Market data APIs (quotes, depth, history)
- Account APIs (funds, positions, holdings)
- Information APIs (orderbook, tradebook)
- Search and symbol APIs

### Webhook APIs

| Scope      | Limit          | Description                                        |
| ---------- | -------------- | -------------------------------------------------- |
| Per Minute | 100 per minute | External webhook endpoints from trading platforms  |

Applies to:
- `/strategy/webhook/<webhook_id>` - Strategy webhook from external platforms
- `/chartink/webhook/<webhook_id>` - ChartInk webhook from external platforms

These limits protect against external DoS attacks and webhook flooding.

### Strategy Management APIs

| Scope      | Limit          | Description                                     |
| ---------- | -------------- | ----------------------------------------------- |
| Per Minute | 200 per minute | Strategy creation, modification, and deletion   |

Applies to:
- `/strategy/new` - Create new strategies
- `/strategy/<id>/delete` - Delete strategies
- `/strategy/<id>/configure` - Configure strategy symbols
- `/chartink/new` - Create new ChartInk strategies
- `/chartink/<id>/delete` - Delete ChartInk strategies
- `/chartink/<id>/configure` - Configure ChartInk strategy symbols

These limits prevent strategy management abuse and database flooding.

## Configuration via .env

You can adjust the rate limits by editing the following variables in your `.env` or `.env.sample` file:

```env
# Login rate limits
LOGIN_RATE_LIMIT_MIN="5 per minute"
LOGIN_RATE_LIMIT_HOUR="25 per hour"

# API rate limits
API_RATE_LIMIT="50 per second"
ORDER_RATE_LIMIT="10 per second"
SMART_ORDER_RATE_LIMIT="2 per second"
WEBHOOK_RATE_LIMIT="100 per minute"
STRATEGY_RATE_LIMIT="200 per minute"
```

These limits follow [Flask-Limiter syntax](https://flask-limiter.readthedocs.io/en/stable/#rate-limit-string-format) and support formats like:

* `10 per second`
* `100 per minute`
* `1000 per day`

## What Happens When Limits Are Exceeded

If a client exceeds any configured rate limit:

* The server will respond with HTTP status `429 Too Many Requests`.
* A `Retry-After` header will be sent with the time to wait before retrying.
* Further requests will be blocked until the rate window resets.

## Security Impact

The rate limiting implementation provides essential protection:

### Critical Protection
- **External DoS Attacks**: Webhook endpoints are protected from unlimited external requests
- **System Overload**: Strategy operations are protected from flooding
- **Resource Exhaustion**: Prevents accidental system overwhelming

### Attack Vector Mitigation
- **Webhook Flooding**: External platforms cannot flood webhook endpoints
- **Strategy Abuse**: Prevents rapid strategy creation/deletion attempts
- **Order Flooding**: Prevents overwhelming the order management system

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

## Version History

- **v1.0.1**: Single `API_RATE_LIMIT` for all endpoints (10 per second)
- **v1.0.2**: Introduced differentiated rate limits:
  - Separate limits for order operations (10 per second)
  - Dedicated limit for smart orders (2 per second)
  - Increased general API limit to 50 per second
  - Added webhook protection (100 per minute)
  - Added strategy operation protection (200 per minute)

## Recommendations

### For API Consumers
* Avoid retrying failed login attempts rapidly
* Spread out API requests using sleep/delay logic or a rate-limiter in your client code
* Use queues or batching when dealing with large volumes of data or orders
* Implement exponential backoff when receiving 429 errors

### For Webhook Integration
* Ensure webhook calls are spread out appropriately
* Implement retry logic with delays for webhook failures
* Monitor webhook success rates to detect rate limiting

### For Strategy Management
* Avoid rapid creation/deletion of strategies
* Batch symbol configuration operations when possible
* Implement proper error handling for strategy operations

## Troubleshooting

### Common Issues

1. **"Rate limit exceeded" errors**
   - Check your request frequency
   - Implement proper retry logic with delays
   - Consider using batch operations

2. **Webhook failures**
   - Verify webhook rate limits are appropriate for your platform
   - Check if external platforms are respecting rate limits
   - Monitor webhook logs for patterns

3. **Strategy operation failures**
   - Ensure strategy operations are not happening too rapidly
   - Check for automated scripts that might be creating excessive requests
   - Verify proper error handling in strategy management code

## Customization

To modify rate limits:

1. Update the values in your `.env` file
2. Restart the application for changes to take effect
3. Ensure the `ENV_CONFIG_VERSION` matches the expected version (1.0.2)

Example customization:
```env
# Increase webhook rate limit for high-frequency platforms
WEBHOOK_RATE_LIMIT="200 per minute"

# Decrease strategy operations for tighter control
STRATEGY_RATE_LIMIT="100 per minute"

# Increase order rate limit for active trading
ORDER_RATE_LIMIT="20 per second"
```