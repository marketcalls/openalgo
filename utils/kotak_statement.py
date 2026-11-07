# utils/kotak_statement.py
"""Parser for Kotak Securities' "Transaction Statement" CSV.

This is the file Kotak's back office exports (Trade Date, Trade Time, Order
Time, Security Name, ISIN, Exchange, Order Source, Transaction Type, Quantity,
Market Rate, Total, GST, Brokerage, Misc., Total Charges, STT/CTT). It is not
the Zerodha Console tradebook, and unlike that file it:

- has no symbol column - the instrument is free text in "Security Name":
  F&O as ``OPTIDXNIFTY     06OCT2026CE  22850.00``, equities as the company
  name (``Cyient Ltd``);
- labels every F&O row ``NSEDERV``, SENSEX/BANKEX included;
- has one line per ORDER at the average price, with no trade id or order id;
- writes dates as DD/MM/YYYY with the time in a separate column.

Pure functions only (no database access) so they can be unit-tested; the
equity name -> symbol lookup is injected by the caller.

Only option instruments are supported for F&O (the only thing traded on these
accounts). Anything else is reported back as unsupported, never guessed.
"""

import re
from datetime import datetime

# Headers (after _normalize_header) that together identify this file. Chosen
# because no other broker export we handle has "security_name"/"market_rate".
_SIGNATURE = {"security_name", "market_rate", "transaction_type", "trade_date", "trade_time"}

# BSE-listed derivative underlyings. Kotak labels these NSEDERV too, so the
# exchange has to come from the underlying.
_BFO_UNDERLYINGS = {"SENSEX", "BANKEX", "SENSEX50"}

_OPTION_NAME = re.compile(
    r"^OPT(?:IDX|STK)\s*(?P<underlying>[A-Z0-9&\-]+?)\s+"
    r"(?P<day>\d{2})(?P<month>[A-Z]{3})(?P<year>\d{4})(?P<right>CE|PE)\s+"
    r"(?P<strike>\d+(?:\.\d+)?)$"
)


def normalize_header(header):
    return (header or "").strip().lower().replace(" ", "_").replace("-", "_")


def is_kotak_statement(fieldnames):
    """True when the CSV header row is a Kotak Transaction Statement."""
    return _SIGNATURE <= {normalize_header(h) for h in (fieldnames or [])}


def normalize_company_name(name):
    """Comparable form of a company name: 'Cyient Ltd' and the symbol
    master's 'CYIENT LIMITED' (or 'ENGINEERS INDIA LTD.') compare equal."""
    text = re.sub(r"[.,]", "", (name or "").upper())
    text = re.sub(r"\bLIMITED\b", "LTD", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_option_name(security_name):
    """``'OPTIDXNIFTY     06OCT2026CE  22850.00'`` -> (symbol, exchange), e.g.
    ``('NIFTY06OCT2622850CE', 'NFO')``; None if it is not an option contract.
    """
    match = _OPTION_NAME.match(re.sub(r"\s+", " ", (security_name or "").strip().upper()))
    if not match:
        return None
    strike = float(match["strike"])
    strike_text = str(int(strike)) if strike.is_integer() else f"{strike:g}"
    underlying = match["underlying"]
    symbol = f"{underlying}{match['day']}{match['month']}{match['year'][2:]}{strike_text}{match['right']}"
    return symbol, ("BFO" if underlying in _BFO_UNDERLYINGS else "NFO")


def parse_trade_datetime(trade_date, trade_time):
    """``'30/09/2026'`` + ``'15:13:35'`` -> ``'2026-09-30T15:13:35'`` (the ISO
    form the importer's timestamp parser reads), or None when malformed."""
    try:
        day = datetime.strptime((trade_date or "").strip(), "%d/%m/%Y")
        clock = datetime.strptime((trade_time or "").strip(), "%H:%M:%S")
    except ValueError:
        return None
    return day.replace(hour=clock.hour, minute=clock.minute, second=clock.second).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )


def normalize_statement_row(raw_row, resolve_equity):
    """Map one statement row onto the importer's common row shape.

    ``resolve_equity(company_name, exchange)`` returns a trading symbol or
    None. Returns ``(row, None)`` on success or ``(None, reason)`` where
    reason is one of: ``bad_date``, ``bad_number``, ``unsupported_instrument``,
    ``unresolved_symbol``, ``bad_action``.
    """
    row = {normalize_header(key): (value or "").strip() for key, value in raw_row.items()}

    timestamp = parse_trade_datetime(row.get("trade_date"), row.get("trade_time"))
    if timestamp is None:
        return None, "bad_date"

    action = row.get("transaction_type", "").upper()
    if action not in ("BUY", "SELL"):
        return None, "bad_action"

    try:
        quantity = float(row["quantity"])
        price = float(row["market_rate"])
    except (KeyError, ValueError):
        return None, "bad_number"
    if quantity <= 0 or price <= 0:
        return None, "bad_number"

    exchange_label = row.get("exchange", "").upper()
    security_name = row.get("security_name", "")

    if exchange_label == "NSEDERV":
        parsed = parse_option_name(security_name)
        if parsed is None:
            return None, "unsupported_instrument"
        symbol, exchange = parsed
        segment = "fno"
    elif exchange_label in ("NSE", "BSE"):
        symbol = resolve_equity(security_name, exchange_label)
        if not symbol:
            return None, "unresolved_symbol"
        exchange, segment = exchange_label, "equity"
    else:
        return None, "unsupported_instrument"

    return (
        {
            "symbol": symbol,
            "exchange": exchange,
            "action": action,
            "quantity": quantity,
            "average_price": price,
            "trade_timestamp": timestamp,
            "segment": segment,
        },
        None,
    )
