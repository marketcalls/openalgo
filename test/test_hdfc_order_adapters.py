"""HDFC Sky and HDFC Securities order updates from ORDER/TRADE feed packets.

Both brokers' feed docs (17-websocket.md) list packet types ORDER (8) and
TRADE (9) carrying GenericDTO.order / GenericDTO.trade. The adapters publish
ORDER packets, decoded from real protobuf frames built here with each plugin's
own generated module, as OpenAlgo order-update fields; TRADE packets repeat the
same fills and are not published.
"""

import json
from unittest.mock import MagicMock

import pytest

import websocket_proxy  # noqa: F401  (resolves the adapter import cycle)
from broker.hdfcsecurities.streaming import hdfcsecurities_market_pb2 as sec_pb
from broker.hdfcsecurities.streaming import hdfcsecurities_order_adapter as sec_mod
from broker.hdfcsky.streaming import hdfcsky_market_pb2 as sky_pb
from broker.hdfcsky.streaming import hdfcsky_order_adapter as sky_mod

BROKERS = [
    (sky_mod, sky_pb, sky_mod.HDFCSkyOrderUpdateAdapter),
    (sec_mod, sec_pb, sec_mod.HDFCSecuritiesOrderUpdateAdapter),
]


@pytest.fixture(params=BROKERS, ids=["hdfcsky", "hdfcsecurities"])
def env(request, monkeypatch):
    mod, pb, cls = request.param
    monkeypatch.setattr(
        mod, "to_openalgo_symbol", lambda brsym, exch, token=None: f"OA:{brsym}" if brsym else brsym
    )
    adapter = cls(user_id="u1", access_token="tok")
    adapter._publish_event_fields = MagicMock()
    return mod, pb, adapter


def _order(pb, **kw):
    order = pb.Order(
        orderID=kw.get("orderID", "2000180000001"),
        tokenID=kw.get("tokenID", 3045),
        price=kw.get("price", 1.0),
        avgPrice=kw.get("avgPrice", 0.0),
        triggerPrice=kw.get("triggerPrice", 0.0),
        quantity=kw.get("quantity", 1),
        fillQuantity=kw.get("fillQuantity", 0),
        volFilledToday=kw.get("volFilledToday", 0),
        remainingQuantity=kw.get("remainingQuantity", 1),
        side=kw.get("side", pb.BUY),
        type=kw.get("type", pb.LIMIT),
        prodType=kw.get("prodType", pb.CNC),
        exchange=kw.get("exchange", pb.NSE),
        segment=kw.get("segment", pb.Capital),
        status=kw.get("status", pb.CONFIRMED),
        isOrderDownload=kw.get("isOrderDownload", False),
    )
    order.description.tradingSymbol = kw.get("tradingSymbol", "SBIN-EQ")
    if "error_message" in kw or "error_code" in kw:
        order.error.Message = kw.get("error_message", "")
        order.error.Code = kw.get("error_code", 0)
    return pb.GenericDTO(packetType=pb.ORDER, order=order)


def _trade(pb, **kw):
    trade = pb.Trade(
        TradeID="T1",
        OrderID=kw.get("OrderID", "2000180000001"),
        Token=3045,
        TradingSymbol="SBIN-EQ",
        Price=800.0,
        FillPrice=kw.get("FillPrice", 800.0),
        FillQty=kw.get("FillQty", 5),
        VolFilledToday=kw.get("VolFilledToday", 5),
        RemainingVolume=kw.get("RemainingVolume", 5),
        OriginalVol=10,
        side=pb.SELL,
        prodType=pb.MIS,
        exchange=pb.NSE,
        segment=pb.Capital,
        isTradeDownload=kw.get("isTradeDownload", False),
    )
    return pb.GenericDTO(packetType=pb.TRADE, trade=trade)


def _frame(pb, *packets):
    return pb.GenericDTOList(genericDTOList=list(packets)).SerializeToString()


def _published(adapter):
    return [c.args[0] for c in adapter._publish_event_fields.call_args_list]


def test_confirmed_order_publishes_open_update(env):
    _, pb, adapter = env
    adapter._handle_message(_frame(pb, _order(pb)))
    [event] = _published(adapter)
    assert event == {
        "orderid": "2000180000001",
        "symbol": "OA:SBIN-EQ",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 1,
        "price": 1.0,
        "trigger_price": 0.0,
        "pricetype": "LIMIT",
        "product": "CNC",
        "order_status": "open",
        "filled_quantity": 0,
        "pending_quantity": 1,
        "average_price": 0.0,
    }


def test_complete_order_carries_fill_and_average(env):
    _, pb, adapter = env
    packet = _order(
        pb, status=pb.COMPLETE, quantity=10, fillQuantity=10, remainingQuantity=0, avgPrice=801.25
    )
    adapter._handle_message(_frame(pb, packet))
    [event] = _published(adapter)
    assert event["order_status"] == "complete"
    assert event["filled_quantity"] == 10
    assert event["pending_quantity"] == 0
    assert event["average_price"] == 801.25


def test_rejected_order_gives_the_broker_message(env):
    _, pb, adapter = env
    adapter._handle_message(
        _frame(pb, _order(pb, status=pb.REJECTED, error_message="Margin unavailable"))
    )
    [event] = _published(adapter)
    assert event["order_status"] == "rejected"
    assert event["rejection_reason"] == "Margin unavailable"


def test_rejected_order_without_message_names_the_error_code(env):
    _, pb, adapter = env
    adapter._handle_message(
        _frame(pb, _order(pb, status=pb.REJECTED, error_code=pb.MarginUnavailable))
    )
    [event] = _published(adapter)
    assert event["rejection_reason"] == "MarginUnavailable"


@pytest.mark.parametrize("status", ["MODIFY_REJECTED", "CANCEL_REJECTED"])
def test_a_refused_modify_or_cancel_leaves_the_order_open(env, status):
    _, pb, adapter = env
    adapter._handle_message(_frame(pb, _order(pb, status=getattr(pb, status))))
    [event] = _published(adapter)
    assert event["order_status"] == "open"
    assert "rejection_reason" not in event


@pytest.mark.parametrize(
    "status, expected",
    [
        ("CANCEL_CONFIRMED", "cancelled"),
        ("AMO_CANCEL_CONFIRMED", "cancelled"),
        ("SL_TRIGGER_CONFIRMED", "trigger pending"),
        ("PARTIAL_TRADE", "open"),
        ("AMO_REQ_RECEIVED", "open"),
    ],
)
def test_status_mapping(env, status, expected):
    _, pb, adapter = env
    adapter._handle_message(_frame(pb, _order(pb, status=getattr(pb, status))))
    assert _published(adapter)[0]["order_status"] == expected


@pytest.mark.parametrize(
    "prod, product",
    [
        ("CNC", "CNC"),
        ("MIS", "MIS"),
        ("NRML", "NRML"),
        ("AMO_CNC", "CNC"),
        ("BO_MIS", "MIS"),
        ("MTF", "MTF"),
    ],
)
def test_product_mapping(env, prod, product):
    _, pb, adapter = env
    adapter._handle_message(_frame(pb, _order(pb, prodType=getattr(pb, prod))))
    assert _published(adapter)[0]["product"] == product


def test_slm_is_sl_dash_m_and_fno_is_nfo(env):
    _, pb, adapter = env
    packet = _order(pb, type=pb.SLM, segment=pb.FutOpt, side=pb.SELL, triggerPrice=99.5)
    adapter._handle_message(_frame(pb, packet))
    [event] = _published(adapter)
    assert event["pricetype"] == "SL-M"
    assert event["exchange"] == "NFO"
    assert event["action"] == "SELL"
    assert event["trigger_price"] == 99.5


def test_trade_packets_are_not_published(env):
    # A fill arrives as an ORDER packet too; a TRADE packet would repeat it.
    # RemainingVolume=0 is also what an omitted field reads as, so a TRADE
    # packet alone must never report the order complete.
    _, pb, adapter = env
    adapter._handle_message(_frame(pb, _trade(pb, VolFilledToday=5, RemainingVolume=0)))
    assert _published(adapter) == []
    assert pb.TRADE in adapter._seen_packet_types  # still logged once


def test_a_fill_and_its_trade_in_one_frame_publish_once(env):
    _, pb, adapter = env
    order = _order(
        pb,
        status=pb.PARTIAL_TRADE,
        quantity=10,
        fillQuantity=5,
        remainingQuantity=5,
        avgPrice=800.0,
    )
    adapter._handle_message(_frame(pb, order, _trade(pb, VolFilledToday=5, RemainingVolume=5)))
    [event] = _published(adapter)
    assert event["order_status"] == "open"
    assert event["filled_quantity"] == 5
    assert event["average_price"] == 800.0


@pytest.mark.parametrize(
    "fill, vol, expected",
    [(5, 5, 5), (3, 8, 8), (8, 3, 8), (0, 6, 6), (6, 0, 6)],
)
def test_filled_quantity_is_the_running_total(env, fill, vol, expected):
    # fillQuantity and volFilledToday are both undocumented; if either is the
    # last fill only, the larger one is still the order's total.
    _, pb, adapter = env
    packet = _order(pb, status=pb.PARTIAL_TRADE, quantity=10, fillQuantity=fill, volFilledToday=vol)
    adapter._handle_message(_frame(pb, packet))
    assert _published(adapter)[0]["filled_quantity"] == expected


def test_book_downloads_are_not_published(env):
    _, pb, adapter = env
    adapter._handle_message(
        _frame(pb, _order(pb, isOrderDownload=True), _trade(pb, isTradeDownload=True))
    )
    assert _published(adapter) == []


def test_market_packets_are_ignored_and_order_packets_in_the_same_frame_kept(env):
    _, pb, adapter = env
    tick = pb.GenericDTO(packetType=pb.NSE_CM_ALL, instrumentId=3045)
    tick.mbpData.lastTradedPrice = 800.0
    heartbeat = pb.GenericDTO(packetType=pb.HEARTBEAT)
    adapter._handle_message(_frame(pb, tick, _order(pb), heartbeat))
    assert len(_published(adapter)) == 1


def test_a_bare_generic_dto_frame_is_decoded(env):
    _, pb, adapter = env
    adapter._handle_message(_order(pb).SerializeToString())
    assert len(_published(adapter)) == 1


def test_text_and_garbage_frames_publish_nothing(env):
    _, _, adapter = env
    adapter._handle_message('{"status":"error"}')
    adapter._handle_message(b"\xff\xff\xff\xff")
    assert _published(adapter) == []


def test_a_repeated_state_is_published_once(env):
    _, pb, adapter = env
    adapter._handle_message(_frame(pb, _order(pb, status=pb.ACCEPTED)))
    adapter._handle_message(_frame(pb, _order(pb, status=pb.CONFIRMED)))  # also "open"
    adapter._handle_message(_frame(pb, _order(pb, status=pb.COMPLETE, fillQuantity=1)))
    assert [e["order_status"] for e in _published(adapter)] == ["open", "complete"]


def test_dedupe_memory_is_bounded(env, monkeypatch):
    mod, pb, adapter = env
    monkeypatch.setattr(mod, "_DEDUPE_LIMIT", 3)
    for n in range(10):
        adapter._handle_message(_frame(pb, _order(pb, orderID=str(n))))
    assert len(adapter._last_published) == 3
    assert len(_published(adapter)) == 10


def test_heartbeat_is_the_documented_frame(env):
    _, _, adapter = env
    ws = MagicMock()
    adapter.send_heartbeat(ws)
    ws.send.assert_called_once_with(json.dumps({"heart_beat": True}))
    assert adapter.heartbeat_interval() == 10


def test_url_rereads_the_token_and_carries_token_and_api_key(env, monkeypatch):
    mod, _, adapter = env
    monkeypatch.setattr(mod, "get_auth_token", lambda user_id, bypass_cache=False: "fresh")
    monkeypatch.setenv("BROKER_API_KEY", "app-key")
    url = adapter.get_ws_url()
    assert "token=fresh" in url
    assert "api_key=app-key" in url
    assert url.startswith("wss://")
    assert adapter.get_headers()["Authorization"] == "fresh"


@pytest.mark.parametrize(
    "mod, factory",
    [
        (sky_mod, "create_hdfcsky_order_adapter"),
        (sec_mod, "create_hdfcsecurities_order_adapter"),
    ],
)
def test_factory_needs_a_session(monkeypatch, mod, factory):
    monkeypatch.setattr(mod, "get_auth_token", lambda user_id, bypass_cache=False: None)
    assert getattr(mod, factory)("u1") is None
    monkeypatch.setattr(mod, "get_auth_token", lambda user_id, bypass_cache=False: "tok")
    assert getattr(mod, factory)("u1").access_token == "tok"


def test_registry_streams_both_brokers_instead_of_polling():
    from services import order_update_service as svc

    assert "hdfcsky" not in svc._POLLING_BROKERS
    assert "hdfcsecurities" not in svc._POLLING_BROKERS
    assert svc._BROKER_FACTORIES["hdfcsky"] == (
        "broker.hdfcsky.streaming.hdfcsky_order_adapter",
        "create_hdfcsky_order_adapter",
    )
    assert svc._BROKER_FACTORIES["hdfcsecurities"] == (
        "broker.hdfcsecurities.streaming.hdfcsecurities_order_adapter",
        "create_hdfcsecurities_order_adapter",
    )
