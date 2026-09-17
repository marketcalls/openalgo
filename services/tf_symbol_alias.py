"""TradeFinder's name for a stock, mapped to the one the broker's master uses.

After a corporate action TradeFinder keeps trading under the old name while the
symbol master moves to the new one, so a ranked-list symbol can be one no
history or option-chain call will answer for. On 17-Sep-2026 that silently
dropped TATAMOTORS -- the day's number one -- from every price study, because
the master lists it as TMPV under the same ISIN.

Anything still unmapped should be reported by name rather than skipped
quietly, so a new rename shows up as a name and not as a stock that stopped
being studied. The frontend keeps the same table in lib/trading/tfSymbol.ts.
"""

from __future__ import annotations

SYMBOL_ALIASES: dict[str, str] = {
    "TATAMOTORS": "TMPV",
}


def tradable_symbol(symbol: str) -> str:
    """The name to ask the broker for. Unknown symbols pass through unchanged."""
    return SYMBOL_ALIASES.get(symbol, symbol)
