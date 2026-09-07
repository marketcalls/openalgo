"""The agent's indicator catalogue over the Rust-backed ``openalgo.ta`` library.

Three modules, and the split is deliberate:

* :mod:`registry` is the table of facts about the 127 callables on the ``ta``
  singleton: which OHLCV series each one takes, what it returns and in what
  order, and how many bars of warm-up it needs. It is asserted against
  ``dir(ta)`` at import, so an SDK upgrade that adds or removes an indicator
  fails loudly here instead of silently shipping a stale list.
* :mod:`descriptions` is one sentence per indicator, so the catalogue is
  searchable by intent rather than only by method name.
* :mod:`compute` is the single dispatcher every caller goes through. It owns
  the argument coercion, the warm-up padding and the refusals.

Nothing here touches the network, the database or the clock. Candles arrive as
a DataFrame the caller fetched; every decision leaves as a return value. That is
what lets the tool layer, and a test, drive it identically.
"""

from __future__ import annotations

__all__ = ["compute", "descriptions", "registry"]
