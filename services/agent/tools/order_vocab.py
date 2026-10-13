"""The words a model uses for an order, translated to OpenAlgo's own codes.

A model writes ``intraday`` for MIS, ``SL-M`` with a hyphen, ``B`` for BUY and
``NSE:SBIN`` for a symbol it saw in a quote card. Each spelling here is
unambiguous, so reading one cannot change what the operator approved; anything
not listed is upper-cased and left for the caller's own validator to refuse.

This module only reads strings. It sends nothing, and it lives apart from
``orders.py`` so a read-only toolkit (``account.py``) can share the vocabulary
without importing the toolkit that changes a real account.
"""

from __future__ import annotations

import re
from typing import Any

from services.agent.tools.base import invalid_argument
from utils.constants import (
    ACTION_BUY,
    ACTION_SELL,
    PRICE_TYPE_SL,
    PRICE_TYPE_SLM,
    PRODUCT_CNC,
    PRODUCT_MIS,
    PRODUCT_NRML,
)

#: Other spellings a model uses for a product, mapped to the OpenAlgo code.
#: Each is unambiguous, so reading one cannot change what the operator approved.
PRODUCT_ALIASES: dict[str, str] = {
    "INTRADAY": PRODUCT_MIS,
    "DELIVERY": PRODUCT_CNC,
    "CARRYFORWARD": PRODUCT_NRML,
    "CARRY_FORWARD": PRODUCT_NRML,
    "NORMAL": PRODUCT_NRML,
}

#: Other spellings of a price type, keyed after spaces and hyphens are folded
#: to underscores, so ``SL M``, ``SL-M`` and ``sl_m`` all land on one key.
PRICE_TYPE_ALIASES: dict[str, str] = {
    "SL_M": PRICE_TYPE_SLM,
    "SLM": PRICE_TYPE_SLM,
    "STOPLOSS_MARKET": PRICE_TYPE_SLM,
    "STOP_LOSS_MARKET": PRICE_TYPE_SLM,
    "STOPLOSS": PRICE_TYPE_SL,
    "STOP_LOSS": PRICE_TYPE_SL,
    "STOPLOSS_LIMIT": PRICE_TYPE_SL,
    "STOP_LOSS_LIMIT": PRICE_TYPE_SL,
}

#: One-letter sides.
ACTION_ALIASES: dict[str, str] = {"B": ACTION_BUY, "S": ACTION_SELL}


def canonical_product(value: Any) -> str:
    """Upper-case a product and translate a known alias to its OpenAlgo code.

    Args:
        value: The product the model supplied.

    Returns:
        The canonical code when the value is a known alias, otherwise the value
        stripped and upper-cased, for the caller to validate.
    """
    text = "" if value is None else str(value).strip().upper()
    return PRODUCT_ALIASES.get(text, text)


def canonical_price_type(value: Any) -> str:
    """Upper-case a price type and translate a known alias to its OpenAlgo code.

    Args:
        value: The price type the model supplied.

    Returns:
        The canonical code when the value is a known alias, otherwise the value
        stripped and upper-cased, for the caller to validate.
    """
    text = "" if value is None else str(value).strip().upper()
    folded = re.sub(r"[\s_-]+", "_", text)
    return PRICE_TYPE_ALIASES.get(folded, text)


def canonical_action(value: Any) -> str:
    """Upper-case an action and translate ``B`` or ``S`` to BUY or SELL.

    Args:
        value: The action the model supplied.

    Returns:
        The canonical side when the value is a known alias, otherwise the value
        stripped and upper-cased, for the caller to validate.
    """
    text = "" if value is None else str(value).strip().upper()
    return ACTION_ALIASES.get(text, text)


def split_exchange_prefix(symbol: Any, exchange: Any) -> tuple[str, str]:
    """Separate an ``EXCHANGE:SYMBOL`` spelling into its two parts.

    A model that has seen ``NSE:SBIN`` in a quote card often sends it as the
    symbol. The prefix is used when the exchange argument is empty or names the
    same exchange. When the two disagree the order is refused rather than
    guessed, because picking either one could trade a different instrument
    from the one the operator approved.

    Args:
        symbol: The symbol the model supplied, with or without a prefix.
        exchange: The exchange the model supplied, possibly empty.

    Returns:
        The symbol and exchange, both stripped and upper-cased. Either may be
        empty; the caller's own validators reject that.

    Raises:
        RetryAgentRun: When the prefix and the exchange argument disagree.
    """
    text = "" if symbol is None else str(symbol).strip().upper()
    venue = "" if exchange is None else str(exchange).strip().upper()
    if ":" not in text:
        return text, venue

    prefix, _, bare = (part.strip() for part in text.partition(":"))
    if venue and venue != prefix:
        invalid_argument(
            "symbol",
            f"it is written as {text}, which names {prefix}, but the exchange argument is "
            f"{venue}, and the two disagree.",
            f"Pass the bare symbol {bare} with the exchange the operator meant, and say which "
            "one you used.",
        )
    return bare, prefix
