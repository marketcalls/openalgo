# Rate limiting — pick the strategy that matches the broker's limit shape

Getting this wrong fails in both directions: too loose and you get HTTP 429s
mid-option-chain; too tight and you serialize parallel work into something
unusably slow. Three plugins solve it three different ways, and each is the
right answer to a *different* limit shape. Read the broker's published limits
first, then pick.

## Three invariants that hold regardless of strategy

**1. Rate-limit state MUST be module-level, never on `self`.**

This is the non-obvious one, and it was a real production bug. Services create
a **fresh `BrokerData(auth_token)` per request** (see
`services/option_chain_service.py`, `services/oi_tracker_service.py`, ...), so
any pacing state kept on the instance is reset away on every call and paces
nothing at all against concurrent requests. That was the root cause of
option-chain and depth bursts blowing through Fyers' real 10 req/sec cap and
getting 429'd, despite "having a rate limiter".

Put the lock and the timestamps at module scope so every importer shares them.

**2. Reserve the slot inside the lock; sleep outside it.**

All three implementations do this:

```python
with _lock:
    ...compute sleep_time...
    _last_call_time = now + sleep_time     # reserve the slot NOW
if sleep_time > 0:
    time.sleep(sleep_time)                 # sleep outside the lock
```

Reserving inside the lock stops concurrent green threads from all computing the
same slot. Sleeping outside it stops waiters blocking each other — sleep inside
the lock and you have serialized everything.

**3. Pace below the documented cap.** Every plugin leaves headroom for clock
jitter and for other modules sharing the same quota: fyers paces at 8/s against
10/s, flattrade at 38/s and 190/min against 40/s and 200/min.

## Strategy A — single global quota (fyers)

Fyers enforces **one cap per API key across every REST endpoint** — orders,
data, quotes, depth, history, funds all draw on the same 10 req/sec, 200/min,
100000/day. There is nothing to split by category, so one process-wide pacer
covers everything.

`broker/fyers/api/rate_limiter.py`:

```python
_lock = threading.Lock()
_last_call_time = 0.0
MIN_INTERVAL = 0.125          # ~8 req/s against a documented 10 req/s
MAX_RETRIES  = 3
BASE_BACKOFF = 1.0            # 1, 2, 4 when no Retry-After header
```

Every call site invokes `apply_rate_limit()` before the request.

## Strategy B — independent per-category quotas (dhan)

Dhan publishes **different limits per endpoint class** — charts at 5 req/sec,
marketfeed (quotes) at 1 req/sec. A single pacer would either throttle history
to the quote limit or blow the quote limit. So the state is a dict keyed by
category, and the category is derived from the endpoint prefix:

```python
_last_api_call_time = {"data": 0.0, "quote": 0.0}
DHAN_DATA_INTERVAL  = 0.2     # 5 req/s  -> /v2/charts/*
DHAN_QUOTE_INTERVAL = 1.1     # 1 req/s  -> /v2/marketfeed/*

category = "quote" if endpoint.startswith("/v2/marketfeed") else "data"
```

Note the 5x asymmetry. Whenever a broker publishes a table with separate
order/data/quote columns, this is the shape you need.

## Strategy C — dual rolling windows, burst-friendly (flattrade)

Flattrade publishes **two simultaneous limits: 40 req/sec AND 200 req/min.**
A fixed inter-request gap cannot satisfy both without being badly pessimistic.

The original implementation used a flat 0.55s gap — the most conservative
reading of the per-minute cap (~1.8/sec, no bursting). The measured cost, from
the fix's own notes (issue #1663): **45 history symbols took ~25 seconds
regardless of worker count**, while the same code path on Shoonya took ~2s.

The fix keeps a `deque` of reserved call timestamps and reserves the earliest
slot satisfying *both* rolling windows:

```python
FLATTRADE_MAX_PER_SECOND = 38     # against 40
FLATTRADE_MAX_PER_MINUTE = 190    # against 200
_reserved_call_times: deque = deque()
```

On each reservation it purges entries older than 60s (they can no longer
constrain any future slot), then takes the latest of the per-second and
per-minute constraints. This **permits bursting** up to the per-second cap
while still honouring the per-minute budget — which is exactly what parallel
history fetches need.

Use this whenever the broker states two windows. Do not collapse them into the
lower average.

## Reactive handling — always add it, whatever the strategy

Proactive pacing is an estimate; the broker's clock is the truth. Fyers pairs
its pacer with a 429 handler that prefers the server's own guidance:

```python
except httpx.HTTPStatusError as e:
    if e.response.status_code == 429 and _retry_count < MAX_RETRIES:
        delay = retry_delay_from_headers(e.response.headers, _retry_count)
        time.sleep(delay)
        return get_api_response(endpoint, auth, method, payload, _retry_count + 1)
```

`retry_delay_from_headers` reads the standard `Retry-After` header (both
casings) and falls back to exponential backoff when the broker does not send
one — which is common, since most Indian broker docs do not specify a
rate-limit response shape. `broker/iiflcapital/api/rate_limiter.py` carries the
same helper with a docstring recording exactly which doc pages were checked
before concluding the header was undocumented. Copy that habit.

Brokers signal rate limiting inconsistently: a 429, a 200 with an error body,
or a broker-specific code (Dhan's error 805). An `is_rate_limited(status_code,
message)` helper that checks both is worth having.

## Where the limiter must be applied

Only three plugins have a dedicated `api/rate_limiter.py` (fyers, iiflcapital,
definedge); dhan and flattrade keep it inline at the top of `api/data.py`.
Either is fine — what matters is that **every** call path goes through it,
including `api/order_api.py` and `api/funds.py` when the broker uses a single
global quota. A limiter that only guards `data.py` does not help when order
calls share the same budget.

## Checklist

- [ ] Broker's published limits read; shape identified (global / per-category / dual-window)
- [ ] State is module-level, not on `BrokerData` (services create a new instance per call)
- [ ] Slot reserved inside the lock, sleep outside it
- [ ] Paced below the documented cap for headroom
- [ ] Applied to every call path sharing the quota, not just `data.py`
- [ ] 429 handled reactively with `Retry-After` when present, exponential backoff otherwise
- [ ] Broker-specific rate-limit codes recognised (e.g. an error body returned with HTTP 200)
- [ ] Verified with a realistic burst — a full option chain, or 45 parallel history fetches — not a single call
