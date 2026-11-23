"""The sandbox charges page: brokerage plan, calculator and transaction cost report.

These run the blueprint's own view functions inside a request, against the
isolated sandbox test database, so they cover what a trader's browser reaches:
what is saved, what is refused and in which words, and that the report's
totals are the charges the fills actually paid.
"""

from __future__ import annotations

import csv
import inspect
import io
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
import pytz
from test_gthread_sandbox_support import (
    CAPITAL,
    configs_restored,
    funds_of,
    only_funds_of,
    prepare_databases,
    quote,
    release_sessions,
    remove_symbols,
    reset_user,
    run_in_thread,
    seed_symbols,
)

D = Decimal
USER = "sandbox_charges_api"
OPTION = "CHGTEST27DEC3525000CE"
LOT = 75

#: An option these tests add and remove. Not named after a real underlying, so
#: a row left behind by a killed run cannot change what another test reads.
OPTION_SPEC = {
    "symbol": OPTION,
    "brsymbol": OPTION,
    "name": "CHGTEST",
    "exchange": "NFO",
    "brexchange": "NFO",
    "token": "990001",
    "expiry": "27-DEC-35",
    "strike": 25000.0,
    "lotsize": LOT,
    "instrumenttype": "CE",
    "tick_size": 0.05,
    "contract_value": 1.0,
}


@pytest.fixture(autouse=True)
def charged_account(monkeypatch):
    from database.sandbox_db import SandboxDailyPnL, db_session, set_configs
    from sandbox.charges import config_keys, default_config_values
    from sandbox.execution_engine import ExecutionEngine

    prepare_databases()
    seed_symbols([OPTION_SPEC])
    reset_user(USER)
    SandboxDailyPnL.query.filter_by(user_id=USER).delete()
    db_session.commit()
    release_sessions()
    try:
        with configs_restored(list(config_keys())):
            assert set_configs(default_config_values())
            db_session.remove()
            monkeypatch.setattr(
                ExecutionEngine, "_fetch_quote", lambda self, symbol, exchange: quote(2600)
            )
            yield
    finally:
        SandboxDailyPnL.query.filter_by(user_id=USER).delete()
        db_session.commit()
        release_sessions()
        remove_symbols([OPTION_SPEC])


#: A made-up broker id for a session on a crypto venue. No plugin has this
#: name: the test answers for its type (see on_a_crypto_venue).
CRYPTO_VENUE = "chgtest_crypto_venue"


@pytest.fixture
def on_a_crypto_venue(monkeypatch):
    """Make CRYPTO_VENUE a broker whose plugin says it is a crypto venue."""
    import utils.broker_keys as broker_keys

    real = broker_keys.broker_type
    monkeypatch.setattr(
        broker_keys,
        "broker_type",
        lambda broker: "crypto" if broker == CRYPTO_VENUE else real(broker),
    )
    return CRYPTO_VENUE


def _request(view_name, *, method="GET", query="", body=None, broker=None):
    """Run a sandbox view's own function inside a request, as the logged-in user.

    ``broker`` is the broker the browser is logged in to. Left out, the session
    names none, which reads as a broker on the Indian exchanges.
    """
    from flask import Flask, session

    import blueprints.sandbox as sandbox_views

    view = inspect.unwrap(getattr(sandbox_views, view_name))
    app = Flask(__name__)
    app.secret_key = "test-only"
    kwargs = {"method": method}
    if body is not None:
        kwargs["json"] = body
    with app.test_request_context(f"/{query}", **kwargs):
        session["user"] = USER
        if broker is not None:
            session["broker"] = broker
        response = view()
        status = None
        if isinstance(response, tuple):
            response, status = response
        status = status or response.status_code
        payload = response.get_json() if response.is_json else response.get_data(as_text=True)
        headers = dict(response.headers)
    release_sessions()
    return payload, status, headers


def _fill(action, quantity, price, *, symbol="RELIANCE", exchange="NSE", product="CNC"):
    from sandbox.order_manager import OrderManager

    order = {
        "symbol": symbol,
        "exchange": exchange,
        "action": action,
        "quantity": quantity,
        "price": float(price),
        "price_type": "LIMIT",
        "product": product,
    }
    ok, response, _ = run_in_thread(
        lambda: OrderManager(USER).place_order(order, prefetched_quote=quote(price))
    )
    assert ok, response
    return response["orderid"]


def _ist_today() -> date:
    """The day a fill made now is reported under.

    A fill is stamped with the IST wall clock and the report counts IST days.
    The machine's own date is a day behind that from midnight to 05:30 IST on a
    server kept on UTC, so a test must not take "today" from the machine.
    """
    return datetime.now(pytz.timezone("Asia/Kolkata")).date()


class _ServerClockOnUtc(datetime):
    """04:35 IST on 24 November 2026, as a server kept on UTC reads it.

    Asked for the time with no zone it gives its own wall clock, 23:05 on the
    23rd. Asked for the time in a zone it answers for that zone, as the real
    clock does.
    """

    @classmethod
    def now(cls, tz=None):
        instant = datetime(2026, 11, 23, 23, 5, tzinfo=UTC)
        return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)


def _trades():
    from database.sandbox_db import SandboxTrades, db_session

    db_session.remove()
    rows = [
        {
            "orderid": trade.orderid,
            "total": trade.total_charges,
            "brokerage": trade.brokerage,
            "value": trade.price * trade.quantity,
        }
        for trade in SandboxTrades.query.filter_by(user_id=USER).order_by(SandboxTrades.id).all()
    ]
    db_session.remove()
    return rows


def _plan(broker=None):
    payload, status, _ = _request("api_get_charge_settings", broker=broker)
    assert status == 200, payload
    return payload["data"]


def _segment(plan, key):
    return next(segment for segment in plan["segments"] if segment["key"] == key)


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def test_the_page_opens_on_the_default_plan_with_charges_on():
    plan = _plan()

    assert plan["enabled"] is True
    assert plan["market"] == "indian"
    assert [segment["key"] for segment in plan["segments"]] == [
        "equity_delivery",
        "equity_intraday",
        "fno_futures",
        "fno_options",
        "currency_futures",
        "currency_options",
        "commodity_futures",
        "commodity_options",
    ]
    delivery = _segment(plan, "equity_delivery")
    assert (delivery["flat"], delivery["percent"]) == ("20", "2.5")
    assert delivery["summary"] == (
        "20 per executed order or 2.5% of the trade value, whichever is lower"
    )
    intraday = _segment(plan, "equity_intraday")
    assert (intraday["flat"], intraday["percent"]) == ("20", "0.1")
    assert _segment(plan, "fno_options")["summary"] == "20 per executed order"

    # The statutory schedule is shown, so a trader can see what is added on top.
    statutory = _segment(plan, "fno_options")["statutory"]
    assert statutory["stt_sell"] == "0.15"
    assert statutory["exchange_txn"] == {"NFO": "0.03553", "BFO": "0.0325"}
    assert statutory["gst"] == "18"
    assert plan["limits"] == {"flat_max": "1000", "percent_max": "5"}
    assert plan["statutory_as_of"]


def test_a_crypto_venue_is_shown_the_crypto_plan_and_nothing_from_the_indian_one(
    on_a_crypto_venue,
):
    """A trader is on one market or the other, and is shown that one alone."""
    plan = _plan(broker=on_a_crypto_venue)

    assert plan["market"] == "crypto"
    assert [segment["key"] for segment in plan["segments"]] == ["crypto_futures", "crypto_options"]
    perpetual = _segment(plan, "crypto_futures")
    assert (perpetual["flat"], perpetual["percent"]) == ("0", "0")
    assert perpetual["summary"] == "No brokerage"
    assert perpetual["exchanges"] == ["CRYPTO"]
    # Nothing of the Indian schedule is added to a crypto trade.
    statutory = perpetual["statutory"]
    assert (statutory["stt_buy"], statutory["stt_sell"], statutory["stamp_buy"]) == ("0", "0", "0")
    assert (statutory["sebi"], statutory["gst"], statutory["exchange_txn"]) == ("0", "0", {})

    # And the same install, asked by a browser on an Indian broker, shows no crypto.
    indian = _plan()
    assert indian["market"] == "indian"
    assert not [s for s in indian["segments"] if s["key"].startswith("crypto")]
    assert len(indian["segments"]) + len(plan["segments"]) == 10


def test_a_save_and_a_reset_answer_with_the_browsers_own_market(on_a_crypto_venue):
    """The page adopts what a save returns, so it must not return the other market."""
    saved, status, _ = _request(
        "api_save_charge_settings",
        method="POST",
        body={"segments": {"crypto_futures": {"flat": "0", "percent": "0.05"}}},
        broker=on_a_crypto_venue,
    )
    assert status == 200, saved
    assert saved["data"]["market"] == "crypto"
    assert [segment["key"] for segment in saved["data"]["segments"]] == [
        "crypto_futures",
        "crypto_options",
    ]
    assert _segment(saved["data"], "crypto_futures")["percent"] == "0.05"

    reset, status, _ = _request("api_reset_charge_settings", method="POST", body={})
    assert status == 200, reset
    assert reset["data"]["market"] == "indian"
    assert len(reset["data"]["segments"]) == 8
    # The reset reached the crypto plan too, though this browser is not shown it.
    assert _segment(_plan(broker=on_a_crypto_venue), "crypto_futures")["percent"] == "0"


def test_each_segment_lists_its_exchanges_main_exchange_first():
    """The calculator opens on the first, and it has to be NSE, NFO, CDS and MCX.

    The rates travel as a JSON object, and the server sorts an object's keys,
    so the page read BSE and BFO first and every card opened on the exchange
    fewer traders use, showing an exchange transaction charge that did not
    match the calculator a trader checked it against.
    """
    plan = _plan()

    assert {s["key"]: s["exchanges"] for s in plan["segments"]} == {
        "equity_delivery": ["NSE", "BSE"],
        "equity_intraday": ["NSE", "BSE"],
        "fno_futures": ["NFO", "BFO"],
        "fno_options": ["NFO", "BFO"],
        "currency_futures": ["CDS", "BCD"],
        "currency_options": ["CDS", "BCD"],
        "commodity_futures": ["MCX", "NCDEX", "NCO"],
        "commodity_options": ["MCX", "NCDEX", "NCO"],
    }
    for segment in plan["segments"]:
        # Every exchange listed has a rate, and none is left out.
        assert sorted(segment["exchanges"]) == sorted(segment["statutory"]["exchange_txn"])
    # What goes wrong without the list: the keys as they are sent, sorted.
    assert sorted(_segment(plan, "equity_intraday")["statutory"]["exchange_txn"])[0] == "BSE"


def test_a_saved_plan_comes_back_as_saved_and_reads_as_a_sentence():
    payload, status, _ = _request(
        "api_save_charge_settings",
        method="POST",
        body={
            "enabled": True,
            "segments": {
                "equity_delivery": {"flat": "0", "percent": "0.5"},
                "fno_options": {"flat": "10", "percent": "0"},
            },
        },
    )

    assert status == 200 and payload["status"] == "success", payload
    assert payload["message"] == "Charges saved. They apply from the next trade."
    plan = _plan()
    assert payload["data"] == plan
    delivery = _segment(plan, "equity_delivery")
    assert (delivery["flat"], delivery["percent"]) == ("0", "0.5")
    assert delivery["summary"] == "0.5% of the trade value"
    assert _segment(plan, "fno_options")["summary"] == "10 per executed order"
    # A segment that was not sent keeps its plan.
    assert _segment(plan, "equity_intraday")["flat"] == "20"


def test_one_bad_value_saves_nothing_at_all():
    """A plan is saved whole. Half of one would charge trades under a mixture."""
    payload, status, _ = _request(
        "api_save_charge_settings",
        method="POST",
        body={
            "enabled": False,
            "segments": {
                "equity_delivery": {"flat": "5", "percent": "0.2"},
                "fno_futures": {"flat": "20", "percent": "30"},
            },
        },
    )

    assert status == 400 and payload["status"] == "error"
    assert payload["message"] == (
        "F&O Futures: the percentage cannot be more than 5. Enter 0.03 for 0.03%, not 3."
    )
    plan = _plan()
    assert plan["enabled"] is True
    delivery = _segment(plan, "equity_delivery")
    assert (delivery["flat"], delivery["percent"]) == ("20", "2.5")


@pytest.mark.parametrize(
    "body,fragment",
    [
        ({"segments": {"equity_intraday": {"flat": "-1", "percent": "0"}}}, "cannot be negative"),
        ({"segments": {"equity_intraday": {"flat": "abc", "percent": "0"}}}, "enter a number"),
        ({"segments": {"equity_intraday": {"flat": "20"}}}, "enter a number"),
        ({"segments": {"penny_stocks": {"flat": "20", "percent": "0"}}}, "not on the rate card"),
        ({"segments": {"equity_intraday": "20"}}, "could not be read"),
        ({"segments": ["equity_intraday"]}, "could not be read"),
        ({"enabled": "sometimes"}, "switched on or off"),
        ({"enabled": 1}, "switched on or off"),
        ({}, "nothing to save"),
        (["not", "a", "plan"], "could not be read"),
    ],
)
def test_what_the_page_refuses_and_how_it_says_so(body, fragment):
    payload, status, _ = _request("api_save_charge_settings", method="POST", body=body)

    assert status == 400 and payload["status"] == "error"
    assert fragment in payload["message"]
    # Never a code, an exception name or a field path.
    for technical in ("Exception", "Error:", "400", "KeyError", "config_key", "segments["):
        assert technical not in payload["message"]


def test_switching_charges_off_makes_the_next_fill_free_and_on_again_charges_it():
    payload, status, _ = _request(
        "api_save_charge_settings", method="POST", body={"enabled": False}
    )
    assert status == 200, payload
    assert _plan()["enabled"] is False

    _fill("BUY", 50, D("2500"))
    assert _trades()[0]["total"] == 0
    assert funds_of(USER)["available"] + funds_of(USER)["used"] == CAPITAL

    payload, status, _ = _request("api_save_charge_settings", method="POST", body={"enabled": True})
    assert status == 200, payload
    _fill("BUY", 50, D("2500"))
    assert _trades()[1]["total"] == D("172.28")
    # The plan itself was never touched by the switch.
    assert _segment(_plan(), "equity_delivery")["flat"] == "20"


def test_reset_restores_the_defaults_and_touches_no_trade_or_balance():
    _request(
        "api_save_charge_settings",
        method="POST",
        body={"enabled": False, "segments": {"equity_delivery": {"flat": "1", "percent": "0"}}},
    )
    _request("api_save_charge_settings", method="POST", body={"enabled": True})
    _fill("BUY", 50, D("2500"))
    before = funds_of(USER)
    trades_before = _trades()

    payload, status, _ = _request("api_reset_charge_settings", method="POST", body={})

    assert status == 200 and payload["status"] == "success", payload
    plan = _plan()
    assert plan["enabled"] is True
    delivery = _segment(plan, "equity_delivery")
    assert (delivery["flat"], delivery["percent"]) == ("20", "2.5")
    assert funds_of(USER) == before
    assert _trades() == trades_before


def test_the_general_settings_route_holds_the_plan_to_the_same_rules():
    """/sandbox/update writes any one key. It must not store what the page refuses."""
    payload, status, _ = _request(
        "update_config",
        method="POST",
        body={"config_key": "brokerage_fno_options_flat", "config_value": "-5"},
    )
    assert status == 400 and "cannot be negative" in payload["message"]

    payload, status, _ = _request(
        "update_config",
        method="POST",
        body={"config_key": "charges_enabled", "config_value": "perhaps"},
    )
    assert status == 400

    payload, status, _ = _request(
        "update_config",
        method="POST",
        body={"config_key": "brokerage_fno_options_flat", "config_value": "15"},
    )
    assert status == 200, payload
    assert _segment(_plan(), "fno_options")["flat"] == "15"


# ---------------------------------------------------------------------------
# The calculator
# ---------------------------------------------------------------------------


def test_the_calculator_reproduces_the_reference_intraday_trade():
    """The reference plan and its worked example: 200.62 on a 39,799.38 net."""
    payload, status, _ = _request(
        "api_estimate_charges",
        method="POST",
        body={
            "segment": "equity_intraday",
            "exchange": "NSE",
            "buy_price": "1000",
            "sell_price": "1100",
            "quantity": "400",
            "flat": "20",
            "percent": "0.03",
        },
    )

    assert status == 200, payload
    data = payload["data"]
    assert data["turnover"] == 840000.0
    assert data["total"] == {
        "brokerage": 40.0,
        "stt": 110.0,
        "exchange_charges": 25.79,
        "sebi_charges": 0.84,
        "stamp_duty": 12.0,
        "gst": 11.99,
        "total_charges": 200.62,
    }
    assert data["gross_pnl"] == 40000.0
    assert data["net_pnl"] == 39799.38
    assert data["points_to_breakeven"] == 0.5
    # One figure per line, for the two orders together: no per-side figures
    # that could add up to something else.
    assert "buy" not in data and "sell" not in data


INTRADAY_TRADE = {
    "segment": "equity_intraday",
    "exchange": "NSE",
    "buy_price": "1000",
    "sell_price": "1100",
    "quantity": "400",
}
PERPETUAL_TRADE = {
    "segment": "crypto_futures",
    "exchange": "CRYPTO",
    "buy_price": "60000",
    "sell_price": "60500",
    "quantity": "1",
}


def test_the_calculator_prices_only_the_market_of_the_broker_logged_in(on_a_crypto_venue):
    """An Indian broker's calculator does not price crypto, nor the other way round."""
    crypto = on_a_crypto_venue

    refused, status, _ = _request("api_estimate_charges", method="POST", body=PERPETUAL_TRADE)
    assert status == 400
    assert refused["message"] == (
        "Crypto Futures and Spot is not traded with the broker you are logged in to."
    )

    refused, status, _ = _request(
        "api_estimate_charges", method="POST", body=INTRADAY_TRADE, broker=crypto
    )
    assert status == 400
    assert refused["message"] == (
        "Equity Intraday is not traded with the broker you are logged in to."
    )

    # Each prices its own.
    priced, status, _ = _request("api_estimate_charges", method="POST", body=INTRADAY_TRADE)
    assert status == 200 and priced["data"]["total"]["stt"] == 110.0

    priced, status, _ = _request(
        "api_estimate_charges", method="POST", body=PERPETUAL_TRADE, broker=crypto
    )
    assert status == 200, priced
    assert priced["data"]["total"]["total_charges"] == 0.0  # no fee entered yet
    assert priced["data"]["net_pnl"] == 500.0


def test_without_a_plan_in_the_request_the_calculator_uses_the_saved_one():
    _request(
        "api_save_charge_settings",
        method="POST",
        body={"segments": {"equity_delivery": {"flat": "0", "percent": "0.5"}}},
    )

    payload, status, _ = _request(
        "api_estimate_charges",
        method="POST",
        body={
            "segment": "equity_delivery",
            "exchange": "NSE",
            "buy_price": "1000",
            "sell_price": "1100",
            "quantity": "400",
        },
    )

    assert status == 200, payload
    assert payload["data"]["brokerage_plan"] == "0.5% of the trade value"
    assert payload["data"]["total"]["brokerage"] == 2000.0 + 2200.0


@pytest.mark.parametrize(
    "change,fragment",
    [
        ({"segment": "nonsense"}, "Choose a segment"),
        ({"exchange": "MCX"}, "trades on NSE or BSE"),
        ({"buy_price": "0"}, "above zero"),
        ({"sell_price": "abc"}, "above zero"),
        ({"quantity": "-5"}, "quantity above zero"),
        ({"flat": "20", "percent": "50"}, "percentage cannot be more than"),
    ],
)
def test_the_calculator_asks_for_what_is_missing_in_plain_words(change, fragment):
    body = {
        "segment": "equity_intraday",
        "exchange": "NSE",
        "buy_price": "1000",
        "sell_price": "1100",
        "quantity": "400",
    }
    body.update(change)

    payload, status, _ = _request("api_estimate_charges", method="POST", body=body)

    assert status == 400 and fragment in payload["message"]


# ---------------------------------------------------------------------------
# The transaction cost report
# ---------------------------------------------------------------------------


def _three_fills():
    _fill("BUY", 50, D("2500"))
    _fill("SELL", 50, D("2600"))
    _fill("BUY", LOT, D("100"), symbol=OPTION, exchange="NFO", product="NRML")


def test_the_report_totals_are_what_the_fills_paid():
    _three_fills()
    trades = _trades()
    paid = sum(trade["total"] for trade in trades)
    today = _ist_today().isoformat()

    payload, status, _ = _request("api_cost_report")

    assert status == 200, payload
    report = payload["data"]
    assert report["trades_total"] == 3 and report["trades_listed"] == 3
    assert report["totals"]["trades"] == 3
    assert D(str(report["totals"]["total_charges"])) == paid
    assert D(str(report["totals"]["brokerage"])) == sum(trade["brokerage"] for trade in trades)
    assert D(str(report["totals"]["turnover"])) == sum(trade["value"] for trade in trades)
    # The balance agrees with the report: this is the money that left it.
    assert funds_of(USER)["charges"] == paid

    # Every component adds up to the total, on every line of the report.
    parts = ("brokerage", "stt", "exchange_charges", "sebi_charges", "stamp_duty", "gst")
    for line in [report["totals"], *report["by_segment"], *report["by_day"], *report["trades"]]:
        assert round(sum(line[name] for name in parts), 2) == line["total_charges"]

    assert [bucket["segment"] for bucket in report["by_segment"]] == [
        "equity_delivery",
        "fno_options",
    ]
    assert [bucket["label"] for bucket in report["by_segment"]] == [
        "Equity Delivery",
        "F&O Options",
    ]
    assert report["by_segment"][0]["trades"] == 2
    assert (
        D(str(report["by_segment"][0]["total_charges"])) == trades[0]["total"] + trades[1]["total"]
    )
    assert D(str(report["by_segment"][1]["total_charges"])) == trades[2]["total"]

    assert [day["date"] for day in report["by_day"]] == [today]
    assert report["by_day"][0]["trades"] == 3

    # Newest first, each with its own breakdown.
    assert [row["orderid"] for row in report["trades"]] == [
        trade["orderid"] for trade in reversed(trades)
    ]
    newest = report["trades"][0]
    assert newest["symbol"] == OPTION and newest["segment_label"] == "F&O Options"
    assert newest["turnover"] == 7500.0
    assert newest["brokerage"] == 20.0 and newest["stt"] == 0.0


def test_a_share_whose_name_ends_like_an_option_is_reported_as_a_share():
    """RELIANCE ends in CE. The report groups by exchange first, as the charge did."""
    _fill("BUY", 50, D("2500"))

    report = _request("api_cost_report")[0]["data"]

    assert [bucket["segment"] for bucket in report["by_segment"]] == ["equity_delivery"]
    assert report["trades"][0]["segment"] == "equity_delivery"


def test_the_list_is_cut_but_the_totals_never_are():
    from sandbox.charge_manager import cost_report

    _three_fills()
    paid = sum(trade["total"] for trade in _trades())
    today = _ist_today()

    report = cost_report(USER, today, today, limit=1)
    release_sessions()

    assert report["trades_listed"] == 1 and len(report["trades"]) == 1
    assert report["trades_total"] == 3
    assert D(str(report["totals"]["total_charges"])) == paid


def test_a_fill_before_0530_ist_is_reported_under_its_ist_day(monkeypatch):
    """A server kept on UTC is a day behind IST from midnight to 05:30 IST.

    The fill and the report must both go by the IST day and never by the
    server's own date. Two tests above once took "today" from the machine and
    failed in CI at 23:04 UTC, which is 04:34 IST the next day. This one holds
    the clock at that hour, so it says the same thing whenever it runs.
    """
    from sandbox import charge_manager, execution_engine

    monkeypatch.setattr(execution_engine, "datetime", _ServerClockOnUtc)
    monkeypatch.setattr(charge_manager, "datetime", _ServerClockOnUtc)
    assert _ServerClockOnUtc.now().date() == date(2026, 11, 23)

    _fill("BUY", 50, D("2500"))

    by_default = _request("api_cost_report")[0]["data"]
    ist_day = _request("api_cost_report", query="?from=2026-11-24&to=2026-11-24")[0]["data"]
    server_day = _request("api_cost_report", query="?from=2026-11-23&to=2026-11-23")[0]["data"]

    assert by_default["to"] == "2026-11-24"
    assert [day["date"] for day in by_default["by_day"]] == ["2026-11-24"]
    assert ist_day["trades_total"] == 1
    assert server_day["trades_total"] == 0


def test_a_range_is_whole_ist_days_and_trades_outside_it_are_left_out():
    from database.sandbox_db import SandboxTrades, db_session

    _fill("BUY", 50, D("2500"))
    # Move the trade to a known day, one second before midnight.
    SandboxTrades.query.filter_by(user_id=USER).update(
        {"trade_timestamp": datetime(2026, 11, 2, 23, 59, 59)}
    )
    db_session.commit()
    db_session.remove()

    inside = _request("api_cost_report", query="?from=2026-11-02&to=2026-11-02")[0]["data"]
    after = _request("api_cost_report", query="?from=2026-11-03&to=2026-11-30")[0]["data"]
    before = _request("api_cost_report", query="?from=2026-10-01&to=2026-11-01")[0]["data"]

    assert inside["trades_total"] == 1 and inside["by_day"][0]["date"] == "2026-11-02"
    assert inside["from"] == "2026-11-02" and inside["to"] == "2026-11-02"
    for empty in (after, before):
        assert empty["trades_total"] == 0
        assert empty["trades"] == [] and empty["by_day"] == [] and empty["by_segment"] == []
        assert empty["totals"]["total_charges"] == 0.0


def test_with_no_dates_the_report_covers_the_last_thirty_days():
    from sandbox.charge_manager import REPORT_DEFAULT_DAYS, parse_report_range

    today = date(2026, 11, 23)
    assert parse_report_range("", "", today=today) == (date(2026, 10, 25), today, None)
    assert (today - date(2026, 10, 25)).days == REPORT_DEFAULT_DAYS - 1
    assert parse_report_range("2026-11-01", None, today=today) == (date(2026, 11, 1), today, None)


@pytest.mark.parametrize(
    "query,fragment",
    [
        ("?from=23-11-2026", "Dates must look like"),
        ("?to=yesterday", "Dates must look like"),
        ("?from=2026-11-20&to=2026-11-10", "start date is after the end date"),
    ],
)
def test_a_date_the_report_cannot_read_is_explained(query, fragment):
    for view in ("api_cost_report", "export_cost_report"):
        payload, status, _ = _request(view, query=query)
        assert status == 400 and fragment in payload["message"], view


def test_the_export_lists_every_trade_with_its_breakdown():
    from sandbox.charge_manager import REPORT_CSV_COLUMNS

    _three_fills()
    trades = _trades()

    body, status, headers = _request("export_cost_report")

    assert status == 200
    assert headers["Content-Type"].startswith("text/csv")
    assert "sandbox_transaction_costs_" in headers["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(body)))
    assert rows[0] == [heading for heading, _key in REPORT_CSV_COLUMNS]
    assert rows[0][-8:] == [
        "Brokerage",
        "STT/CTT",
        "Exchange Charges",
        "SEBI Charges",
        "Stamp Duty",
        "GST",
        "Total Charges",
        "Strategy",
    ]
    assert len(rows) == 1 + 3
    total_column = rows[0].index("Total Charges")
    # Oldest first, the order a ledger is read in.
    assert [D(row[total_column]) for row in rows[1:]] == [trade["total"] for trade in trades]
    assert rows[1][rows[0].index("Segment")] == "Equity Delivery"


def test_an_export_with_nothing_in_it_says_so_instead_of_downloading_headings():
    payload, status, _ = _request("export_cost_report", query="?from=2020-01-01&to=2020-01-31")

    assert status == 404
    assert payload["message"] == "There are no trades between those dates."


def test_another_users_trades_are_not_in_the_report():
    from database.sandbox_db import SandboxTrades, db_session

    _fill("BUY", 50, D("2500"))
    SandboxTrades.query.filter_by(user_id="someone_else_charges").delete()
    db_session.add(
        SandboxTrades(
            tradeid="TRADE-OTHER-USER-CHARGES",
            orderid="OTHER-1",
            user_id="someone_else_charges",
            symbol="INFY",
            exchange="NSE",
            action="BUY",
            quantity=1,
            price=D("1500.00"),
            product="CNC",
            trade_timestamp=datetime.now(),
            total_charges=D("999.00"),
            brokerage=D("999.00"),
        )
    )
    db_session.commit()
    db_session.remove()
    try:
        report = _request("api_cost_report")[0]["data"]
        assert report["trades_total"] == 1
        assert report["totals"]["total_charges"] == 172.28
    finally:
        SandboxTrades.query.filter_by(user_id="someone_else_charges").delete()
        db_session.commit()
        db_session.remove()


# ---------------------------------------------------------------------------
# P&L page, resets and the daily figures
# ---------------------------------------------------------------------------


def test_the_pnl_page_shows_the_charges_beside_a_gross_pnl():
    _fill("BUY", 50, D("2500"))
    _fill("SELL", 50, D("2600"))
    charges = D("172.28") + D("158.46")

    payload, status, _ = _request("api_my_pnl_data")

    assert status == 200, payload
    summary = payload["data"]["summary"]
    assert summary["today_realized_pnl"] == 5000.0  # gross, as the position book has it
    assert summary["today_charges"] == float(charges)
    assert summary["total_charges"] == float(charges)
    assert summary["today_net_mtm"] == float(D("5000") - charges)
    assert summary["all_time_net_realized_pnl"] == float(D("5000") - charges)
    assert sorted(trade["charges"] for trade in payload["data"]["trades"]) == [158.46, 172.28]


def test_resetting_the_sandbox_clears_the_charges_and_restores_the_plan(monkeypatch):
    import blueprints.sandbox as sandbox_views

    monkeypatch.setattr(sandbox_views, "gthread_active", lambda: False)
    _request(
        "api_save_charge_settings",
        method="POST",
        body={"enabled": False, "segments": {"fno_options": {"flat": "5", "percent": "0"}}},
    )
    _request("api_save_charge_settings", method="POST", body={"enabled": True})
    _fill("BUY", 50, D("2500"))
    assert funds_of(USER)["charges"] == D("172.28")

    reset_keys = [
        "starting_capital",
        "reset_day",
        "reset_time",
        "order_check_interval",
        "mtm_update_interval",
        "nse_bse_square_off_time",
        "cds_bcd_square_off_time",
        "mcx_square_off_time",
        "ncdex_square_off_time",
        "equity_mis_leverage",
        "equity_cnc_leverage",
        "futures_leverage",
        "option_buy_leverage",
        "option_sell_leverage",
    ]
    with configs_restored(reset_keys):
        payload, status, _ = _request("reset_config", method="POST", body={})
        assert status == 200 and payload["status"] == "success", payload

        funds = funds_of(USER)
        plan = _plan()

    assert funds["charges"] == 0 and funds["today_charges"] == 0
    assert funds["available"] == CAPITAL and funds["used"] == 0
    assert _trades() == []
    assert plan["enabled"] is True
    assert _segment(plan, "fno_options")["flat"] == "20"


def test_a_day_that_only_paid_charges_still_has_them_cleared_the_next_day():
    """Buying delivery realizes nothing and still pays. Testing realized P&L
    alone for staleness would carry yesterday's charges into today."""
    from sqlalchemy import text

    from database.sandbox_db import db_session
    from sandbox.catch_up_processor import catch_up_daily_pnl_reset

    db_session.execute(
        text(
            "UPDATE sandbox_funds SET today_charges = 50.00, total_charges = 80.00, "
            "today_realized_pnl = 0.00, updated_at = '2020-01-01 00:00:00' "
            "WHERE user_id = :user"
        ),
        {"user": USER},
    )
    db_session.commit()
    db_session.remove()

    with only_funds_of(USER):
        catch_up_daily_pnl_reset()
        release_sessions()
        funds = funds_of(USER)

    assert funds["today_charges"] == 0
    # What was paid stays paid.
    assert funds["charges"] == D("80.00")


def test_a_missed_snapshot_gets_that_days_charges_from_that_days_trades(monkeypatch):
    from database.sandbox_db import SandboxDailyPnL, SandboxTrades, db_session
    from sandbox import catch_up_processor

    monkeypatch.setattr(catch_up_processor, "is_pnl_snapshot_day", lambda day: True)
    yesterday = date.today() - timedelta(days=1)

    def trade(suffix, when, charge):
        return SandboxTrades(
            tradeid=f"TRADE-SNAPSHOT-{suffix}",
            orderid=f"SNAPSHOT-{suffix}",
            user_id=USER,
            symbol="RELIANCE",
            exchange="NSE",
            action="BUY",
            quantity=1,
            price=D("2500.00"),
            product="CNC",
            trade_timestamp=when,
            total_charges=charge,
        )

    db_session.add_all(
        [
            trade("A", datetime.combine(yesterday, time(9, 30)), D("12.34")),
            trade("B", datetime.combine(yesterday, time(23, 59, 59)), D("7.66")),
            trade("C", datetime.combine(date.today(), time(0, 0, 1)), D("99.00")),
            trade("D", datetime.combine(yesterday - timedelta(days=1), time(15, 0)), D("55.00")),
        ]
    )
    db_session.commit()
    db_session.remove()

    with only_funds_of(USER):
        catch_up_processor.catch_up_daily_pnl_snapshot()
        release_sessions()

    snapshot = SandboxDailyPnL.query.filter_by(user_id=USER, date=yesterday).first()
    # No P&L was realized, so only the charges make this a day worth a row.
    assert snapshot is not None
    assert snapshot.charges == D("20.00")
    assert snapshot.realized_pnl == 0
    db_session.remove()
