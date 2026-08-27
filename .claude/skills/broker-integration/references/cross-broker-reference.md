# Cross-broker reference — how the 36 existing plugins actually behave

Measured from the tree, not from any broker's documentation. Use these as
calibration when deciding what is normal, what is a broker quirk, and what a
sensible default looks like for a new integration.

## Finding a broker's official documentation

The broker's own developer portal is the authoritative source, and its official
SDK on PyPI is the best source for literal JSON keys, enum codes and binary
offsets (see the SDK-download trick in `SKILL.md`).

If you have a local mirror of broker documentation available, grep it before
browsing a portal — but never assume one exists. Two naming traps worth knowing
if you do have docs to hand, because the vendor's product name often differs
from the OpenAlgo plugin directory:

- **AngelOne / SmartAPI** is `broker/angel/`
- **INDstocks** is `broker/indmoney/` (its API host is `api.indstocks.com`)
- **Dhan** docs cover both `broker/dhan/` and `broker/dhan_sandbox/`

When your broker has no documentation you can reach, read its **family**
sibling in the tree instead — a Noren white-label behaves essentially like
`broker/flattrade/` or `broker/shoonya/`, and an XTS white-label like
`broker/fivepaisaxts/`. See the family table in `SKILL.md`.

## Quote batch caps vary by two orders of magnitude

`BATCH_SIZE` in each plugin's `api/data.py`, as implemented today:

| Broker | Batch size | Note |
| --- | --- | --- |
| dhan | 1000 | |
| zerodha, upstox | 500 | matches Zerodha's documented `/quote` cap |
| aliceblue, arrow | 100 | arrow uses `_MULTIQUOTE_MAX_PER_REQUEST` |
| angel, fyers, compositedge, groww | 50 | fyers and groww comments cite the API limit |
| definedge | 20 | |
| several | 10 | commented "matches rate limit per second" |

There is no safe universal default. Take the broker's stated cap; if it
publishes none, binary-search live (1/10/50/100/101/150) and record the finding
in a comment.

**NUANCE — the cap can depend on the endpoint, not just the broker.** Zerodha
publishes three different limits on the same API: `/quote` (full) at 500
instruments, but `/quote/ohlc` and `/quote/ltp` at 1000. If your broker splits
LTP / OHLC / full into separate endpoints, chunk each at its own cap instead of
applying the smallest one everywhere.

**NUANCE — exceeding the cap may not fail cleanly.** Arrow returned HTTP 500
("unable to get quotes") at 101 symbols rather than a 4xx naming the limit. Do
not assume a clear error will tell you where the boundary is.

## Rate limits are per-category, not global

Dhan's published limits are the shape to expect from an Indian broker:

| | Order APIs | Data APIs | Quote APIs | Non-trading |
| --- | --- | --- | --- | --- |
| per second | 10 | 5 | **1** | 20 |
| per minute | 250 | - | unlimited | unlimited |
| per hour | 1000 | - | unlimited | unlimited |
| per day | 7000 | 100000 | unlimited | unlimited |

Two things to carry into any integration:

- **A 1/second quote limit is a design constraint, not a tuning detail.** It
  forces large batches and rules out per-symbol polling loops entirely. This is
  why `get_multiquotes` matters so much for the options tools, which request
  180+ symbols at once.
- **Order modification can be capped separately** (Dhan: 25 modifications per
  order). Smart-order retry loops can hit this.

Whatever the broker imposes is entirely separate from OpenAlgo's own
`API_RATE_LIMIT` on `/api/v1/*`, which is per-IP and not your concern inside a
broker module.

## Depth capability is loosely declared

`get_supported_depth_levels()` exists in the adapter design but is implemented
by only a couple of plugins — grepping all 36 finds `[1]` and `[5]` and little
else. The mechanism that actually runs is:

```python
def subscribe(self, symbol, exchange, mode=2, depth_level=5): ...
```

with the adapter returning `actual_depth` so the proxy can report what was
really delivered. `websocket_proxy/base_adapter.py` documents `depth_level` as
"5, 20, or 30 depending on broker support"; the client-facing protocol also
allows 50, which `broker/fyers/` serves from a second TBT socket.

If you support more than 5 levels, implement `get_supported_depth_levels()`
even though most plugins don't — otherwise the proxy cannot answer a client's
capability query and clients see `UNSUPPORTED_DEPTH_LEVEL` for a level you
actually serve.

## Capabilities brokers offer that OpenAlgo does not expose

Do not build these into a new plugin unprompted — but know they exist before
concluding a broker "can't" do something, and before designing around a gap:

- **Bracket / cover style orders** — Dhan documents "super orders" and several
  brokers have an equivalent. OpenAlgo has no common contract for them.
- **GTT / OCO** — documented by Dhan (forever orders), Flattrade and others,
  but only `broker/dhan/` and `broker/zerodha/` ship an `api/gtt_api.py`. The
  capability gate returns **501** for every other broker.
- **20-level full market depth** — Dhan documents it; OpenAlgo's common
  contract tops out per the depth mechanism above.
- **Expired-options and option-chain endpoints** — Dhan exposes both; OpenAlgo
  builds its option chain from quotes plus the symbol master instead.
- **Alerts, mutual funds, basket orders** — Zerodha documents all three; none
  has an OpenAlgo equivalent.
- **Postback / order webhooks** — widely documented, and OpenAlgo *does*
  support these via `blueprints/postback.py`. If both a broker push feed and a
  postback are configured, deduplicate on `orderid` + `order_status` +
  `filled_quantity`.
