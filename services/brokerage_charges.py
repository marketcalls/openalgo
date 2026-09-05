"""services/brokerage_charges.py

Estimates per-trade broker charges for Fyers, Zerodha, Dhan and Groww from the
data-driven tariff table ``data/broker_charges_comparison.csv``.

Pure module, mirroring the services/risk convention: no I/O at import, no Flask,
no logging. Every input arrives as an argument and every charge leaves as a
return value, so the estimation can be unit-tested, called from a green thread
or a real one, and served under HTTP without a service layer.

The versioned CSV is the source of truth for the estimator's tariff rules.
"""

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CHARGES_CSV = Path(__file__).resolve().parents[1] / "data" / "broker_charges_comparison.csv"

# Broker plugin keys allowed to see brokerage estimates.
SUPPORTED_BROKERS = ("fyers", "zerodha", "dhan", "groww")
_BROKER_LABELS = {"fyers": "Fyers", "zerodha": "Zerodha", "dhan": "Dhan", "groww": "Groww"}

# Exchanges whose instruments are derivatives (turnover scales by lot size).
FNO_EXCHANGES = {"NFO", "BFO", "CDS", "BCD", "MCX", "NCDEX", "NCO"}

# The exchange whose txn-charge rows apply for a given exchange code.
_TXN_EXCHANGE = {
    "NFO": "NSE",
    "BFO": "BSE",
    "CDS": "NSE",
    "BCD": "BSE",
    "MCX": "MCX",
    "NCDEX": "NCDEX",
}


@dataclass(frozen=True)
class Rule:
    """One parsed tariff row."""

    kind: str  # zero | flat | flat_or_pct | flat_or_pct_max | pct | per_crore | dp | gst
    value: float  # percentage, flat amount, per-crore ratio, or GST percent
    cap: float = 0.0  # flat companion for flat_or_pct / flat_or_pct_max
    side: str = "BOTH"  # BUY | SELL | BOTH
    gst: bool = False  # add GST on top of a fixed charge (delivery DP)


_FIRST_NUM = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)")
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_OR_ALT = re.compile(r"(\d+(?:\.\d+)?)\s*(%?)\s+or\s+(\d+(?:\.\d+)?)\s*(%?)")


def _first_num(text: str) -> float:
    m = _FIRST_NUM.search(text)
    return float(m.group(1)) if m else 0.0


def _parse_rule(charge_type: str, value: str) -> Rule:
    """Parse one CSV tariff row into a Rule, returning kind='skip' for rows the
    estimator does not use (segment tariffs, AMC, demo charges, etc.)."""
    low = value.strip().lower()
    ct = charge_type.strip().lower()

    if ct == "gst":
        m = _PCT.search(low)
        return Rule("gst", float(m.group(1)) if m else 0.0)

    if low in ("zero", "0", "0%"):
        return Rule("zero", 0.0)

    # "20 or 0.3% per order (whichever lower)" and "0.03% or 20/order (whichever lower)"
    if "or " in low and "%" in low and ("whichever lower" in low or "whichever higher" in low):
        m = _OR_ALT.search(low)
        if m:
            first, first_pct, second = m.group(1), m.group(2), m.group(3)
            if first_pct == "%":
                pct, flat = float(first), float(second)
            else:
                flat, pct = float(first), float(second)
            # A "/crore" flat companion is just another way of writing the same
            # percentage (1500/crore == 0.015%); keep the percent only.
            if "/crore" not in low:
                kind = "flat_or_pct" if "whichever lower" in low else "flat_or_pct_max"
                return Rule(kind, pct, cap=flat)

    # Pure percentage rows: STT, txn charges, GST base notes, clearing, SEBI as %.
    if "%" in low:
        m = _PCT.search(low)
        pct = float(m.group(1)) if m else 0.0
        if "buy and sell" in low:
            side = "BOTH"
        elif re.search(r"\bon sell", low):
            side = "SELL"
        elif re.search(r"\bon buy", low):
            side = "BUY"
        else:
            side = "BOTH"
        return Rule("pct", pct, side=side)

    if "per crore" in low:
        # "10 per Crore" or "0.01 per Crore" (SEBI / IPFT).
        return Rule("per_crore", _first_num(low))

    if "flat" in low:
        # "Flat 20 per executed order".
        return Rule("flat", _first_num(low))

    # Delivery DP charges: "12.5 + GST per scrip", "15.34 per scrip (...+GST)",
    # "12.50 per instruction per ISIN + GST", "15 per scrip incl GST".
    # The Zerodha figure already includes GST (inside parentheses); Fyers and
    # Dhan add it on top. Decide by whether "+ GST" sits outside parentheses.
    if ("per scrip" in low or "per instruction" in low or "per isin" in low) and not low.startswith(
        "zero"
    ):
        outside_parens = re.sub(r"\([^)]*\)", "", low)
        gst_on_top = "+ gst" in outside_parens
        return Rule("dp", _first_num(low), side="SELL", gst=gst_on_top)

    # Bare fixed figures that are not per-scrip (e.g. "20 per order extra"). Zero is a skip.
    if re.match(r"\s?\d", low):
        return Rule("flat", _first_num(low))

    return Rule("skip", 0.0)


@dataclass
class _ChargeSet:
    brokerage: Rule | None = None
    stt: list = None
    exchange_txn: dict = None  # {"NSE": Rule, "BSE": Rule, ...}
    gst: Rule | None = None
    sebi: list = None
    ipft: list = None
    clearing: list = None
    stamp: list = None
    dp: Rule | None = None


def _empty_charge_set():
    return _ChargeSet(stt=[], exchange_txn={}, sebi=[], ipft=[], clearing=[], stamp=[])


# Segments where a resolved trade can land, plus aliases for brokers that name
# their equity F&O segments differently (Dhan: "Futures (Equity F&O)").
_STANDARD_SEGMENTS = ("Equity Delivery", "Equity Intraday", "Futures", "Options")
_SEGMENT_ALIAS_MAP = {
    "Futures (Equity F&O)": "Futures",
    "Options (Equity F&O)": "Options",
}

# Rows under these segments apply to every segment of the broker.
_GLOBAL_SEGMENTS = {"All Equity Segments", "DP Charges", "Demat Account"}


@lru_cache(maxsize=1)
def _load_charges() -> dict:
    """Parse the CSV into {broker_key: {segment: _ChargeSet}}. Cached forever."""
    tables: dict[str, dict[str, _ChargeSet]] = {}
    try:
        fh = open(CHARGES_CSV, encoding="utf-8-sig", newline="")
    except FileNotFoundError:
        # The tariff table ships with the repo; a deployment that predates it
        # gets an explicit client error here (the blueprint maps ValueError to
        # a 400) instead of a frontend-side HTTP 500 from a raw OSError, and
        # the lru_cache does not cache exceptions so a later git pull heals it.
        raise ValueError(
            f"Brokerage tariff table not found: {CHARGES_CSV}. "
            "Reinstall or update OpenAlgo so the charges file is present."
        ) from None
    with fh:
        for row in csv.DictReader(fh):
            broker = (row.get("Broker") or "").strip()
            segment = (row.get("Segment") or "").strip()
            charge_type = (row.get("Charge Type") or "").strip()
            value = (row.get("Value") or "").strip()
            ticker = broker.lower()
            if ticker not in SUPPORTED_BROKERS or not segment or not charge_type:
                continue

            ct = charge_type.lower()
            if ct == "brokerage":
                category = "brokerage"
            elif "gst" == ct:
                category = "gst"
            elif ct.startswith("stt") or "stt/ctt" in ct:
                category = "stt"
            elif "exchange txn" in ct:
                category = "exchange_txn"
            elif "sebi" in ct:
                category = "sebi"
            elif "ipft" in ct:
                category = "ipft"
            elif "clearing" in ct:
                category = "clearing"
            elif "stamp" in ct:
                category = "stamp"
            elif "debit" in ct or "dp transaction" in ct:
                category = "dp"
            else:
                continue  # AMC, account opening, pledging, delays, interest, ...

            rule = _parse_rule(charge_type, value)
            if rule.kind == "skip":
                continue

            # Rows under "All Equity Segments" (GST / SEBI / IPFT) or
            # "DP Charges" feed every segment; the DP result is gated later to
            # equity delivery sells anyway.
            if segment in _GLOBAL_SEGMENTS:
                targets = _STANDARD_SEGMENTS
            else:
                targets = (_SEGMENT_ALIAS_MAP.get(segment, segment),)

            table = tables.setdefault(ticker, {})
            for target in targets:
                charges = table.setdefault(target, _empty_charge_set())
                if category == "exchange_txn":
                    # "Exchange Txn Charges NSE" / "... BSE" / "... BSE Index".
                    charges.exchange_txn.setdefault("BSE" if "bse" in ct else "NSE", rule)
                elif category == "stt":
                    charges.stt.append(rule)
                elif category == "sebi":
                    charges.sebi.append(rule)
                elif category == "ipft":
                    charges.ipft.append(rule)
                elif category == "clearing":
                    charges.clearing.append(rule)
                elif category == "stamp":
                    charges.stamp.append(rule)
                elif category == "dp":
                    # The DP tariff is the sell-side debit row; Groww (and Fyers)
                    # also carry a zero buy-side row that must not overwrite it.
                    current = charges.dp
                    if current is None or current.kind == "zero" or current.value == 0:
                        charges.dp = rule
                else:
                    setattr(charges, category, rule)
    return tables


def _segment_rows(tables: dict, broker: str, segment: str) -> _ChargeSet:
    return tables.get(broker, {}).get(segment, _empty_charge_set())


def _resolve_side(payload_side: str) -> str:
    return "BUY" if str(payload_side).strip().upper() == "BUY" else "SELL"


def _is_derivative(exchange: str, symbol: str, instrumenttype: str | None) -> bool:
    """Derivative only when the exchange or an explicit instrument type says so.

    Never infer from a symbol suffix on NSE/BSE: "RELIANCE" ends in "CE" and
    "BAJFINANCE" ends in "CE" too - those are equities, not options."""
    if instrumenttype and instrumenttype.upper() in ("FUT", "FUTIDX", "CE", "PE"):
        return True
    if instrumenttype and instrumenttype.upper() in ("EQ", "EQUITY", "INDEX", "AMO"):
        return False
    return (exchange or "").upper() in FNO_EXCHANGES


def resolve_segment(exchange: str, product: str, symbol: str, instrumenttype: str | None) -> str:
    """Map an order context to a CSV segment label."""
    if _is_derivative(exchange, symbol, instrumenttype):
        if instrumenttype and instrumenttype.upper() in ("CE", "PE"):
            return "Options"
        if (symbol or "").upper().endswith(("CE", "PE")) and (
            exchange or ""
        ).upper() in FNO_EXCHANGES:
            return "Options"
        return "Futures"
    product_upper = (product or "").upper()
    if product_upper in ("CNC", "NRML") or product_upper.startswith("DELIVERY"):
        return "Equity Delivery"
    return "Equity Intraday"


def _charge_exchange(exchange: str) -> str:
    return _TXN_EXCHANGE.get((exchange or "").upper(), (exchange or "").upper())


def _rule_amount(rule: Rule, turnover: float, side: str) -> float:
    if rule.kind == "zero":
        return 0.0
    if rule.side != "BOTH" and rule.side != side:
        return 0.0
    if rule.kind == "flat":
        return rule.value
    if rule.kind == "flat_or_pct":
        return min(turnover * rule.value / 100.0, rule.cap)
    if rule.kind == "flat_or_pct_max":
        return max(turnover * rule.value / 100.0, rule.cap)
    if rule.kind == "pct":
        return turnover * rule.value / 100.0
    if rule.kind == "per_crore":
        return turnover * rule.value / 1e7
    if rule.kind == "dp":
        amount = rule.value
        if rule.gst:
            amount *= 1.18
        return amount
    return 0.0


def estimate_brokerage(
    *,
    broker: str,
    exchange: str,
    product: str,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
    instrumenttype: str | None = None,
    lot_size: float = 1,
) -> dict:
    """Estimate the charges on a single trade.

    Returns a dict with ``components`` (brokerage, stt, exchange_txn, sebi,
    ipft, clearing_charges, stamp_duty, dp_charges, gst), ``turnover`` and
    ``total``. Raises ValueError for unsupported brokers or trades.
    """
    ticker = str(broker).strip().lower()
    if ticker not in SUPPORTED_BROKERS:
        raise ValueError("Brokerage is supported only for Fyers, Zerodha, Dhan and Groww")

    qty = float(quantity)
    px = float(price)
    if qty <= 0 or px <= 0:
        raise ValueError("quantity and price must be positive")

    side = _resolve_side(side)
    exchange_upper = (exchange or "").upper()
    segment = resolve_segment(exchange_upper, product or "", symbol or "", instrumenttype)
    derivative = segment in ("Futures", "Options")
    lot = float(lot_size) if lot_size and lot_size > 0 else 1
    turnover = qty * px * (lot if derivative else 1)
    charge_exchange = _charge_exchange(exchange_upper)

    charges = _segment_rows(_load_charges(), ticker, segment)

    amounts = {
        "brokerage": 0.0,
        "stt": 0.0,
        "exchange_txn": 0.0,
        "sebi": 0.0,
        "ipft": 0.0,
        "clearing_charges": 0.0,
        "stamp_duty": 0.0,
        "dp_charges": 0.0,
    }

    if charges.brokerage:
        amounts["brokerage"] = _rule_amount(charges.brokerage, turnover, side)

    for rule in charges.stt:
        amounts["stt"] += _rule_amount(rule, turnover, side)

    txn_rules = charges.exchange_txn or {}
    txn_rule = txn_rules.get(charge_exchange) or txn_rules.get("NSE")
    if txn_rule:
        amounts["exchange_txn"] = _rule_amount(txn_rule, turnover, side)

    for rule in charges.sebi:
        amounts["sebi"] += _rule_amount(rule, turnover, side)

    for rule in charges.ipft:
        amounts["ipft"] += _rule_amount(rule, turnover, side)

    for rule in charges.clearing:
        amounts["clearing_charges"] += _rule_amount(rule, turnover, side)

    for rule in charges.stamp:
        amounts["stamp_duty"] += _rule_amount(rule, turnover, side)

    # Delivery DP applies to equity delivery sells only.
    if segment == "Equity Delivery" and side == "SELL" and charges.dp:
        amounts["dp_charges"] = _rule_amount(charges.dp, turnover, side)

    gst = 0.0
    if charges.gst:
        gst_base = (
            amounts["brokerage"]
            + amounts["exchange_txn"]
            + amounts["sebi"]
            + amounts["ipft"]
            + amounts["clearing_charges"]
        )
        gst = gst_base * charges.gst.value / 100.0
    amounts["gst"] = gst

    components = {key: round(value, 2) for key, value in amounts.items()}
    total = round(sum(components.values()), 2)

    notes = ["Estimated figures; actual charges levied by the broker may differ."]
    if derivative and lot == 1:
        notes.append(
            "Using contract size 1 - for derivatives pass the lot size for an exact turnover."
        )
    if charge_exchange != exchange_upper:
        notes.append(
            f"Charges estimated on the {charge_exchange} tariff for {exchange_upper} instruments."
        )

    return {
        "broker": _BROKER_LABELS[ticker],
        "segment": segment,
        "exchange": exchange_upper,
        "charge_exchange": charge_exchange,
        "side": side,
        "quantity": qty,
        "price": px,
        "lot_size": lot,
        "turnover": round(turnover, 2),
        "components": components,
        "total": total,
        "notes": notes,
    }
