"""Arguments a model sends to the agent's order, account, live and Flow tools.

agno builds each tool's JSON schema from its signature and wraps the method in
pydantic's ``validate_call``, so a type hint narrower than what models really
send rejects the call before the body runs. For an order tool that rejection
lands after the operator approved, and every one costs a second approval. These
tests pin the widened hints, the alias maps and the refusals that stay hard.

Nothing here reaches a broker or places an order: every service the tools would
call is replaced, and a stand-in for the smart order service fails the test if
it is ever called.
"""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import pytest

pytest.importorskip("agno", reason="the agent's toolkits need agno")

from agno.exceptions import RetryAgentRun  # noqa: E402
from agno.tools.function import Function  # noqa: E402

from services.agent.tools import account as account_mod  # noqa: E402
from services.agent.tools import flow_gen as flow_gen_mod  # noqa: E402
from services.agent.tools import live as live_mod  # noqa: E402
from services.agent.tools import order_vocab as vocab_mod  # noqa: E402
from services.agent.tools import orders as orders_mod  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bare_orders_toolkit() -> orders_mod.OrdersToolkit:
    """An OrdersToolkit with no context, enough for the pure validators."""
    toolkit = orders_mod.OrdersToolkit.__new__(orders_mod.OrdersToolkit)
    toolkit.strategy = orders_mod.AGENT_STRATEGY
    return toolkit


def _entrypoint(bound_method):
    """The callable agno runs, pydantic validation included."""
    return Function.from_callable(bound_method).entrypoint


def _build(toolkit, **overrides):
    order = {
        "symbol": "SBIN",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 10,
        "product": "MIS",
        "price_type": "MARKET",
        "price": 0.0,
        "trigger_price": 0.0,
    }
    order.update(overrides)
    return toolkit._build_order(**order)


# ---------------------------------------------------------------------------
# Alias maps
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("INTRADAY", "MIS"),
        ("intraday", "MIS"),
        ("DELIVERY", "CNC"),
        ("CARRYFORWARD", "NRML"),
        ("NORMAL", "NRML"),
        (" mis ", "MIS"),
        ("CNC", "CNC"),
        ("BOGUS", "BOGUS"),
    ],
)
def test_product_aliases(given, expected):
    assert vocab_mod.canonical_product(given) == expected


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("SL_M", "SL-M"),
        ("SL M", "SL-M"),
        ("SLM", "SL-M"),
        ("sl-m", "SL-M"),
        ("STOPLOSS_MARKET", "SL-M"),
        ("STOP_LOSS_MARKET", "SL-M"),
        ("STOPLOSS", "SL"),
        ("Stop Loss", "SL"),
        ("STOPLOSS_LIMIT", "SL"),
        ("MARKET", "MARKET"),
        ("LIMIT", "LIMIT"),
        ("SL", "SL"),
        ("BOGUS", "BOGUS"),
    ],
)
def test_price_type_aliases(given, expected):
    assert vocab_mod.canonical_price_type(given) == expected


@pytest.mark.parametrize(
    ("given", "expected"), [("B", "BUY"), ("s", "SELL"), ("buy", "BUY"), ("X", "X")]
)
def test_action_aliases(given, expected):
    assert vocab_mod.canonical_action(given) == expected


def test_the_read_only_toolkit_does_not_import_the_mutating_one():
    """account.py shares the vocabulary through order_vocab, never through orders."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(account_mod))
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "services.agent.tools.orders" not in imported
    assert "services.agent.tools.order_vocab" in imported
    assert account_mod.canonical_product is vocab_mod.canonical_product
    assert orders_mod.canonical_product is vocab_mod.canonical_product


def test_the_validators_apply_the_aliases():
    order = _build(
        _bare_orders_toolkit(),
        action="s",
        product="intraday",
        price_type="SL M",
        trigger_price=1440.0,
    )
    assert order["action"] == "SELL"
    assert order["product"] == "MIS"
    assert order["pricetype"] == "SL-M"
    assert order["trigger_price"] == 1440.0


def test_product_stays_required_in_the_schema():
    toolkit = _bare_orders_toolkit()
    for name in ("place_order", "place_smart_order", "modify_order", "close_position"):
        required = Function.from_callable(getattr(toolkit, name)).parameters["required"]
        assert "product" in required, name


# ---------------------------------------------------------------------------
# Null prices and numeric order ids pass pydantic
# ---------------------------------------------------------------------------


def test_null_price_on_a_market_order_reaches_the_body(monkeypatch):
    toolkit = _bare_orders_toolkit()
    seen = {}

    def capture(tool, args, plan_factory, **attributes):
        seen.update(args)
        return "ran"

    monkeypatch.setattr(toolkit, "_run_mutation", capture, raising=False)
    run = _entrypoint(toolkit.place_order)

    result = run(
        symbol="SBIN",
        exchange="NSE",
        action="BUY",
        quantity=1,
        product="MIS",
        price_type="MARKET",
        price=None,
        trigger_price=None,
    )

    assert result == "ran"
    assert seen["price"] is None and seen["trigger_price"] is None


def test_null_prices_are_read_as_zero():
    order = _build(_bare_orders_toolkit(), price=None, trigger_price=None)
    assert order["price"] == 0.0 and order["trigger_price"] == 0.0


def test_null_quantity_on_a_smart_order_reaches_the_body(monkeypatch):
    toolkit = _bare_orders_toolkit()
    monkeypatch.setattr(toolkit, "_run_mutation", lambda *a, **k: "ran", raising=False)
    run = _entrypoint(toolkit.place_smart_order)

    assert (
        run(
            symbol="SBIN",
            exchange="NSE",
            action="BUY",
            quantity=None,
            position_size=10,
            product="MIS",
        )
        == "ran"
    )


@pytest.mark.parametrize("tool", ["cancel_order", "modify_order"])
def test_a_numeric_order_id_reaches_the_body(monkeypatch, tool):
    toolkit = _bare_orders_toolkit()
    monkeypatch.setattr(toolkit, "_run_mutation", lambda *a, **k: "ran", raising=False)
    run = _entrypoint(getattr(toolkit, tool))
    kwargs = {"order_id": 240307000616990}
    if tool == "modify_order":
        kwargs.update(
            symbol="SBIN",
            exchange="NSE",
            action="BUY",
            quantity=1,
            product="MIS",
            price_type="LIMIT",
            price=100.0,
        )
    assert run(**kwargs) == "ran"


def test_order_id_is_normalised_to_stripped_text():
    toolkit = _bare_orders_toolkit()
    assert toolkit._order_id(240307000616990) == "240307000616990"
    assert toolkit._order_id("  A1  ") == "A1"
    with pytest.raises(RetryAgentRun):
        toolkit._order_id(True)


def test_get_order_status_accepts_a_numeric_id(monkeypatch):
    toolkit = account_mod.AccountToolkit.__new__(account_mod.AccountToolkit)
    toolkit.api_key = "k"
    toolkit.analyzer_mode = False
    looked_up = {}

    def fake_call_service(fn, data, **kwargs):
        looked_up.update(data)
        return True, {"status": "success", "data": {"orderid": data["orderid"]}}, 200

    monkeypatch.setattr(account_mod, "call_service", fake_call_service)
    monkeypatch.setattr(account_mod, "current_mode", lambda fallback=False: "live")
    fake_service = types.ModuleType("services.orderstatus_service")
    fake_service.get_order_status = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "services.orderstatus_service", fake_service)

    result = _entrypoint(toolkit.get_order_status)(order_id=250408000989443)

    assert looked_up["orderid"] == "250408000989443"
    payload = json.loads(result[result.index("{") : result.rindex("}") + 1])
    assert payload["found"] is True and payload["order_id"] == "250408000989443"


# ---------------------------------------------------------------------------
# Prices the price type ignores stay a hard refusal, naming the field to drop
# ---------------------------------------------------------------------------


def test_a_price_on_a_market_order_is_refused_naming_the_field():
    with pytest.raises(RetryAgentRun) as caught:
        _build(_bare_orders_toolkit(), price_type="MARKET", price=1450.5)
    message = str(caught.value)
    assert "'price'" in message and "Drop price" in message


def test_a_trigger_on_a_limit_order_is_refused_naming_the_field():
    with pytest.raises(RetryAgentRun) as caught:
        _build(_bare_orders_toolkit(), price_type="LIMIT", price=100.0, trigger_price=99.0)
    message = str(caught.value)
    assert "'trigger_price'" in message and "Drop trigger_price" in message


# ---------------------------------------------------------------------------
# EXCHANGE:SYMBOL and index codes
# ---------------------------------------------------------------------------


def test_prefix_fills_an_empty_exchange():
    assert vocab_mod.split_exchange_prefix("nse:sbin", "") == ("SBIN", "NSE")
    assert vocab_mod.split_exchange_prefix("NSE:SBIN", None) == ("SBIN", "NSE")


def test_prefix_agreeing_with_the_exchange_is_accepted():
    assert vocab_mod.split_exchange_prefix("NFO:NIFTY28MAR2420800CE", "nfo") == (
        "NIFTY28MAR2420800CE",
        "NFO",
    )


def test_prefix_disagreeing_with_the_exchange_is_refused():
    with pytest.raises(RetryAgentRun) as caught:
        vocab_mod.split_exchange_prefix("NSE:SBIN", "BSE")
    assert "disagree" in str(caught.value)


def test_a_bare_symbol_is_left_alone():
    assert vocab_mod.split_exchange_prefix("SBIN", "NSE") == ("SBIN", "NSE")


def test_an_order_built_from_a_prefixed_symbol():
    order = _build(_bare_orders_toolkit(), symbol="NSE:SBIN", exchange="")
    assert order["symbol"] == "SBIN" and order["exchange"] == "NSE"


@pytest.mark.parametrize(
    ("exchange", "venue"), [("NSE_INDEX", "NFO"), ("BSE_INDEX", "BFO"), ("MCX_INDEX", "MCX")]
)
def test_an_index_order_names_the_tradable_venue(exchange, venue):
    with pytest.raises(RetryAgentRun) as caught:
        _build(_bare_orders_toolkit(), symbol="NIFTY", exchange=exchange)
    message = str(caught.value)
    assert venue in message and "future" in message and "option" in message


def test_a_global_index_order_says_there_is_no_contract():
    refusal = orders_mod.index_refusal("GLOBAL_INDEX")
    assert refusal and "no contract" in refusal
    assert orders_mod.index_refusal("NSE") is None


# ---------------------------------------------------------------------------
# Square-off that reads zero is not reported as closed
# ---------------------------------------------------------------------------


class _Guard:
    def __init__(self):
        self.released = 0
        self.committed = 0

    def check_destructive(self, tool, **kwargs):
        return SimpleNamespace(
            allowed=True, code="ok", as_dict=lambda: {"code": "ok"}, as_message=lambda: ""
        )

    def release(self, verdict):
        self.released += 1
        return True

    def commit(self, verdict):
        self.committed += 1
        return True


@pytest.fixture
def closing_toolkit(monkeypatch):
    toolkit = _bare_orders_toolkit()
    toolkit.api_key = "k"
    guard = _Guard()
    audits = []
    sent = []

    monkeypatch.setattr(orders_mod, "_order_services_warmed", True)
    toolkit.audit_attempt = lambda tool, args: 1
    toolkit.audit_result = lambda tool, **kwargs: audits.append(kwargs)
    toolkit._emit = lambda tool, payload, **attrs: dict(payload)
    toolkit._guard = lambda: guard
    toolkit._analyzer_mode = lambda: False
    toolkit._open_position_quantity = lambda symbol, exchange, product: 0

    fake_service = types.ModuleType("services.place_smart_order_service")
    fake_service.place_smart_order = lambda **kwargs: sent.append(kwargs)
    monkeypatch.setitem(sys.modules, "services.place_smart_order_service", fake_service)

    toolkit.test_guard = guard
    toolkit.test_audits = audits
    toolkit.test_sent = sent
    return toolkit


def test_close_position_on_a_zero_read_is_nothing_to_close(closing_toolkit):
    result = closing_toolkit.close_position(symbol="NSE:SBIN", exchange="", product="intraday")

    assert result["ok"] is False
    assert result["status"] == "nothing_to_close"
    assert result["retry"] is False
    assert result["order_ids"] == []
    assert "get_positions" in result["message"]
    assert "does not prove the position is closed" in result["message"]
    assert (result["symbol"], result["exchange"], result["product"]) == ("SBIN", "NSE", "MIS")
    assert closing_toolkit.test_sent == []
    assert closing_toolkit.test_guard.released == 1
    assert closing_toolkit.test_guard.committed == 0
    assert closing_toolkit.test_audits[-1]["ok"] is False
    assert closing_toolkit.test_audits[-1]["response"]["status"] == "nothing_to_close"


def test_close_position_with_a_held_quantity_still_sends(closing_toolkit):
    closing_toolkit._open_position_quantity = lambda symbol, exchange, product: 50
    sys.modules["services.place_smart_order_service"].place_smart_order = lambda **kwargs: (
        closing_toolkit.test_sent.append(kwargs)
        or (True, {"status": "success", "orderid": "A1"}, 200)
    )

    result = closing_toolkit.close_position(symbol="SBIN", exchange="NSE", product="MIS")

    assert result["ok"] is True
    assert closing_toolkit.test_sent[0]["order_data"]["position_size"] == 0
    assert closing_toolkit.test_guard.committed == 1


def test_a_broker_refusal_does_not_invite_a_retry(closing_toolkit):
    closing_toolkit._open_position_quantity = lambda symbol, exchange, product: 50
    sys.modules["services.place_smart_order_service"].place_smart_order = lambda **kwargs: (
        False,
        {"status": "error", "message": "Invalid quantity"},
        400,
    )

    result = closing_toolkit.close_position(symbol="SBIN", exchange="NSE", product="MIS")

    assert result["ok"] is False and result["retry"] is False
    assert "Invalid quantity" in result["message"]
    assert "call the tool again" not in result["message"]
    assert "HTTP" not in result["message"]
    assert closing_toolkit.test_guard.released == 1


def test_an_unexpected_failure_is_a_sentence_not_an_exception(closing_toolkit):
    def explode(symbol, exchange, product):
        raise KeyError("ltp")

    closing_toolkit._open_position_quantity = explode

    result = closing_toolkit.close_position(symbol="SBIN", exchange="NSE", product="MIS")

    assert result["status"] == "unknown"
    assert "KeyError" not in result["message"]
    assert "do NOT send it again" in result["message"]


def test_get_open_position_note_does_not_claim_the_operator_is_flat(monkeypatch):
    toolkit = account_mod.AccountToolkit.__new__(account_mod.AccountToolkit)
    toolkit.analyzer_mode = False
    toolkit.service_call = lambda fn, data: {"quantity": 0}
    monkeypatch.setattr(account_mod, "current_mode", lambda fallback=False: "live")
    fake_service = types.ModuleType("services.openposition_service")
    fake_service.get_open_position = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "services.openposition_service", fake_service)

    text = toolkit.get_open_position(symbol="SBIN", exchange="NSE", product="intraday")
    payload = json.loads(text[text.index("{") : text.rindex("}") + 1])

    assert payload["product"] == "MIS"
    assert "flat in this contract" not in payload["note"]
    assert "reported no open quantity" in payload["note"]
    assert "get_positions" in payload["note"]


# ---------------------------------------------------------------------------
# Live cards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (1, "LTP"),
        (2, "Quote"),
        (3, "Depth"),
        ("1", "LTP"),
        (" 3 ", "Depth"),
        ("quote", "Quote"),
        (None, "Quote"),
        ("", "Quote"),
    ],
)
def test_normalise_mode_accepts_protocol_numbers(given, expected):
    assert live_mod.normalise_mode(given) == expected


def test_normalise_mode_refuses_an_unknown_mode():
    with pytest.raises(RetryAgentRun):
        live_mod.normalise_mode("FULL")


def test_symbols_argument_reads_a_bare_exchange_symbol():
    assert live_mod.symbols_argument("NSE:INFY") == ["NSE:INFY"]
    assert live_mod.symbols_argument("NSE:INFY, NSE:SBIN") == ["NSE:INFY", "NSE:SBIN"]
    as_json = '[{"symbol": "INFY", "exchange": "NSE"}]'
    assert live_mod.symbols_argument(as_json) == as_json
    listed = [{"symbol": "INFY", "exchange": "NSE"}]
    assert live_mod.symbols_argument(listed) is listed


@pytest.mark.parametrize(
    "symbols",
    [
        "NSE:INFY",
        '[{"symbol": "INFY", "exchange": "NSE"}]',
        {"symbol": "INFY", "exchange": "NSE"},
        [{"symbol": "INFY", "exchange": "NSE", "lots": 2, "note": None}],
        ["NSE:INFY", {"symbol": "SBIN", "exchange": "NSE"}],
    ],
)
def test_stream_quotes_shapes_pass_pydantic(monkeypatch, symbols):
    toolkit = live_mod.LiveToolkit.__new__(live_mod.LiveToolkit)
    reached = []
    monkeypatch.setattr(
        live_mod, "symbol_pairs", lambda value, **kwargs: reached.append(value) or ([], [])
    )
    monkeypatch.setattr(live_mod, "tool_answer", lambda *a, **k: "answered")

    assert _entrypoint(toolkit.stream_quotes)(symbols=symbols, mode=2) == "answered"
    assert reached


def test_stream_combo_accepts_nulls_and_loose_legs(monkeypatch):
    toolkit = live_mod.LiveToolkit.__new__(live_mod.LiveToolkit)
    named = {}
    custom = {}
    toolkit._named_structure = lambda *args: named.update(args=args) or "named"
    toolkit._custom_combo = lambda entries, *args: custom.update(entries=entries) or "custom"
    run = _entrypoint(toolkit.stream_combo)

    assert run(underlying="NIFTY", exchange=None, structure=None, expiry=None, width=None) == (
        "named"
    )
    assert named["args"][4] == 1

    assert run(legs={"symbol": "NIFTY09SEP2624500CE", "side": "SELL", "lots": 2}) == "custom"
    assert run(legs='["NIFTY09SEP2624500CE", "NIFTY09SEP2624500PE"]') == "custom"
    assert len(custom["entries"]) == 2


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------


def test_validate_flow_accepts_an_object(monkeypatch):
    toolkit = flow_gen_mod.FlowGenToolkit.__new__(flow_gen_mod.FlowGenToolkit)
    prepared = []
    monkeypatch.setattr(
        toolkit,
        "_prepare",
        lambda value: prepared.append(value) or ({"nodes": [], "edges": []}, []),
        raising=False,
    )
    monkeypatch.setattr(toolkit, "_reject_if_invalid", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(toolkit, "_result", lambda tool, payload: payload, raising=False)

    result = _entrypoint(toolkit.validate_flow)(workflow_json={"name": "x", "nodes": []})

    assert result["valid"] is True
    assert prepared == [{"name": "x", "nodes": []}]
