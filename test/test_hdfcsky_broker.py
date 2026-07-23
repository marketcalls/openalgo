"""
Unit tests for the HDFC Sky broker integration.

Covers the two areas that fail silently rather than loudly:

1. Master-contract symbol construction -- especially symbols containing the
   characters that break naive parsing (BAJAJ-AUTO's hyphen, M&M's ampersand)
   and the three expiry-suffix shapes HDFC Sky uses (monthly, weekly with a
   month digit, weekly with the O/N/D month letter).
2. The protobuf tick parser -- a wrong field mapping produces plausible
   garbage rather than an exception, so every field is asserted against a
   synthetic packet built with known values.

Run with: python -m pytest test/test_hdfcsky_broker.py -v
"""

import pandas as pd
import pytest

# Import websocket_proxy first: the shared adapter registry imports every
# broker adapter, and a direct broker-first import trips a circular import.
import websocket_proxy  # noqa: F401
from broker.hdfcsky.database.master_contract_db import process_security_master
from broker.hdfcsky.mapping.exchange import from_ws_scrip_id, ws_scrip_id
from broker.hdfcsky.streaming import hdfcsky_market_pb2 as pb
from broker.hdfcsky.streaming.hdfcsky_websocket import HDFCSkyWebSocket

_CSV_COLUMNS = [
    "exchange_token",
    "trading_symbol",
    "company_name",
    "close_price",
    "expiry",
    "strike",
    "tick_size",
    "lot_size",
    "instrument_name",
    "option_type",
    "segment",
    "exchange",
    "fin_instrm_pdct_tp_cd",
    "asset_code",
    "settlement_type",
    "isin",
]

# Rows copied verbatim from the live Security Master (CompactScrip.csv).
_SECURITY_MASTER_ROWS = [
    # exchange_token, trading_symbol, company_name, close, expiry, strike,
    # tick, lot, instrument_name, option_type, segment, exchange
    ("16669", "BAJAJ-AUTO-EQ", "BAJAJ AUTO LIMITED", "8000", "", "0.0000", "0.5000", "1", "EQ", "", "EQ", "NSE"),
    ("2031", "M&M-EQ", "MAHINDRA & MAHINDRA LTD", "3000", "", "0.0000", "0.1000", "1", "EQ", "", "EQ", "NSE"),
    ("2885", "RELIANCE-EQ", "RELIANCE INDUSTRIES LTD", "1400", "", "0.0000", "0.1000", "1", "EQ", "", "EQ", "NSE"),
    # Same underlying on the NSE T+0 series: must NOT collapse onto BAJAJ-AUTO.
    ("23262", "BAJAJ-AUTO-T0", "BAJAJ AUTO LIMITED", "0", "", "0.0000", "0.5000", "1", "T0", "", "T0", "NSE"),
    # BSE cash carries the group as the suffix.
    ("500520", "M&M-A", "MAHINDRA & MAHINDRA LTD.", "3000", "", "0.0000", "0.0500", "1", "E", "", "A", "BSE"),
    ("532977", "BAJAJ-AUTO-A", "BAJAJ AUTO LTD.", "8000", "", "0.0000", "0.0500", "1", "E", "", "A", "BSE"),
    # Indices: display name on NSE, short code on BSE.
    ("26000", "Nifty 50", "", "24275.2", "", "0.0000", "0.0500", "0", "", "", "INDICES", "NSE"),
    ("26009", "Nifty Bank", "", "58239.2", "", "0.0000", "0.0500", "0", "", "", "INDICES", "NSE"),
    ("26074", "NIFTY MID SELECT", "", "14869.7", "", "0.0000", "0.0500", "0", "", "", "INDICES", "NSE"),
    ("1", "SENSEX", "SENSEX", "81700", "", "0.0000", "0.0100", "0", "", "", "IDX", "BSE"),
    ("47", "SNSX50", "SNSX50", "25000", "", "0.0000", "0.0100", "0", "", "", "IDX", "BSE"),
    # Derivatives -- monthly expiry suffix (YY + MMM).
    ("58072", "NIFTY26AUGFUT", "NIFTY", "24275.2", "25-Aug-2026", "-0.0100", "0.1000", "65", "FUTIDX", "XX", "XX", "NFO"),
    ("36092", "M&M26AUG4050PE", "M&M", "0", "25-Aug-2026", "4050.0000", "0.0500", "200", "OPTSTK", "PE", "XX", "NFO"),
    ("36093", "BAJAJ-AUTO26SEP14800CE", "BAJAJ-AUTO", "0", "29-Sep-2026", "14800.0000", "0.0500", "75", "OPTSTK", "CE", "XX", "NFO"),
    # Decimal strike must survive verbatim.
    ("820204", "FEDERALBNK26JUL262.5PE", "FEDERALBNK", "0.05", "30-Jul-2026", "262.5000", "0.0500", "2500", "SO", "PE", "SO", "BFO"),
    # Weekly expiry suffix (YY + month digit + DD).
    ("1146911", "SENSEX2681369500CE", "SENSEX", "9.15", "13-Aug-2026", "69500.0000", "0.0500", "20", "IO", "CE", "IO", "BFO"),
    # Weekly expiry suffix with the O/N/D month letter (Oct/Nov/Dec).
    ("6886", "EURINR26O01FUT", "EURINR26O01FUT", "0", "01-Oct-2026", "0.0000", "0.0025", "1", "FUTCUR", "XX", "XX", "CDS"),
    # MCX carries no company_name at all -- the underlying comes from the suffix strip.
    ("557563", "SILVER26AUG297000CE", "", "49.5", "28-Aug-2026", "297000.0000", "0.5000", "30", "OPTFUT", "CE", "XX", "MCX"),
    # Non-tradable MCX underlying-commodity row (sentinel expiry) must be dropped.
    ("384", "MESCRUDOIL", "", "0", "01-Jan-0001", "0.0000", "0.5000", "100", "COM", "", "XX", "MCX"),
]


@pytest.fixture(scope="module")
def instruments():
    """Run the real parser over a representative slice of the live master."""
    frame = pd.DataFrame(
        [list(row) + ["", "", "", ""] for row in _SECURITY_MASTER_ROWS], columns=_CSV_COLUMNS
    )
    result = process_security_master(frame)
    return {(row.symbol, row.exchange): row for row in result.itertuples()}


@pytest.mark.parametrize(
    ("symbol", "exchange", "brsymbol", "token"),
    [
        # Hyphenated and ampersand symbols keep their punctuation; only the
        # series suffix is stripped.
        ("BAJAJ-AUTO", "NSE", "BAJAJ-AUTO-EQ", "16669"),
        ("M&M", "NSE", "M&M-EQ", "2031"),
        ("RELIANCE", "NSE", "RELIANCE-EQ", "2885"),
        # The NSE T+0 listing keeps its suffix so it cannot collide with -EQ.
        ("BAJAJ-AUTO-T0", "NSE", "BAJAJ-AUTO-T0", "23262"),
        # BSE strips the group suffix.
        ("M&M", "BSE", "M&M-A", "500520"),
        ("BAJAJ-AUTO", "BSE", "BAJAJ-AUTO-A", "532977"),
    ],
)
def test_cash_symbols(instruments, symbol, exchange, brsymbol, token):
    row = instruments[(symbol, exchange)]
    assert row.brsymbol == brsymbol
    assert row.token == token
    assert row.instrumenttype == "EQ"
    assert row.expiry == ""


@pytest.mark.parametrize(
    ("symbol", "exchange", "brsymbol", "name", "expiry", "strike", "instrumenttype"),
    [
        ("NIFTY25AUG26FUT", "NFO", "NIFTY26AUGFUT", "NIFTY", "25-AUG-26", 0.0, "FUT"),
        ("M&M25AUG264050PE", "NFO", "M&M26AUG4050PE", "M&M", "25-AUG-26", 4050.0, "PE"),
        (
            "BAJAJ-AUTO29SEP2614800CE",
            "NFO",
            "BAJAJ-AUTO26SEP14800CE",
            "BAJAJ-AUTO",
            "29-SEP-26",
            14800.0,
            "CE",
        ),
        # Decimal strike is preserved in the symbol.
        (
            "FEDERALBNK30JUL26262.5PE",
            "BFO",
            "FEDERALBNK26JUL262.5PE",
            "FEDERALBNK",
            "30-JUL-26",
            262.5,
            "PE",
        ),
        # Weekly suffix: YY + month digit + DD.
        ("SENSEX13AUG2669500CE", "BFO", "SENSEX2681369500CE", "SENSEX", "13-AUG-26", 69500.0, "CE"),
        # Weekly suffix: YY + O/N/D month letter + DD.
        ("EURINR01OCT26FUT", "CDS", "EURINR26O01FUT", "EURINR", "01-OCT-26", 0.0, "FUT"),
        # MCX has no company_name; the underlying is recovered from the symbol.
        (
            "SILVER28AUG26297000CE",
            "MCX",
            "SILVER26AUG297000CE",
            "SILVER",
            "28-AUG-26",
            297000.0,
            "CE",
        ),
    ],
)
def test_derivative_symbols(
    instruments, symbol, exchange, brsymbol, name, expiry, strike, instrumenttype
):
    row = instruments[(symbol, exchange)]
    assert row.brsymbol == brsymbol
    assert row.name == name, "name must be the underlying for derivatives"
    assert row.expiry == expiry, "expiry must be DD-MMM-YY uppercase"
    assert row.strike == strike
    assert row.instrumenttype == instrumenttype


@pytest.mark.parametrize(
    ("symbol", "exchange", "brsymbol"),
    [
        ("NIFTY", "NSE_INDEX", "Nifty 50"),
        ("BANKNIFTY", "NSE_INDEX", "Nifty Bank"),
        ("MIDCPNIFTY", "NSE_INDEX", "NIFTY MID SELECT"),
        ("SENSEX", "BSE_INDEX", "SENSEX"),
        ("SENSEX50", "BSE_INDEX", "SNSX50"),
    ],
)
def test_index_symbols(instruments, symbol, exchange, brsymbol):
    row = instruments[(symbol, exchange)]
    assert row.brsymbol == brsymbol
    # Indices are stored as instrumenttype EQ; the *_INDEX exchange is what
    # distinguishes them. There is no "INDEX" instrument type in OpenAlgo.
    assert row.instrumenttype == "EQ"
    assert row.expiry == ""


def test_non_tradable_mcx_rows_are_dropped(instruments):
    assert not [key for key in instruments if key[0] == "MESCRUDOIL"]


def test_symbol_exchange_pairs_are_unique():
    frame = pd.DataFrame(
        [list(row) + ["", "", "", ""] for row in _SECURITY_MASTER_ROWS], columns=_CSV_COLUMNS
    )
    result = process_security_master(frame)
    assert not result.duplicated(subset=["symbol", "exchange"]).any()


# --- WebSocket scripId ---------------------------------------------------


@pytest.mark.parametrize(
    ("exchange", "token", "scrip_id"),
    [
        ("NSE", 2885, "NSE_2885"),
        ("BSE", 500325, "BSE_500325"),
        ("NFO", 58072, "NFO_58072"),
        ("BFO", 1146911, "BFO_1146911"),
        ("CDS", 1065, "NCD_1065"),
        ("MCX", 575691, "MCX_575691"),
        ("NSE_INDEX", 26000, "NSE_INDEX_26000"),
        ("BSE_INDEX", 1, "BSE_INDEX_1"),
    ],
)
def test_ws_scrip_id_round_trip(exchange, token, scrip_id):
    assert ws_scrip_id(exchange, token) == scrip_id
    # The longest prefix must win, so NSE_INDEX_26000 never parses as NSE.
    assert from_ws_scrip_id(scrip_id) == (exchange, str(token))


# --- protobuf tick parser ------------------------------------------------


@pytest.fixture(scope="module")
def parser():
    return HDFCSkyWebSocket(access_token="test-token")


def _frame(*packets):
    envelope = pb.GenericDTOList()
    for packet in packets:
        envelope.genericDTOList.append(packet)
    return envelope.SerializeToString()


def _mbp_packet():
    packet = pb.GenericDTO(
        instrumentId=2885, packetType=pb.NSE_CM_ALL, packetTimestamp=1700000000000
    )
    mbp = packet.mbpData
    mbp.lastTradedPrice = 1234.5
    mbp.openPrice = 1200.0
    mbp.highPrice = 1250.0
    mbp.lowPrice = 1190.0
    mbp.closingPrice = 1210.0
    mbp.volumeTradedToday = 987654
    mbp.lastTradeQuantity = 25
    mbp.averageTradePrice = 1222.2
    mbp.totalBuyQuantity = 5000
    mbp.totalSellQuantity = 4000
    mbp.oi = 123456
    mbp.lowerCircuitLimit = 1090.0
    mbp.upperCircuitLimit = 1330.0
    mbp.lastTradeTime = 1700000000
    for level in range(5):
        bid = mbp.marketDepthDTOList.marketDepthDTO.add()
        bid.price, bid.quantity, bid.numberOfOrders, bid.buyFlag = (
            1234.0 - level,
            10 * (level + 1),
            level + 1,
            True,
        )
    for level in range(5):
        ask = mbp.marketDepthDTOList.marketDepthDTO.add()
        ask.price, ask.quantity, ask.numberOfOrders, ask.buyFlag = (
            1235.0 + level,
            20 * (level + 1),
            level + 2,
            False,
        )
    return packet


def test_parse_mbp_packet(parser):
    tick = parser._parse_frame(_frame(_mbp_packet()))[0]
    assert tick["token"] == 2885
    assert tick["ltp"] == 1234.5
    assert tick["open"] == 1200.0
    assert tick["high"] == 1250.0
    assert tick["low"] == 1190.0
    assert tick["close"] == 1210.0
    assert tick["volume"] == 987654
    assert tick["ltq"] == 25
    assert tick["average_price"] == 1222.2
    assert tick["total_buy_quantity"] == 5000
    assert tick["total_sell_quantity"] == 4000
    assert tick["oi"] == 123456
    assert tick["lower_limit"] == 1090.0
    assert tick["upper_limit"] == 1330.0
    # buyFlag must route levels to the right side of the book.
    assert tick["depth"]["buy"][0] == {"price": 1234.0, "quantity": 10, "orders": 1}
    assert tick["depth"]["sell"][0] == {"price": 1235.0, "quantity": 20, "orders": 2}
    assert len(tick["depth"]["buy"]) == 5
    assert len(tick["depth"]["sell"]) == 5


def test_parse_index_packet(parser):
    packet = pb.GenericDTO(instrumentId=26000, packetType=pb.NSE_INDEX)
    index = packet.indexData
    index.indexValue = 24275.2
    index.openingIndex = 24100.0
    index.highIndexValue = 24300.0
    index.lowIndexValue = 24050.0
    index.closingIndex = 24150.0
    index.packetTimeStamp = 1700000001000

    tick = parser._parse_frame(_frame(packet))[0]
    assert tick["kind"] == "index"
    assert tick["token"] == 26000
    assert tick["ltp"] == 24275.2
    assert tick["open"] == 24100.0
    assert tick["close"] == 24150.0
    assert tick["timestamp"] == 1700000001000


def test_heartbeat_packets_are_dropped(parser):
    assert parser._parse_frame(_frame(pb.GenericDTO(packetType=pb.HEARTBEAT))) == []


def test_multi_packet_frame(parser):
    index = pb.GenericDTO(instrumentId=26000, packetType=pb.NSE_INDEX)
    index.indexData.indexValue = 24275.2
    ticks = parser._parse_frame(
        _frame(_mbp_packet(), index, pb.GenericDTO(packetType=pb.HEARTBEAT))
    )
    assert [tick["token"] for tick in ticks] == [2885, 26000]


def test_bare_generic_dto_is_accepted(parser):
    ticks = parser._parse_frame(_mbp_packet().SerializeToString())
    assert len(ticks) == 1
    assert ticks[0]["ltp"] == 1234.5


def test_undecodable_frame_returns_no_ticks(parser):
    assert parser._parse_frame(b"\xff\xff\xff\xff\xff\xff") == []
