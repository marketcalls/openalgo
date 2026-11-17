"""Order-book and position-book fields shared by the Symphony XTS plugins.

compositedge, fivepaisaxts, ibulls, iifl, jainamxts, rmoney and wisdom all map
the same XTS interactive answers (https://symphonyfintech.com/xts-trading-front-end-api-v2/),
and each had the same three defects, fixed here once:

- ``exact_order_id``: an order id read through float() lost its last digits.
- ``traded_average_price``: a carried position showed the previous close as
  its average.
- ``position_rows``: an error answer crashed six plugins' position book and
  read as an empty book on Wisdom.
"""

import math
from decimal import Decimal, InvalidOperation

from utils.position_read import broker_display_name


def exact_order_id(value):
    """An XTS order id as text, digit for digit.

    XTS order ids run to 20 digits (the docs' own Modify Order example uses
    10001253450000041478), more than a float holds exactly: float() made
    11001263160000030116, ...0117 and ...0118 into one id, so every order of
    a day shared it in the order book and trade book (issue #2462). JSON
    integers and digit strings are kept as they are; a missing id reads "0",
    as before.
    """
    if value is None or isinstance(value, bool):
        return "0"
    if isinstance(value, int):
        return str(value)
    text = str(value).strip()
    if not text:
        return "0"
    if text.isdigit():
        return str(int(text))
    try:
        number = Decimal(text)
    except InvalidOperation:
        return text
    if number.is_finite() and number == number.to_integral_value():
        return str(int(number))
    return text


def _positive_price(value):
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 0 else None


def traded_average_price(position, net_quantity):
    """The average a trader paid (long) or received (short) for a position.

    For a position carried overnight XTS fills BuyAveragePrice and
    SellAveragePrice with the previous close it marked the position to, and
    keeps the traded average in ActualBuyAveragePrice and
    ActualSellAveragePrice (issue #2462; the same fields are in the live
    Wisdom answers quoted on issue #633). The docs' position table lists only
    the first pair, so a missing or zero Actual field falls back to it. A
    flat position has no average.
    """
    if net_quantity > 0:
        fields = ("ActualBuyAveragePrice", "BuyAveragePrice")
    elif net_quantity < 0:
        fields = ("ActualSellAveragePrice", "SellAveragePrice")
    else:
        return 0.0
    for field in fields:
        price = _positive_price(position.get(field))
        if price is not None:
            return price
    return 0.0


def position_rows(position_data, broker):
    """The position container a plugin's transform_positions_data reads.

    Returns ``{"positionList": [...]}`` for an answer XTS marks a success,
    including an empty book. Any other answer raises ValueError with a
    sentence for the trader, which the position book service and the CSV
    export report: an error must not read as having no positions (issue
    #633). Wisdom showed an empty book while its own API returned positions,
    and the other XTS plugins crashed on the empty list they returned.
    """
    if isinstance(position_data, dict) and position_data.get("type") == "success":
        result = position_data.get("result")
        rows = result.get("positionList") if isinstance(result, dict) else None
        return {"positionList": rows if isinstance(rows, list) else []}

    name = broker_display_name(broker)
    reason = ""
    if isinstance(position_data, dict):
        reason = str(position_data.get("description") or "").strip().rstrip(".")
    detail = f" Its answer: {reason}." if reason else ""
    raise ValueError(
        f"{name} did not return your positions.{detail} "
        f"Refresh in a moment, and log in to {name} again if it keeps happening."
    )
