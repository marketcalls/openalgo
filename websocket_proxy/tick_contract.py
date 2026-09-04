# websocket_proxy/tick_contract.py
"""
Quote-mode tick field contract.

Broker adapters publish their mapped payloads verbatim over ZeroMQ, and
several mappers only add OHLC fields when the broker snapshot happens to
carry them (see e.g. broker/zerodha/streaming/zerodha_mapping.py, which
updates open/high/low/close only "if available"). Clients that chart from
Quote-mode ticks therefore cannot tell "field absent" from "field coming
later", and every broker behaves differently.

This module guarantees the documented Quote Data field set:

* Every Quote-mode tick contains ltp, open, high, low, close, volume and
  timestamp keys after normalisation.
* A field the broker did not supply is set to ``None`` — never to 0. A
  fabricated 0 is worse than a visible null: OHLC zeros render as doji
  bars on client charts and corrupt interval aggregation, while null is
  unambiguous "not provided".
* Fields the broker did supply — including zeros — are preserved
  verbatim. This module never overwrites adapter values.

The normaliser is deliberately stdlib-only so it can be unit-tested
standalone (see test/test_quote_tick_contract.py) and is safe on the hot
path: it mutates the freshly-parsed tick dict in place and does no work
when the contract is already satisfied.
"""

# Numeric Quote mode, mirroring websocket_proxy.mode_utils (kept as a
# literal here so this module stays dependency-free).
QUOTE_MODE = 2

# Fields a Quote-mode tick guarantees after normalisation.
QUOTE_REQUIRED_FIELDS = ("ltp", "open", "high", "low", "close", "volume", "timestamp")

# Adapters disagree on the last-traded-price key name.
_LTP_ALIASES = ("ltp", "last_price")


def normalize_quote_tick(tick):
    """Enforce the Quote-mode field contract on a parsed tick.

    Args:
        tick: The market-data payload forwarded by the adapter (expected
            to be a dict from json.loads; other types pass through).

    Returns:
        The same tick dict, with any missing contract fields added as
        None. Existing values are never modified.

    Idempotent: a tick that already satisfies the contract is returned
    unchanged, making repeat normalisation a no-op.
    """
    if not isinstance(tick, dict):
        return tick

    for field in QUOTE_REQUIRED_FIELDS:
        if field in tick:
            continue
        if field == "ltp":
            aliased = next((tick[name] for name in _LTP_ALIASES if name in tick), None)
            tick["ltp"] = aliased
        else:
            tick[field] = None
    return tick
