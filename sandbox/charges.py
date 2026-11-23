# sandbox/charges.py
"""Brokerage and statutory charges for one sandbox fill.

This module performs no I/O of any kind: no database, no market data, no clock
and no logging. Every input arrives as an argument and the result leaves as a
return value, so the arithmetic can be tested without a running platform and is
the same wherever it is called from (the execution engine, the settings page's
calculator, the transaction cost report).

What a fill is charged
----------------------
Brokerage is the trader's own plan, read from the sandbox configuration and
passed in. Each segment has two numbers, a flat amount per executed order and a
percentage of the trade value:

* both set: whichever is lower (the usual discount-broker plan)
* only the flat amount set: that amount per order
* only the percentage set: that share of the trade value
* neither set: no brokerage

The statutory part is not configurable. It is the schedule the exchanges and
the government publish, the same at every broker, and the one a broker's
published brokerage calculator applies:

* STT (CTT on commodities), on the side the law names
* exchange transaction charges, per exchange. The NSE rates include the
  Investor Protection Fund Trust levy, which is how a contract note bills them
* SEBI turnover fees
* stamp duty, on the buy side only
* GST on brokerage, exchange transaction charges and SEBI fees

Rounding
--------
As a contract note prints it: STT (or CTT) and stamp duty to the nearest rupee,
every other line to the paisa, and GST on the brokerage, exchange and SEBI
lines as printed. The total is the sum of the lines, so it never disagrees
with them.

A fill is charged as a contract note for that one trade (compute_charges). The
calculator prices a buy and a sell together, as one note for the two
(estimate_round_trip): each line is worked on the combined value and rounded
once, which is what a published brokerage calculator does, and its figures are
the ones a trader checks this against. The two can differ by a paisa on a
line, and by a rupee on delivery STT, because two rounded halves do not always
add up to the rounded whole.

An earlier version rounded every line to the paisa on each fill. An option buy
then paid 1.20 of stamp duty where the published calculator shows 1, and a
trader comparing the two saw a calculator that "did not match".

What is not modelled
--------------------
* Depository (DP) charges on a delivery sell.
* STT on an option that is exercised at expiry. Expiry settlement closes the
  position without an order, so it carries no charges at all.
* A delivery buy and sell on the same day is charged as two delivery trades.
  An exchange nets them and bills intraday rates.
* Agricultural commodities (lower SEBI fee, no CTT on futures) and NCDEX's own
  slab rates. NCDEX trades use the MCX non-agricultural rates.
* BSE scrip groups other than the standard rate.
* Crypto is charged nothing by default. Every crypto value is zero until the
  trader enters a venue's fee, and nothing is added on top of that fee. A
  crypto venue prices differently from an Indian exchange (maker and taker
  rates, fees on notional), so none of the schedule above is applied to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

PAISA = Decimal("0.01")
RUPEE = Decimal("1")
ZERO = Decimal("0.00")
_HUNDRED = Decimal("100")

#: The date the statutory schedule below was last checked against the published
#: rates. Shown on the settings page so a trader can tell how current it is.
STATUTORY_SCHEDULE_AS_OF = "2026-11-23"

#: The one switch that turns every charge off. Stored as "true" or "false".
CHARGES_ENABLED_KEY = "charges_enabled"

#: The most a trader may enter for each brokerage field. These are guards
#: against a slip of the keyboard (20 typed into the percentage box would take
#: a fifth of every trade), not limits a broker observes.
MAX_BROKERAGE_FLAT = Decimal("1000")
MAX_BROKERAGE_PERCENT = Decimal("5")

#: The two markets the rate card is split into. A trader is on one or the
#: other: a broker for the Indian exchanges trades the Indian segments, a
#: crypto venue trades the crypto ones, and a page shows the segments of the
#: logged-in broker's market and never both. They are priced differently (a
#: schedule of statutory charges on one side, a venue fee and nothing else on
#: the other), so a calculator that offered both would be offering a trader a
#: market the account cannot trade.
MARKET_INDIAN = "indian"
MARKET_CRYPTO = "crypto"
MARKETS = (MARKET_INDIAN, MARKET_CRYPTO)


@dataclass(frozen=True)
class Segment:
    """One row of the rate card.

    Every rate is a percentage of the trade value, written as the published
    figure (0.025 means 0.025 percent).

    Attributes:
        key: Stable identifier, used in configuration keys and API payloads.
        label: What a trader calls the segment.
        group: The heading the settings page files it under.
        applies_to: Which orders fall in the segment, in a trader's words.
        default_flat: Default brokerage per executed order.
        default_percent: Default brokerage as a percentage of trade value.
        stt_buy: STT or CTT on a buy.
        stt_sell: STT or CTT on a sell.
        stt_label: "STT", "CTT", or empty when neither applies.
        stamp_buy: Stamp duty on a buy. A sell pays none.
        sebi: SEBI turnover fee.
        gst: GST on brokerage, exchange transaction charges and SEBI fees.
        exchange_txn: Exchange transaction charge by exchange code, including
            any Investor Protection Fund Trust levy.
        ipft: The part of exchange_txn that is the Investor Protection Fund
            Trust levy, by exchange code. It is not charged again: it is
            listed so a breakdown can show the levy on its own line.
        market: MARKET_INDIAN or MARKET_CRYPTO. Which rate card the segment
            is part of, and so which brokers are shown it.
    """

    key: str
    label: str
    group: str
    applies_to: str
    default_flat: Decimal
    default_percent: Decimal
    stt_buy: Decimal = ZERO
    stt_sell: Decimal = ZERO
    stt_label: str = ""
    stamp_buy: Decimal = ZERO
    sebi: Decimal = ZERO
    gst: Decimal = Decimal("18")
    exchange_txn: dict[str, Decimal] = field(default_factory=dict)
    ipft: dict[str, Decimal] = field(default_factory=dict)
    market: str = MARKET_INDIAN


def _d(value: str) -> Decimal:
    return Decimal(value)


#: Rs 10 per crore of turnover.
_SEBI = _d("0.0001")

SEGMENTS: tuple[Segment, ...] = (
    Segment(
        key="equity_delivery",
        label="Equity Delivery",
        group="Equity",
        applies_to="CNC orders on NSE and BSE",
        default_flat=_d("20"),
        default_percent=_d("2.5"),
        stt_buy=_d("0.1"),
        stt_sell=_d("0.1"),
        stt_label="STT",
        stamp_buy=_d("0.015"),
        sebi=_SEBI,
        exchange_txn={"NSE": _d("0.00307"), "BSE": _d("0.00375")},
        ipft={"NSE": _d("0.0001")},
    ),
    Segment(
        key="equity_intraday",
        label="Equity Intraday",
        group="Equity",
        applies_to="MIS orders on NSE and BSE",
        default_flat=_d("20"),
        default_percent=_d("0.1"),
        stt_sell=_d("0.025"),
        stt_label="STT",
        stamp_buy=_d("0.003"),
        sebi=_SEBI,
        exchange_txn={"NSE": _d("0.00307"), "BSE": _d("0.00375")},
        ipft={"NSE": _d("0.0001")},
    ),
    Segment(
        key="fno_futures",
        label="F&O Futures",
        group="Equity F&O",
        applies_to="Futures on NFO and BFO",
        default_flat=_d("20"),
        default_percent=_d("0.03"),
        stt_sell=_d("0.05"),
        stt_label="STT",
        stamp_buy=_d("0.002"),
        sebi=_SEBI,
        exchange_txn={"NFO": _d("0.00183"), "BFO": _d("0")},
        ipft={"NFO": _d("0.0001")},
    ),
    Segment(
        key="fno_options",
        label="F&O Options",
        group="Equity F&O",
        applies_to="Options on NFO and BFO, charged on the premium",
        default_flat=_d("20"),
        default_percent=_d("0"),
        stt_sell=_d("0.15"),
        stt_label="STT",
        stamp_buy=_d("0.003"),
        sebi=_SEBI,
        exchange_txn={"NFO": _d("0.03553"), "BFO": _d("0.0325")},
        ipft={"NFO": _d("0.0005")},
    ),
    Segment(
        key="currency_futures",
        label="Currency Futures",
        group="Currency",
        applies_to="Futures on CDS and BCD",
        default_flat=_d("20"),
        default_percent=_d("0.03"),
        stamp_buy=_d("0.0001"),
        sebi=_SEBI,
        # CDS: 0.00035 plus the 0.00005 Investor Protection Fund Trust levy.
        exchange_txn={"CDS": _d("0.0004"), "BCD": _d("0.00045")},
        ipft={"CDS": _d("0.00005")},
    ),
    Segment(
        key="currency_options",
        label="Currency Options",
        group="Currency",
        applies_to="Options on CDS and BCD, charged on the premium",
        default_flat=_d("20"),
        default_percent=_d("0"),
        stamp_buy=_d("0.0001"),
        sebi=_SEBI,
        # CDS: 0.0311 plus the 0.002 Investor Protection Fund Trust levy.
        exchange_txn={"CDS": _d("0.0331"), "BCD": _d("0.001")},
        ipft={"CDS": _d("0.002")},
    ),
    Segment(
        key="commodity_futures",
        label="Commodity Futures",
        group="Commodity",
        applies_to="Futures on MCX, NCDEX and NCO",
        default_flat=_d("20"),
        default_percent=_d("0.03"),
        stt_sell=_d("0.01"),
        stt_label="CTT",
        stamp_buy=_d("0.002"),
        sebi=_SEBI,
        exchange_txn={"MCX": _d("0.0021"), "NCDEX": _d("0.0021"), "NCO": _d("0.0001")},
    ),
    Segment(
        key="commodity_options",
        label="Commodity Options",
        group="Commodity",
        applies_to="Options on MCX, NCDEX and NCO, charged on the premium",
        default_flat=_d("20"),
        default_percent=_d("0"),
        stt_sell=_d("0.05"),
        stt_label="CTT",
        stamp_buy=_d("0.003"),
        sebi=_SEBI,
        exchange_txn={"MCX": _d("0.0418"), "NCDEX": _d("0.0418"), "NCO": _d("0.001")},
    ),
    Segment(
        key="crypto_futures",
        label="Crypto Futures and Spot",
        group="Crypto",
        applies_to="Perpetuals, dated futures and spot on CRYPTO",
        default_flat=_d("0"),
        default_percent=_d("0"),
        gst=_d("0"),
        market=MARKET_CRYPTO,
    ),
    Segment(
        key="crypto_options",
        label="Crypto Options",
        group="Crypto",
        applies_to="Options on CRYPTO, charged on the premium",
        default_flat=_d("0"),
        default_percent=_d("0"),
        gst=_d("0"),
        market=MARKET_CRYPTO,
    ),
)

SEGMENTS_BY_KEY: dict[str, Segment] = {segment.key: segment for segment in SEGMENTS}


def market_for_broker_type(broker_type) -> str:
    """The market a broker of this type trades.

    ``broker_type`` is what a broker plugin declares about itself: "crypto"
    for a crypto venue, "IN_stock" for a broker on the Indian exchanges. Only
    the first is the crypto market. Everything else, an unknown or missing
    type included, is the Indian market, which is what every install traded
    before crypto was offered.
    """
    return MARKET_CRYPTO if str(broker_type or "").strip().lower() == "crypto" else MARKET_INDIAN


def exchanges_of(segment: Segment) -> tuple[str, ...]:
    """The exchanges a segment trades on, the main one first.

    The order is the order the rate card is written in (NSE before BSE, NFO
    before BFO, CDS before BCD, MCX first), and the first is the one a
    calculator opens on. It is handed out as a list because the order is lost
    the moment the rates travel as a JSON object: the server sorts an object's
    keys, which put BSE and BFO first, and every card opened on the exchange
    fewer traders use and showed a different exchange transaction charge from
    the one they expected. A crypto segment has no exchange rate and trades on
    CRYPTO.
    """
    return tuple(segment.exchange_txn) or ("CRYPTO",)


def segments_for(market=None) -> tuple[Segment, ...]:
    """The segments of one market, in rate-card order. Every segment when none is named."""
    if market is None:
        return SEGMENTS
    return tuple(segment for segment in SEGMENTS if segment.market == market)


_EQUITY_EXCHANGES = frozenset({"NSE", "BSE"})
_FNO_EXCHANGES = frozenset({"NFO", "BFO"})
_CURRENCY_EXCHANGES = frozenset({"CDS", "BCD"})
_COMMODITY_EXCHANGES = frozenset({"MCX", "NCDEX", "NCO"})
_CRYPTO_EXCHANGES = frozenset({"CRYPTO"})


@dataclass(frozen=True)
class Charges:
    """What one fill or one round trip costs, each line as a contract note prints it."""

    brokerage: Decimal = ZERO
    stt: Decimal = ZERO
    exchange_charges: Decimal = ZERO
    sebi_charges: Decimal = ZERO
    stamp_duty: Decimal = ZERO
    gst: Decimal = ZERO

    @property
    def total(self) -> Decimal:
        return (
            self.brokerage
            + self.stt
            + self.exchange_charges
            + self.sebi_charges
            + self.stamp_duty
            + self.gst
        )

    def as_columns(self) -> dict[str, Decimal]:
        """The values under the column names sandbox_trades stores them in."""
        return {
            "brokerage": self.brokerage,
            "stt": self.stt,
            "exchange_charges": self.exchange_charges,
            "sebi_charges": self.sebi_charges,
            "stamp_duty": self.stamp_duty,
            "gst": self.gst,
            "total_charges": self.total,
        }

    def __add__(self, other: Charges) -> Charges:
        return Charges(
            brokerage=self.brokerage + other.brokerage,
            stt=self.stt + other.stt,
            exchange_charges=self.exchange_charges + other.exchange_charges,
            sebi_charges=self.sebi_charges + other.sebi_charges,
            stamp_duty=self.stamp_duty + other.stamp_duty,
            gst=self.gst + other.gst,
        )


NO_CHARGES = Charges()

#: The charge columns of sandbox_trades, in the order reports list them.
CHARGE_COLUMNS: tuple[str, ...] = (
    "brokerage",
    "stt",
    "exchange_charges",
    "sebi_charges",
    "stamp_duty",
    "gst",
    "total_charges",
)


def paisa(value: Decimal) -> Decimal:
    """Round to two places, halves away from zero, as a contract note prints."""
    return value.quantize(PAISA, rounding=ROUND_HALF_UP)


def rupee(value: Decimal) -> Decimal:
    """Round to the nearest rupee, as a contract note prints STT and stamp duty.

    To the paisa first and then to the rupee, halves up both times, so 0.4995
    is 0.50 and then 1: that is the order a published calculator rounds in,
    and rounding once would give 0.
    """
    return paisa(value).quantize(RUPEE, rounding=ROUND_HALF_UP).quantize(PAISA)


def classify_segment(exchange: str, product: str, symbol: str) -> str | None:
    """The rate-card segment an order belongs to.

    Decided by the exchange first, so an equity symbol that happens to end in
    CE or PE (RELIANCE does) is never read as an option.

    Args:
        exchange: OpenAlgo exchange code.
        product: CNC, MIS or NRML.
        symbol: OpenAlgo symbol.

    Returns:
        A key of SEGMENTS_BY_KEY, or None for an exchange nothing is charged
        on (the index exchanges, which cannot be traded).
    """
    exchange = (exchange or "").upper()
    symbol = (symbol or "").upper()
    product = (product or "").upper()

    if exchange in _EQUITY_EXCHANGES:
        return "equity_intraday" if product == "MIS" else "equity_delivery"

    is_option = symbol.endswith("CE") or symbol.endswith("PE")
    if exchange in _FNO_EXCHANGES:
        return "fno_options" if is_option else "fno_futures"
    if exchange in _CURRENCY_EXCHANGES:
        return "currency_options" if is_option else "currency_futures"
    if exchange in _COMMODITY_EXCHANGES:
        return "commodity_options" if is_option else "commodity_futures"
    if exchange in _CRYPTO_EXCHANGES:
        return "crypto_options" if is_option else "crypto_futures"
    return None


def brokerage_for(trade_value: Decimal, flat: Decimal, percent: Decimal) -> Decimal:
    """Brokerage on one executed order, unrounded.

    Args:
        trade_value: Price times quantity (times the contract value, if any).
        flat: Amount per executed order; zero or less means not set.
        percent: Percentage of trade value; zero or less means not set.

    Returns:
        The lower of the two when both are set, the one that is set when only
        one is, and zero when neither is.
    """
    if trade_value <= 0:
        return ZERO
    by_percent = trade_value * percent / _HUNDRED
    if flat > 0 and percent > 0:
        return min(flat, by_percent)
    if flat > 0:
        return flat
    if percent > 0:
        return by_percent
    return ZERO


def compute_charges(
    segment_key: str | None,
    exchange: str,
    action: str,
    trade_value: Decimal,
    flat: Decimal,
    percent: Decimal,
) -> Charges:
    """Everything one fill is charged.

    Args:
        segment_key: From classify_segment. None or an unknown key charges
            nothing.
        exchange: OpenAlgo exchange code, which picks the transaction charge.
        action: BUY or SELL.
        trade_value: Price times quantity (times the contract value, if any).
        flat: The trader's brokerage per executed order for this segment.
        percent: The trader's brokerage percentage for this segment.

    Returns:
        The charges as a contract note for this one trade prints them: STT and
        stamp duty to the nearest rupee, the other lines to the paisa. GST is
        worked out on the rounded brokerage, exchange and SEBI figures, so the
        GST line is always 18 percent of the lines printed above it.
    """
    segment = SEGMENTS_BY_KEY.get(segment_key or "")
    if segment is None or trade_value <= 0:
        return NO_CHARGES

    is_buy = (action or "").upper() == "BUY"
    brokerage = paisa(brokerage_for(trade_value, flat, percent))
    return _contract_note(
        segment,
        exchange,
        buy_value=trade_value if is_buy else ZERO,
        sell_value=ZERO if is_buy else trade_value,
        brokerage=brokerage,
    )


def _contract_note(
    segment: Segment,
    exchange: str,
    buy_value: Decimal,
    sell_value: Decimal,
    brokerage: Decimal,
) -> Charges:
    """The lines of one contract note for a bought value and a sold value.

    Either value may be zero, which is one fill. Both set is a buy and a sell
    billed together. Every line is worked on what it applies to (STT on the
    side the law names, stamp duty on the buy, the turnover lines on both) and
    rounded once.
    """
    exchange = (exchange or "").upper()
    turnover = buy_value + sell_value

    def of(value: Decimal, rate: Decimal) -> Decimal:
        return value * rate / _HUNDRED

    # The exchange's own charge and its Investor Protection Fund Trust levy are
    # two amounts on a contract note, each rounded on its own, and the line a
    # trader sees is their sum. Rounding the combined rate once is a paisa out
    # about one time in five (6,670 of NSE equity turnover is 0.20 plus 0.01,
    # and 0.20 if the two rates are added first).
    rate = segment.exchange_txn.get(exchange, ZERO)
    levy_rate = segment.ipft.get(exchange, ZERO)
    exchange_charges = paisa(of(turnover, rate - levy_rate)) + paisa(of(turnover, levy_rate))
    sebi_charges = paisa(of(turnover, segment.sebi))
    # STT goes to the nearest rupee. CTT, the same tax on commodities, is kept
    # to the paisa: that is how a published brokerage calculator shows the two,
    # and its lines are what a trader holds these against.
    transaction_tax = of(buy_value, segment.stt_buy) + of(sell_value, segment.stt_sell)
    stt = paisa(transaction_tax) if segment.stt_label == "CTT" else rupee(transaction_tax)
    return Charges(
        brokerage=brokerage,
        stt=stt,
        exchange_charges=exchange_charges,
        sebi_charges=sebi_charges,
        stamp_duty=rupee(of(buy_value, segment.stamp_buy)),
        gst=paisa((brokerage + exchange_charges + sebi_charges) * segment.gst / _HUNDRED),
    )


def split_exchange_charges(
    segment_key: str | None, exchange: str, trade_value: Decimal, exchange_charges: Decimal
) -> tuple[Decimal, Decimal]:
    """Split a fill's exchange charges into the transaction charge and the levy.

    The fill is charged one figure, rounded once (compute_charges). This only
    says how much of that figure is the Investor Protection Fund Trust levy,
    for a breakdown that lists the two apart. The parts always add back to the
    figure that was charged.

    Args:
        segment_key: From classify_segment.
        exchange: OpenAlgo exchange code.
        trade_value: The value the charges were worked out on.
        exchange_charges: Charges.exchange_charges for that fill.

    Returns:
        ``(transaction, ipft)``, both rounded to the paisa.
    """
    segment = SEGMENTS_BY_KEY.get(segment_key or "")
    if segment is None:
        return exchange_charges, ZERO
    rate = segment.ipft.get((exchange or "").upper(), ZERO)
    ipft = min(paisa(trade_value * rate / _HUNDRED), exchange_charges)
    return exchange_charges - ipft, ipft


# ---------------------------------------------------------------------------
# Configuration: key names, defaults and validation. Still no I/O; the caller
# reads and writes the sandbox_config table.
# ---------------------------------------------------------------------------


def brokerage_flat_key(segment_key: str) -> str:
    return f"brokerage_{segment_key}_flat"


def brokerage_percent_key(segment_key: str) -> str:
    return f"brokerage_{segment_key}_percent"


def plain(value: Decimal) -> str:
    """A Decimal as a trader would type it: no exponent, no trailing zeros."""
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


def describe_brokerage(flat: Decimal, percent: Decimal) -> str:
    """The plan in one sentence, as a broker's pricing page would word it."""
    if flat > 0 and percent > 0:
        return (
            f"{plain(flat)} per executed order or {plain(percent)}% of the trade value, "
            "whichever is lower"
        )
    if flat > 0:
        return f"{plain(flat)} per executed order"
    if percent > 0:
        return f"{plain(percent)}% of the trade value"
    return "No brokerage"


def default_config_rows() -> list[dict[str, str]]:
    """Every charge setting with its default, in the shape sandbox_config holds.

    One source for the seed at startup, the migration script and both resets,
    so none of them can ship a default the others do not.
    """
    rows = [
        {
            "config_key": CHARGES_ENABLED_KEY,
            "config_value": "true",
            "description": (
                "Charge brokerage and statutory charges on sandbox trades (true or false)"
            ),
        }
    ]
    for segment in SEGMENTS:
        rows.append(
            {
                "config_key": brokerage_flat_key(segment.key),
                "config_value": plain(segment.default_flat),
                "description": (
                    f"{segment.label} brokerage per executed order (0 = not used). "
                    f"Range: 0-{plain(MAX_BROKERAGE_FLAT)}"
                ),
            }
        )
        rows.append(
            {
                "config_key": brokerage_percent_key(segment.key),
                "config_value": plain(segment.default_percent),
                "description": (
                    f"{segment.label} brokerage as a percentage of trade value "
                    f"(0 = not used). Range: 0-{plain(MAX_BROKERAGE_PERCENT)}"
                ),
            }
        )
    return rows


def default_config_values() -> dict[str, str]:
    """default_config_rows as a key to value mapping."""
    return {row["config_key"]: row["config_value"] for row in default_config_rows()}


def config_keys() -> tuple[str, ...]:
    """Every sandbox_config key this module owns."""
    return tuple(row["config_key"] for row in default_config_rows())


def to_decimal(value, default: Decimal = ZERO) -> Decimal:
    """Read a stored or submitted number, falling back when it is not one."""
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return default
    return number if number.is_finite() else default


def is_enabled(value) -> bool:
    """Whether a stored charges_enabled value means on. Anything unclear is on,
    so a damaged setting never silently makes every trade free."""
    return str(value).strip().lower() not in ("false", "0", "no", "off")


def validate_brokerage(segment_key: str, flat, percent) -> tuple[Decimal, Decimal, str | None]:
    """Check one segment's brokerage as a trader submitted it.

    Returns:
        ``(flat, percent, error)``. ``error`` is a sentence for the trader, or
        None when both values are acceptable.
    """
    segment = SEGMENTS_BY_KEY.get(segment_key)
    if segment is None:
        return ZERO, ZERO, "That segment is not on the rate card."

    def parse(value, what):
        try:
            number = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, AttributeError):
            return None, f"{segment.label}: enter a number for the {what}."
        if not number.is_finite():
            return None, f"{segment.label}: enter a number for the {what}."
        return number, None

    flat_value, error = parse(flat, "amount per order")
    if error:
        return ZERO, ZERO, error
    percent_value, error = parse(percent, "percentage")
    if error:
        return ZERO, ZERO, error

    if flat_value < 0 or percent_value < 0:
        return ZERO, ZERO, f"{segment.label}: brokerage cannot be negative."
    if flat_value > MAX_BROKERAGE_FLAT:
        return (
            ZERO,
            ZERO,
            f"{segment.label}: the amount per order cannot be more than "
            f"{plain(MAX_BROKERAGE_FLAT)}.",
        )
    if percent_value > MAX_BROKERAGE_PERCENT:
        return (
            ZERO,
            ZERO,
            f"{segment.label}: the percentage cannot be more than "
            f"{plain(MAX_BROKERAGE_PERCENT)}. Enter 0.03 for 0.03%, not 3.",
        )
    return flat_value, percent_value, None


def validate_config_value(config_key: str, config_value) -> str | None:
    """Check a value written to one of this module's keys on its own.

    The settings page saves the whole plan through validate_brokerage. This is
    for the sandbox's general one-key update, so that route cannot store a
    value the calculation would have to guess at.

    Returns:
        A sentence for the trader, or None when the value is acceptable or the
        key is not one of this module's.
    """
    if config_key == CHARGES_ENABLED_KEY:
        if str(config_value).strip().lower() not in ("true", "false"):
            return "Charges can only be switched on (true) or off (false)."
        return None
    for segment in SEGMENTS:
        if config_key == brokerage_flat_key(segment.key):
            _flat, _percent, error = validate_brokerage(segment.key, config_value, "0")
            return error
        if config_key == brokerage_percent_key(segment.key):
            _flat, _percent, error = validate_brokerage(segment.key, "0", config_value)
            return error
    return None


def estimate_round_trip(
    segment_key: str,
    exchange: str,
    buy_price: Decimal,
    sell_price: Decimal,
    quantity: Decimal,
    flat: Decimal,
    percent: Decimal,
) -> dict:
    """A buy and a sell of the same quantity, as a brokerage calculator shows it.

    Priced as one contract note for the two orders: brokerage on each order,
    and every other line on the combined value, rounded once. That is how a
    published brokerage calculator works a round trip, so the lines here are
    the lines it shows. The two fills, each charged on its own when it
    happens, can come to a paisa more or less on a line.

    Returns:
        The charges, the turnover, the gross and net profit, and the price
        move that covers the charges.
    """
    buy_value = buy_price * quantity
    sell_value = sell_price * quantity
    segment = SEGMENTS_BY_KEY.get(segment_key or "")
    if segment is None or buy_value <= 0 or sell_value <= 0:
        total = NO_CHARGES
    else:
        brokerage = paisa(
            brokerage_for(buy_value, flat, percent) + brokerage_for(sell_value, flat, percent)
        )
        total = _contract_note(segment, exchange, buy_value, sell_value, brokerage)
    gross = sell_value - buy_value
    breakeven = paisa(total.total / quantity) if quantity > 0 else ZERO
    return {
        "turnover": paisa(buy_value + sell_value),
        "total": total,
        "gross_pnl": paisa(gross),
        "net_pnl": paisa(gross - total.total),
        "points_to_breakeven": breakeven,
    }
