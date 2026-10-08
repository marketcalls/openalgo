"""Rupeezy (Vortex API) plugin: the parts that need no broker session.

Covers the binary feed parser against synthetic packets built at the
documented offsets, the instrument-master symbol construction, MCX lot/unit
conversion, order payload mapping, positions, funds and GTT orders.
"""

import io
import struct
from types import SimpleNamespace

import pandas as pd
import pytest

# Load the proxy first, as the other streaming tests do: the streaming
# package imports its adapter, which imports websocket_proxy.
import websocket_proxy  # noqa: F401  isort:skip

from broker.rupeezy.mapping import exchange as ex
from broker.rupeezy.streaming.rupeezy_websocket import parse_packet, split_message

# --- binary feed --------------------------------------------------------------


def _exch(name):
    return name.encode().ljust(10, b"\x00")


def _ltp_packet():
    return struct.pack("<10sid", _exch("NSE_EQ"), 2885, 1412.35)


def _ohlcv_packet():
    return struct.pack(
        "<10sididdddi", _exch("NSE_FO"), 51440, 104.1, 1700000000, 100.15, 120.0, 95.5, 99.8, 23700
    )


def _full_packet():
    head = struct.pack(
        "<10sididdddiiidqqi",
        _exch("MCX_FO"),
        585909,
        6500.0,  # ltp
        1700000001,  # ltt
        6400.0,  # open
        6550.0,  # high
        6390.0,  # low
        6420.0,  # close
        12345,  # volume
        1700000002,  # last update
        7,  # ltq
        6480.5,  # avg
        111,  # total buy qty
        222,  # total sell qty
        3333,  # oi
    )
    bids = b"".join(struct.pack("<dii", 6499.0 - i, 10 + i, 1 + i) for i in range(5))
    asks = b"".join(struct.pack("<dii", 6501.0 + i, 20 + i, 2 + i) for i in range(5))
    dpr = struct.pack("<ii", 715000, 585000)
    return head + bids + asks + dpr


def _frame(*packets):
    out = struct.pack("<H", len(packets))
    for p in packets:
        out += struct.pack("<H", len(p)) + p
    return out


def test_packet_sizes_match_the_documented_modes():
    assert (len(_ltp_packet()), len(_ohlcv_packet()), len(_full_packet())) == (22, 62, 266)


def test_a_frame_carries_several_packets():
    packets = split_message(_frame(_ltp_packet(), _ohlcv_packet(), _full_packet()))
    assert [len(p) for p in packets] == [22, 62, 266]
    assert split_message(b"\x00") == []  # heartbeat


def test_ltp_packet():
    tick = parse_packet(_ltp_packet())
    assert tick == {"mode": "ltp", "exchange": "NSE_EQ", "token": 2885, "ltp": 1412.35}


def test_ohlcv_packet():
    tick = parse_packet(_ohlcv_packet())
    assert tick["mode"] == "ohlcv"
    assert (tick["exchange"], tick["token"]) == ("NSE_FO", 51440)
    assert (tick["open"], tick["high"], tick["low"], tick["close"]) == (100.15, 120.0, 95.5, 99.8)
    assert tick["volume"] == 23700 and tick["ltt"] == 1700000000


def test_full_packet_fields_and_depth():
    tick = parse_packet(_full_packet())
    assert tick["mode"] == "full"
    assert (tick["exchange"], tick["token"], tick["ltp"]) == ("MCX_FO", 585909, 6500.0)
    assert tick["close"] == 6420.0 and tick["volume"] == 12345
    assert (tick["ltq"], tick["average_price"]) == (7, 6480.5)
    assert (tick["total_buy_quantity"], tick["total_sell_quantity"], tick["oi"]) == (111, 222, 3333)
    assert tick["depth"]["buy"][0] == {"price": 6499.0, "quantity": 10, "orders": 1}
    assert tick["depth"]["sell"][4] == {"price": 6505.0, "quantity": 24, "orders": 6}
    # DPR arrives in paise.
    assert (tick["upper_limit"], tick["lower_limit"]) == (7150.0, 5850.0)


def test_unknown_packet_size_is_ignored():
    assert parse_packet(b"\x00" * 30) is None


# --- master contract ------------------------------------------------------------

MASTER_SAMPLE = """token,exchange,symbol,instrument_name,series,expiry_date,option_type,strike_price,tick,lot_size,eligibility,security_desc,asm_gsm_stage,last_trading_date,isin_code,ticker,has_cas_session
2885,NSE_EQ,RELIANCE,EQUITIES,EQ,,,,10,1,1,RELIANCE INDUSTRIES LTD,,,INE002A01018,NSE:RELIANCE,true
766440,NSE_EQ,PAPADMALJI,EQUITIES,ST,,,,5,1600,1,PAPADMALJI AGRO FOODS LTD,,,INE1V7901010,NSE:PAPADMALJI-ST,false
26000,NSE_EQ,NIFTY,EQIDX,EQ,,,,5,0,0,NIFTY,,,,NSE:NIFTYIDX,true
26008,NSE_EQ,NIFTYIT,EQIDX,EQ,,,,5,0,0,NIFTY IT,,,,NSE:NIFTYITIDX,true
19000,BSE_EQ,SENSEX,EQIDX,A,,,,5,0,0,SENSEX,,,,BSE:SENSEXIDX,true
48704,NSE_FO,NIFTY,FUTIDX,XX,20261027,XX,-0.010000000000000000,10,65,1,NIFTY26OCTFUT,,,,NSE:NIFTY26OCTFUT,false
51440,NSE_FO,NIFTY,OPTIDX,XX,20261027,CE,25000.0000000000,5,65,1,NIFTY26OCT25000CE,,,,NSE:NIFTY26OCT25000CE,false
86883,NSE_FO,BANKBARODA,OPTSTK,XX,20261027,PE,177.50000000000000,1,2925,1,BANKBARODA26OCT177.5PE,,,,NSE:BANKBARODA26OCT177.5PE,false
585909,MCX_FO,CRUDEOIL,FUTCOM,XX,20280320,XX,0.000000000000000000,100,100,1,LIGHT SWEET CRUDE OIL,,1837209599,,MCX:CRUDEOIL28MARFUT,false
"""


@pytest.fixture
def master():
    from broker.rupeezy.database.master_contract_db import process_master

    df = process_master(pd.read_csv(io.StringIO(MASTER_SAMPLE), dtype=str))
    return {(r.symbol, r.exchange): r for r in df.itertuples()}


@pytest.mark.parametrize(
    "symbol, exchange, brsymbol, brexchange, itype",
    [
        ("RELIANCE", "NSE", "RELIANCE", "NSE_EQ", "EQ"),
        ("PAPADMALJI-ST", "NSE", "PAPADMALJI-ST", "NSE_EQ", "EQ"),
        ("NIFTY", "NSE_INDEX", "NIFTYIDX", "NSE_EQ", "EQ"),
        ("NIFTYIT", "NSE_INDEX", "NIFTYITIDX", "NSE_EQ", "EQ"),
        ("SENSEX", "BSE_INDEX", "SENSEXIDX", "BSE_EQ", "EQ"),
        ("NIFTY27OCT26FUT", "NFO", "NIFTY26OCTFUT", "NSE_FO", "FUT"),
        ("NIFTY27OCT2625000CE", "NFO", "NIFTY26OCT25000CE", "NSE_FO", "CE"),
        ("BANKBARODA27OCT26177.5PE", "NFO", "BANKBARODA26OCT177.5PE", "NSE_FO", "PE"),
        ("CRUDEOIL20MAR28FUT", "MCX", "CRUDEOIL28MARFUT", "MCX_FO", "FUT"),
    ],
)
def test_master_symbols(master, symbol, exchange, brsymbol, brexchange, itype):
    row = master[(symbol, exchange)]
    assert (row.brsymbol, row.brexchange, row.instrumenttype) == (brsymbol, brexchange, itype)


def test_master_scaling_and_expiry(master):
    fut = master[("NIFTY27OCT26FUT", "NFO")]
    assert (fut.expiry, fut.strike, fut.lotsize, fut.tick_size) == ("27-OCT-26", 0.0, 65, 0.1)
    opt = master[("BANKBARODA27OCT26177.5PE", "NFO")]
    assert (opt.strike, opt.tick_size, opt.name) == (177.5, 0.01, "BANKBARODA")
    crude = master[("CRUDEOIL20MAR28FUT", "MCX")]
    assert (crude.lotsize, crude.tick_size) == (100, 1.0)
    assert master[("RELIANCE", "NSE")].expiry == ""


def test_index_names_follow_the_openalgo_list():
    assert ex.to_oa_index_symbol("NIFTYMID100", "NSE_INDEX") == "NIFTYMIDCAP100"
    assert ex.to_oa_index_symbol("REALTY", "NSE_INDEX") == "NIFTYREALTY"
    assert ex.to_oa_index_symbol("REALTY", "BSE_INDEX") == "BSEREALTY"
    assert ex.to_oa_index_symbol("BANKNIFTY", "NSE_INDEX") == "BANKNIFTY"


# --- quantities and orders ------------------------------------------------------


def test_mcx_is_sent_in_lots_and_read_back_in_units():
    assert ex.to_vortex_quantity(200, "MCX_FO", 100) == 2
    assert ex.from_vortex_quantity(2, "MCX_FO", 100) == 200
    with pytest.raises(ValueError):
        ex.to_vortex_quantity(150, "MCX_FO", 100)


def test_other_segments_are_sent_in_units():
    assert ex.to_vortex_quantity(130, "NSE_FO", 65) == 130
    assert ex.to_vortex_quantity(5, "NSE_EQ", 1) == 5
    assert ex.from_vortex_quantity(130, "NSE_FO", 65) == 130


@pytest.fixture
def symbol_info(monkeypatch):
    import broker.rupeezy.mapping.transform_data as td

    rows = {
        ("SBIN", "NSE"): SimpleNamespace(brsymbol="SBIN", brexchange="NSE_EQ", lotsize=1),
        ("CRUDEOIL20MAR28FUT", "MCX"): SimpleNamespace(
            brsymbol="CRUDEOIL28MARFUT", brexchange="MCX_FO", lotsize=100
        ),
    }
    monkeypatch.setattr(
        td, "get_symbol_info", lambda symbol, exchange: rows.get((symbol, exchange))
    )
    return td


def test_limit_order_payload(symbol_info):
    payload = symbol_info.transform_data(
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "BUY",
            "pricetype": "LIMIT",
            "product": "CNC",
            "quantity": "5",
            "price": "801.5",
            "strategy": "test",
        }
    )
    assert payload["ticker"] == "NSE:SBIN"
    assert (payload["variety"], payload["product"], payload["quantity"]) == ("RL", "DELIVERY", 5)
    assert (payload["price"], payload["trigger_price"]) == (801.5, 0.0)
    assert payload["validity"] == "DAY" and payload["is_amo"] is False


def test_market_and_stop_orders(symbol_info):
    base = {"symbol": "CRUDEOIL20MAR28FUT", "exchange": "MCX", "action": "SELL", "product": "NRML"}
    mkt = symbol_info.transform_data(
        {**base, "pricetype": "MARKET", "quantity": "200", "price": "6500"}
    )
    assert (mkt["ticker"], mkt["variety"], mkt["price"], mkt["quantity"]) == (
        "MCX:CRUDEOIL28MARFUT",
        "RL-MKT",
        0.0,
        2,
    )
    slm = symbol_info.transform_data(
        {**base, "pricetype": "SL-M", "quantity": "100", "trigger_price": "6400"}
    )
    assert (slm["variety"], slm["trigger_price"], slm["price"]) == ("SL-MKT", 6400.0, 0.0)


def test_product_round_trip():
    from broker.rupeezy.mapping.transform_data import map_product_type, reverse_map_product_type

    assert map_product_type("MIS") == "INTRADAY"
    assert reverse_map_product_type("NSE", "DELIVERY") == "CNC"
    assert reverse_map_product_type("NFO", "DELIVERY") == "NRML"
    assert reverse_map_product_type("NSE", "MTF") == "CNC"


# --- positions, funds -----------------------------------------------------------


def test_position_pnl_is_booked_only_once_flat():
    from broker.rupeezy.mapping.order_data import position_pnl

    assert position_pnl({"quantity": 0, "buy_value": 1000, "sell_value": 1100}) == 100
    # An open position needs a live price, which this plugin does not fetch.
    assert position_pnl({"quantity": 5, "buy_value": 1000, "sell_value": 0}) == 0.0


def test_funds_sum_nse_and_mcx(monkeypatch):
    import broker.rupeezy.api.funds as funds

    bucket = {
        "collateral": 100,
        "booked_profit": 30,
        "mtm_and_booked_loss": -10,
        "total_utilization": -50,
        "net_available": 1000,
    }
    monkeypatch.setattr(funds, "request_json", lambda *a, **k: {"nse": bucket, "mcx": bucket})
    assert funds.get_margin_data("tok") == {
        "availablecash": "2000.00",
        "collateral": "200.00",
        "m2munrealized": "0.00",
        "m2mrealized": "40.00",
        "utiliseddebits": "100.00",
    }


# --- GTT --------------------------------------------------------------------------


@pytest.fixture
def gtt(monkeypatch, symbol_info):
    import broker.rupeezy.mapping.gtt_data as gd

    monkeypatch.setattr(gd, "resolve_instrument", symbol_info.resolve_instrument)
    monkeypatch.setattr(gd, "get_oa_symbol", lambda brsymbol, exchange: brsymbol)
    return gd


def test_single_gtt(gtt):
    body = gtt.transform_place_gtt(
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "trigger_type": "SINGLE",
            "action": "BUY",
            "product": "CNC",
            "quantity": 3,
            "pricetype": "LIMIT",
            "price": 790,
            "trigger_price": 795,
        }
    )
    assert body == {
        "ticker": "NSE:SBIN",
        "transaction_type": "BUY",
        "product": "DELIVERY",
        "gtt_trigger_type": "single",
        "quantity": 3,
        "price": 790.0,
        "trigger_price": 795.0,
        "variety": "RL",
    }


@pytest.mark.parametrize(
    "action, stoploss_trigger, profit_trigger",
    [("SELL", 780.0, 850.0), ("BUY", 850.0, 780.0)],
)
def test_oco_legs_follow_the_side(gtt, action, stoploss_trigger, profit_trigger):
    body = gtt.transform_place_gtt(
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "trigger_type": "OCO",
            "action": action,
            "product": "MIS",
            "quantity": 2,
            "pricetype": "MARKET",
            "triggerprice_sl": 780,
            "stoploss": 779,
            "triggerprice_tg": 850,
            "target": 851,
        }
    )
    assert body["gtt_trigger_type"] == "oco" and body["product"] == "INTRADAY"
    assert body["stoploss"]["trigger_price"] == stoploss_trigger
    assert body["profit"]["trigger_price"] == profit_trigger
    # MARKET legs go as RL-MKT with no limit price.
    assert body["stoploss"]["variety"] == "RL-MKT" and body["stoploss"]["price"] == 0.0


def test_gtt_quantity_follows_mcx_lots(gtt):
    body = gtt.transform_place_gtt(
        {
            "symbol": "CRUDEOIL20MAR28FUT",
            "exchange": "MCX",
            "trigger_type": "SINGLE",
            "action": "SELL",
            "product": "NRML",
            "quantity": 200,
            "pricetype": "LIMIT",
            "price": 6400,
            "trigger_price": 6410,
        }
    )
    assert body["quantity"] == 2


VORTEX_OCO = {
    "ticker": "NSE:SBIN",
    "exchange": "NSE_EQ",
    "id": "8f141670-59b3-4754-81c7-a072f3598475",
    "lot_size": 1,
    "product": "INTRADAY",
    "symbol": "SBIN",
    "transaction_type": "SELL",
    "trigger_type": "oco",
    "orders": [
        {
            "id": 2,
            "price": 0,
            "quantity": 190,
            "status": "active",
            "trail": None,
            "transaction_type": "SELL",
            "trigger_price": 850,
            "variety": "RL-MKT",
            "created_at": "2025-06-24T12:24:32Z",
        },
        {
            "id": 1,
            "price": 779,
            "quantity": 190,
            "status": "active",
            "trail": {"id": 9, "trail_jump_point": 2, "trail_jump_type": "Point"},
            "transaction_type": "SELL",
            "trigger_price": 780,
            "variety": "RL",
            "created_at": "2025-06-24T12:24:32Z",
        },
    ],
}


def test_gtt_book_maps_to_the_openalgo_shape(gtt):
    [row] = gtt.map_gtt_book({"status": "success", "data": [VORTEX_OCO]})
    assert row["trigger_id"] == VORTEX_OCO["id"]
    assert (row["trigger_type"], row["status"], row["symbol"], row["exchange"]) == (
        "two-leg",
        "active",
        "SBIN",
        "NSE",
    )
    assert row["trigger_prices"] == [780.0, 850.0]
    assert [leg["pricetype"] for leg in row["legs"]] == ["LIMIT", "MARKET"]
    assert row["legs"][0]["product"] == "MIS"


def test_gtt_book_hides_finished_triggers_unless_asked(gtt):
    done = {**VORTEX_OCO, "orders": [{**o, "status": "triggered"} for o in VORTEX_OCO["orders"]]}
    assert gtt.map_gtt_book({"data": [done]}) == []
    assert gtt.map_gtt_book({"data": [done]}, include_history=True)[0]["status"] == "triggered"


def test_gtt_modify_matches_legs_by_price_and_keeps_the_trail(gtt):
    body = gtt.transform_modify_gtt(
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "quantity": 100,
            "pricetype": "LIMIT",
            "triggerprice_sl": 770,
            "stoploss": 769,
            "triggerprice_tg": 860,
            "target": 861,
        },
        VORTEX_OCO,
    )
    assert [(leg["id"], leg["trigger_price"], leg["price"]) for leg in body] == [
        (1, 770.0, 769.0),
        (2, 860.0, 861.0),
    ]
    assert body[0]["trail"] == {"id": 9, "trail_jump_point": 2, "trail_jump_type": "Point"}
    assert "trail" not in body[1]


def test_rate_limit_categories():
    from broker.rupeezy.api.rate_limiter import category_for

    assert category_for("GET", "/user/funds") == "account"
    assert category_for("POST", "/trading/orders/gtt") == "trading"


def test_funds_prefer_the_combined_bucket(monkeypatch):
    import broker.rupeezy.api.funds as funds

    bucket = {"net_available": 1000, "collateral": 0, "total_utilization": 0}
    combined = {"net_available": 1500, "collateral": 0, "total_utilization": 0}
    monkeypatch.setattr(
        funds,
        "request_json",
        lambda *a, **k: {"nse": bucket, "mcx": bucket, "exchange_combined": combined},
    )
    assert funds.get_margin_data("tok")["availablecash"] == "1500.00"


def test_holdings_use_vortex_last_price(monkeypatch):
    import broker.rupeezy.mapping.order_data as od

    monkeypatch.setattr(od, "get_oa_symbol", lambda brsymbol, exchange: brsymbol)
    raw = {
        "status": "Success",
        "data": [
            {
                "nse": {"ticker": "NSE:IDEA", "exchange": "NSE_EQ", "symbol": "IDEA"},
                "bse": {},
                "total_free": 3,
                "t1_quantity": 0,
                "average_price": 12.7,
                "last_price": 13.21,
                "product": "DELIVERY",
            }
        ],
    }
    [row] = od.transform_holdings_data(od.map_portfolio_data(raw))
    assert (row["symbol"], row["exchange"], row["quantity"], row["ltp"], row["pnl"]) == (
        "IDEA",
        "NSE",
        3,
        13.21,
        1.53,
    )
    assert row["pnlpercent"] == 4.02


# --- historical data (quotes + history) -------------------------------------------


@pytest.fixture
def data_module(monkeypatch):
    import broker.rupeezy.api.data as data

    rows = {
        ("SBIN", "NSE"): SimpleNamespace(brsymbol="SBIN", brexchange="NSE_EQ"),
        ("NIFTY", "NSE_INDEX"): SimpleNamespace(brsymbol="NIFTYIDX", brexchange="NSE_EQ"),
    }
    monkeypatch.setattr(data, "get_symbol_info", lambda s, e: rows.get((s, e)))
    return data


def test_daily_candles_land_on_the_ist_date(data_module, monkeypatch):
    # 2026-10-05 00:00 IST, returned newest-first the way the docs show.
    ist_midnight = 1791138600
    sent = {}

    def fake_request(method, endpoint, auth, params=None, **_):
        sent.update(endpoint=endpoint, params=params)
        return {
            "s": "ok",
            "t": [ist_midnight, ist_midnight - 86400],
            "o": [2, 1],
            "h": [2, 1],
            "l": [2, 1],
            "c": [2, 1],
            "v": [20, 10],
        }

    monkeypatch.setattr(data_module, "request_json", fake_request)
    df = data_module.BrokerData("tok").get_history("SBIN", "NSE", "D", "2026-10-02", "2026-10-05")
    assert sent["endpoint"] == "/data/history"
    assert (sent["params"]["ticker"], sent["params"]["resolution"]) == ("NSE:SBIN", "1D")
    assert list(df.columns) == ["timestamp", "open", "high", "low", "close", "volume", "oi"]
    # 00:00 UTC of the IST date, ascending: the Zerodha convention.
    assert df["timestamp"].tolist() == [1791072000, 1791158400]
    assert df["close"].tolist() == [1.0, 2.0]


def test_history_with_no_data_returns_the_empty_frame(data_module, monkeypatch):
    monkeypatch.setattr(data_module, "request_json", lambda *a, **k: {"s": "no_data"})
    df = data_module.BrokerData("tok").get_history("SBIN", "NSE", "5m", "2026-10-04", "2026-10-04")
    assert df.empty and list(df.columns)[0] == "timestamp"


def test_multiquotes_reports_every_leg(data_module, monkeypatch):
    def fake_request(method, endpoint, auth, params=None, **_):
        assert endpoint == "/data/quotes" and ("mode", "full") in params
        return {
            "status": "success",
            "data": {
                "NSE:SBIN": {
                    "last_trade_price": 954.0,
                    "close_price": 958.75,
                    "depth": {"buy": [{"price": 953.0, "quantity": 54}], "sell": [{}]},
                }
            },
        }

    monkeypatch.setattr(data_module, "request_json", fake_request)
    out = data_module.BrokerData("tok").get_multiquotes(
        [
            {"symbol": "SBIN", "exchange": "NSE"},
            {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
            {"symbol": "NOPE", "exchange": "NSE"},
        ]
    )
    by_symbol = {row["symbol"]: row for row in out}
    assert by_symbol["SBIN"]["data"]["ltp"] == 954.0
    assert by_symbol["SBIN"]["data"]["bid"] == 953.0 and by_symbol["SBIN"]["data"]["ask"] == 0.0
    assert by_symbol["NIFTY"]["error"] == "No quote data available"
    assert "not found" in by_symbol["NOPE"]["error"]


def test_data_rate_limit_categories():
    from broker.rupeezy.api.rate_limiter import category_for

    assert category_for("GET", "/data/quotes") == "quotes"
    assert category_for("GET", "/data/history") == "history"


# --- trade book -------------------------------------------------------------------


def test_trade_book_maps_to_openalgo(monkeypatch):
    import broker.rupeezy.mapping.order_data as od

    monkeypatch.setattr(od, "get_oa_symbol", lambda brsymbol, exchange: brsymbol)
    monkeypatch.setattr(od, "get_symbol_info", lambda s, e: SimpleNamespace(lotsize=100))
    raw = {
        "status": "success",
        "trades": [
            {
                "order_id": "NXAAE00002@6",
                "ticker": "NSE:ACC",
                "exchange": "NSE_EQ",
                "transaction_type": "SELL",
                "product": "INTRADAY",
                "trade_quantity": 1,
                "trade_price": 1856.75,
                "traded_at": "2023-06-16 13:06:43",
            },
            {
                "order_id": "NXAAE00003@6",
                "ticker": "MCX:CRUDEOIL26NOVFUT",
                "exchange": "MCX_FO",
                "transaction_type": "BUY",
                "product": "DELIVERY",
                "trade_quantity": 2,
                "trade_price": 6500,
                "traded_at": "2023-06-16 13:07:00",
            },
        ],
    }
    rows = od.transform_tradebook_data(od.map_trade_data(trade_data=raw))
    assert rows[0] == {
        "symbol": "ACC",
        "exchange": "NSE",
        "product": "MIS",
        "action": "SELL",
        "quantity": 1,
        "average_price": 1856.75,
        "trade_value": 1856.75,
        "orderid": "NXAAE00002@6",
        "timestamp": "2023-06-16 13:06:43",
    }
    # MCX trades come back in lots; OpenAlgo shows units (2 lots x 100).
    assert (rows[1]["exchange"], rows[1]["product"], rows[1]["quantity"]) == ("MCX", "NRML", 200)


def test_trade_book_fills_bare_trades_from_the_order_book(monkeypatch):
    import broker.rupeezy.api.order_api as oa

    def fake_request(method, endpoint, auth, **_):
        assert endpoint == "/trading/trades"
        # A bare trade row: no ticker / side / product.
        return {
            "status": "success",
            "trades": [
                {
                    "order_id": "NXAAE000027:",
                    "trade_no": "240151702",
                    "trade_price": 14929,
                    "trade_quantity": 1,
                    "traded_at": "2026-10-07 17:41:25",
                }
            ],
        }

    book = {
        "status": "success",
        "orders": [
            {
                "order_id": "NXAAE000027:",
                "ticker": "MCX:GOLDPETAL26OCTFUT",
                "exchange": "MCX_FO",
                "transaction_type": "SELL",
                "product": "DELIVERY",
                "variety": "RL",
                "lot_size": 1,
            }
        ],
    }
    monkeypatch.setattr(oa, "request_json", fake_request)
    monkeypatch.setattr(oa, "get_order_book", lambda auth: book)
    [trade] = oa.get_trade_book("tok")["trades"]
    assert (trade["ticker"], trade["exchange"], trade["transaction_type"], trade["product"]) == (
        "MCX:GOLDPETAL26OCTFUT",
        "MCX_FO",
        "SELL",
        "DELIVERY",
    )
    assert trade["trade_price"] == 14929  # the trade's own fields are kept


# --- close-all reporting and read retry -------------------------------------------


@pytest.fixture
def close_all(monkeypatch):
    import broker.rupeezy.api.order_api as oa

    monkeypatch.setattr(oa, "get_oa_symbol", lambda brsymbol, exchange: brsymbol)
    monkeypatch.setattr(oa, "_invalidate_position_cache", lambda auth: None)
    return oa


def _book(*rows):
    return {"status": "success", "data": {"net": list(rows), "day": []}}


def test_close_all_reports_refused_square_offs(close_all, monkeypatch):
    position = {
        "ticker": "MCX:GOLDPETAL26OCTFUT",
        "exchange": "MCX_FO",
        "product": "DELIVERY",
        "quantity": 1,
        "lot_size": 1,
    }
    monkeypatch.setattr(close_all, "get_positions", lambda auth: _book(position))
    monkeypatch.setattr(
        close_all,
        "place_order_api",
        lambda order, auth: (
            None,
            {"status": "error", "message": "Your IP is not allowed for this application"},
            None,
        ),
    )
    body, status = close_all.close_all_positions("key", "tok")
    assert status == 400 and body["status"] == "error"
    assert "Squared off 0 of 1" in body["message"] and "IP is not allowed" in body["message"]


def test_close_all_does_not_call_an_unreadable_book_empty(close_all, monkeypatch):
    monkeypatch.setattr(
        close_all, "get_positions", lambda auth: {"status": "error", "message": "Invalid session"}
    )
    body, status = close_all.close_all_positions("key", "tok")
    assert status == 502 and "Invalid session" in body["message"]


def test_close_all_success_when_every_order_is_accepted(close_all, monkeypatch):
    position = {"ticker": "NSE:SBIN", "exchange": "NSE_EQ", "product": "INTRADAY", "quantity": -5}
    sent = []
    monkeypatch.setattr(close_all, "get_positions", lambda auth: _book(position))
    monkeypatch.setattr(
        close_all,
        "place_order_api",
        lambda order, auth: sent.append(order) or (None, {"status": "success"}, "OID1"),
    )
    body, status = close_all.close_all_positions("key", "tok")
    assert status == 200 and body["status"] == "success"
    assert (sent[0]["action"], sent[0]["quantity"], sent[0]["product"]) == ("BUY", "5", "MIS")


class _FlakyClient:
    """First call times out (a dead pooled connection), the next succeeds."""

    def __init__(self, fail_times=1):
        self.calls = []
        self.fail_times = fail_times

    def request(self, method, url, **kwargs):
        import httpx

        self.calls.append((method, kwargs["timeout"]))
        if len(self.calls) <= self.fail_times:
            raise httpx.ReadTimeout("timed out")
        return httpx.Response(200, json={"status": "success"})


def test_a_read_is_retried_once_on_a_dead_connection(monkeypatch):
    import broker.rupeezy.api.client as client

    flaky = _FlakyClient()
    monkeypatch.setattr(client, "get_httpx_client", lambda: flaky)
    monkeypatch.setattr(client, "wait_for_slot", lambda category: None)
    assert client.request_json("GET", "/trading/portfolio/positions", "tok") == {
        "status": "success"
    }
    # Short first attempt, then the full timeout on the fresh connection.
    assert flaky.calls == [("GET", 10), ("GET", 30)]


def test_an_order_is_never_retried(monkeypatch):
    import httpx

    import broker.rupeezy.api.client as client

    flaky = _FlakyClient()
    monkeypatch.setattr(client, "get_httpx_client", lambda: flaky)
    monkeypatch.setattr(client, "wait_for_slot", lambda category: None)
    with pytest.raises(httpx.ReadTimeout):
        client.request("POST", "/trading/orders/regular", "tok", payload={"ticker": "NSE:SBIN"})
    assert len(flaky.calls) == 1
