# Order-update streaming (account-level trade updates)

This is a **second, separate** streaming contract from market data, and it is
much smaller. Do not confuse the two:

| | Market data | Order updates |
| --- | --- | --- |
| Base class | `websocket_proxy/base_adapter.BaseBrokerWebSocketAdapter` | `websocket_proxy/order_adapter.BaseOrderUpdateAdapter` |
| Subscription | per symbol + mode (1/2/3) | one `subscribe_orders` for the whole account |
| Registered in | `websocket_proxy/__init__.py` (`register_adapter`) | `services/order_update_service.py` (`_BROKER_FACTORIES`) |
| You implement | connect, subscribe, unsubscribe, disconnect, parsing | **3 methods** |
| Optional? | effectively required | yes — 17 of 36 brokers have one |

Client-facing protocol (see `docs/prompt/websockets-format.md`): the client
sends `{"action": "subscribe_orders"}` after authenticating and receives
`{"type": "order_update", ...}` events. Disabled globally by
`ORDER_UPDATES_ENABLED=FALSE`.

## The contract — three abstract methods

`BaseOrderUpdateAdapter` (an ABC) already implements connect, disconnect,
`run_forever`, reconnect with backoff, the heartbeat thread, and publishing.
You implement only:

```python
class MyBrokerOrderUpdateAdapter(BaseOrderUpdateAdapter):
    def get_ws_url(self) -> str: ...
    def get_headers(self) -> dict | None: ...
    def normalize(self, raw_message) -> dict | None: ...
```

Optional overrides when the broker needs them:

- `on_open_extra(ws)` — send a subscribe/auth frame after the socket opens
- `heartbeat_interval() -> int | None` and `send_heartbeat(ws)` — app-level keepalive
- `ws_ping_interval() -> int` — protocol-level ping

Plus a module-level factory, which is what the registry actually calls:

```python
def create_<name>_order_adapter(user_id: str) -> "MyBrokerOrderUpdateAdapter | None":
    # resolve the stored token from the DB; return None if unavailable
```

Register it in `services/order_update_service.py`:

```python
_BROKER_FACTORIES = {
    "<name>": ("broker.<name>.streaming.<name>_order_adapter",
               "create_<name>_order_adapter"),
}
```

Imports are lazy, so an entry for an unused broker costs nothing at startup.

## `normalize()` output — the exact 14-field dict

Return `None` for any frame that is not an order event (binary market-data
frames, heartbeats, broker "message"/"error" notices). Otherwise return exactly:

```python
{
    "orderid": str,            # always cast to str
    "symbol": str,             # OpenAlgo format, via to_openalgo_symbol()
    "exchange": str,
    "action": str,             # BUY / SELL, uppercased
    "quantity": int,
    "price": float,
    "trigger_price": float,
    "pricetype": str,          # MARKET / LIMIT / SL / SL-M
    "product": str,            # CNC / NRML / MIS
    "order_status": str,       # lowercase, see below
    "filled_quantity": int,
    "pending_quantity": int,
    "average_price": float,
    "rejection_reason": str,   # broker RMS/OMS text, "" unless rejected
}
```

Coerce defensively — brokers send nulls and empty strings for numerics:
`int(data.get("filled_quantity") or 0)`, `float(data.get("price") or 0)`.

### `order_status` must be mapped to OpenAlgo's lowercase vocabulary

Valid values: `open`, `trigger pending`, `complete`, `rejected`, `cancelled`
(brokers may add extras such as `expired`). Brokers emit many more intermediate
states than OpenAlgo has, and **all of them collapse to `open`**. Zerodha's map
is the model:

```python
_STATUS_MAP = {
    "COMPLETE": "complete",
    "REJECTED": "rejected",
    "CANCELLED": "cancelled",
    "OPEN": "open",
    "UPDATE": "open",
    "TRIGGER PENDING": "trigger pending",
    "VALIDATION PENDING": "open",
    "PUT ORDER REQ RECEIVED": "open",
    "OPEN PENDING": "open",
    "MODIFY VALIDATION PENDING": "open",
}
```

Fall back to `raw_status.lower() or "open"` for unmapped states rather than
dropping the event.

### Symbol conversion — prefer the token-keyed lookup

Use `to_openalgo_symbol(broker_symbol, exchange, token=None)` from
`websocket_proxy/order_adapter.py`. **Pass the token when the broker's payload
carries one** — the token-keyed lookup is more reliable than matching on the
broker's tradingsymbol string:

```python
symbol = to_openalgo_symbol(
    data.get("tradingsymbol", ""), exchange, token=data.get("instrument_token")
)
```

It falls back to `get_oa_symbol` on the tradingsymbol if the token misses. This
matters for suffixed symbols (`NHPC-EQ` -> `NHPC`) and for derivatives where the
broker's symbology diverges from OpenAlgo's.

### NUANCE — the same socket may carry market data and order updates

Zerodha's order adapter receives the Kite ticker's binary frames on the same
connection and must discard them:

```python
if isinstance(raw_message, (bytes, bytearray)):
    return None  # binary market-data / heartbeat frames
```

Then filter on the event type (`if message.get("type") != "order": return None`)
before parsing. Skipping either check produces spurious order events.

## Brokers with no push feed

Subclass nothing — `_order_update_service` builds a
`PollingOrderUpdateAdapter(broker_name, user_id, poll_interval)` instead, which
polls the REST orderbook and diffs it. Just add the broker to
`_POLLING_BROKERS` (currently `{"groww"}`). This is the correct fallback when
the broker has no order socket at all; do not hand-roll a polling loop.

## Postback webhooks

`blueprints/postback.py` exposes `/postback/<broker>` for brokers that push
order updates over HTTPS instead of (or in addition to) a socket. Production
deployments with a public URL can use this.

**If both a broker feed and a postback are configured, deduplicate on
`orderid` + `order_status` + `filled_quantity`** — otherwise every fill is
emitted twice.

## The exception in the tree

`broker/iiflcapital/streaming/iiflcapital_order_adapter.py` deliberately does
**not** subclass `BaseOrderUpdateAdapter` (it carries a comment explaining why —
it needs a bespoke connect/subscribe handshake and handles both order and trade
message kinds). Read that comment before copying it; the base class is the
right default for a new broker.
