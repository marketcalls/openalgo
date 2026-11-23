"""A sandbox fill pays its brokerage and statutory charges exactly once.

The charge is worked out by ``sandbox/charges.py`` (checked against a published
brokerage calculator in ``test/sandbox/test_charges.py``). These tests are about where it
lands: it is recorded on the trade and taken from the funds row in the commit
that fills the order, so the three can never disagree.

The races below are the ones a charge adds to the fill path:

* Two threads reach one resting order. Only one may charge it.
* A fill that fails after its charge was staged must take the charge back.
* A funds writer that commits between the charge's read and its write must not
  be erased by it.

Each runs on real threads with their own sessions, as the other
``test_gthread_sandbox_*`` files do.
"""

from __future__ import annotations

import threading
from datetime import datetime as RealDatetime
from decimal import Decimal

import pytest
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
    run_in_threads,
    seed_symbols,
    set_charges,
)

D = Decimal
USER = "gthread_sandbox_charges"
NO_FUNDS_USER = "gthread_sandbox_charges_nofunds"

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

#: A delivery buy of 50 RELIANCE at 2500 under the default plan, line by line.
#: Worked by hand from the published rates on a trade value of 1,25,000.
BUY_50_AT_2500 = {
    "brokerage": D("20.00"),  # 20, the lower of 20 and 2.5% (3,125)
    "stt": D("125.00"),  # 0.1%
    "exchange_charges": D("3.84"),  # 0.00297% = 3.71, and the 0.0001% levy = 0.13
    "sebi_charges": D("0.13"),  # 10 per crore = 0.125
    "stamp_duty": D("19.00"),  # 0.015% on the buy = 18.75, to the nearest rupee
    "gst": D("4.31"),  # 18% of 20 + 3.84 + 0.13
    "total_charges": D("172.28"),
}


@pytest.fixture(autouse=True)
def charged_account(monkeypatch):
    from database.sandbox_db import db_session, set_configs
    from sandbox.charges import config_keys, default_config_values
    from sandbox.execution_engine import ExecutionEngine

    prepare_databases()
    seed_symbols([OPTION_SPEC])
    reset_user(USER)
    release_sessions()
    try:
        with configs_restored(list(config_keys())):
            # The default plan, with charges on.
            assert set_configs(default_config_values())
            db_session.remove()
            # A resting order must stay resting: placement checks marketability
            # against a live quote, so keep that quote away from the limit.
            monkeypatch.setattr(
                ExecutionEngine, "_fetch_quote", lambda self, symbol, exchange: quote(2600)
            )
            yield
    finally:
        release_sessions()
        remove_symbols([OPTION_SPEC])


def _allow_mis_orders(monkeypatch):
    from sandbox import order_manager

    class MarketHoursDatetime(RealDatetime):
        @classmethod
        def now(cls, tz=None):
            fixed = RealDatetime(2026, 10, 12, 14, 0)
            return tz.localize(fixed) if tz else fixed

    monkeypatch.setattr(order_manager, "datetime", MarketHoursDatetime)


def _fill(action, quantity, price, *, symbol="RELIANCE", exchange="NSE", product="CNC"):
    """Place a limit order the market already meets, so it fills at ``price`` at once."""
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


def _rest(price=D("2500.00"), quantity=50):
    """Place a delivery buy below the market, so it rests open."""
    from sandbox.order_manager import OrderManager

    order = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": quantity,
        "price": float(price),
        "price_type": "LIMIT",
        "product": "CNC",
    }
    ok, response, _ = run_in_thread(lambda: OrderManager(USER).place_order(order))
    assert ok, response
    return response["orderid"]


def _trade(orderid):
    """The charges recorded on an order's trade, or None when it has no trade."""
    from database.sandbox_db import SandboxTrades, db_session
    from sandbox.charges import CHARGE_COLUMNS

    db_session.remove()
    trade = SandboxTrades.query.filter_by(orderid=orderid).first()
    values = {name: getattr(trade, name) for name in CHARGE_COLUMNS} if trade else None
    if trade:
        values["tradeid"] = trade.tradeid
    db_session.remove()
    return values


def _status(orderid):
    from database.sandbox_db import SandboxOrders, db_session

    db_session.remove()
    status = SandboxOrders.query.filter_by(orderid=orderid).first().order_status
    db_session.remove()
    return status


def _expected(segment, exchange, action, value):
    from sandbox.charges import SEGMENTS_BY_KEY, compute_charges

    row = SEGMENTS_BY_KEY[segment]
    return compute_charges(segment, exchange, action, value, row.default_flat, row.default_percent)


# ---------------------------------------------------------------------------
# One fill
# ---------------------------------------------------------------------------


def test_a_fill_records_its_charges_and_takes_them_from_the_balance():
    orderid = _fill("BUY", 50, D("2500"))

    trade = _trade(orderid)
    for name, expected in BUY_50_AT_2500.items():
        assert trade[name] == expected, name

    funds = funds_of(USER)
    margin = D("125000.00")
    assert funds["used"] == margin
    assert funds["available"] == CAPITAL - margin - D("172.28")
    assert funds["charges"] == D("172.28")
    assert funds["today_charges"] == D("172.28")
    # The charge is a cost, not a loss on the position: P&L is untouched.
    assert funds["realized"] == 0
    assert funds["today"] == 0
    assert funds["total_pnl"] == 0


def test_a_round_trip_keeps_pnl_gross_and_the_margin_books_balanced():
    """Realized P&L agrees with the position; the balance carries the charges."""
    from sandbox.fund_manager import validate_margin_consistency

    buy_id = _fill("BUY", 50, D("2500"))
    sell_id = _fill("SELL", 50, D("2600"))

    buy, sell = _trade(buy_id), _trade(sell_id)
    assert sell["total_charges"] == _expected("equity_delivery", "NSE", "SELL", D("130000")).total
    assert sell["stamp_duty"] == 0  # stamp duty is the buyer's
    assert sell["stt"] == D("130.00")  # delivery pays STT both ways
    charges = buy["total_charges"] + sell["total_charges"]
    assert charges == D("172.28") + D("158.46")

    funds = funds_of(USER)
    gross = D("5000.00")  # 50 shares, 100 a share
    assert funds["realized"] == gross
    assert funds["today"] == gross
    assert funds["used"] == 0
    assert funds["charges"] == charges
    assert funds["available"] == CAPITAL + gross - charges

    consistent, discrepancy = validate_margin_consistency(USER)
    release_sessions()
    assert consistent and discrepancy == 0


def test_an_intraday_fill_is_charged_the_intraday_rates(monkeypatch):
    _allow_mis_orders(monkeypatch)
    orderid = _fill("BUY", 50, D("2500"), product="MIS")

    trade = _trade(orderid)
    assert trade["brokerage"] == D("20.00")  # 20, the lower of 20 and 0.1% (125)
    assert trade["stt"] == 0  # intraday STT is on the sell
    # 0.003%, a fifth of the delivery rate: 3.75, to the nearest rupee
    assert trade["stamp_duty"] == D("4.00")
    assert trade["total_charges"] == _expected("equity_intraday", "NSE", "BUY", D("125000")).total

    funds = funds_of(USER)
    margin = D("25000.00")  # five times leverage on MIS
    assert funds["used"] == margin
    assert funds["available"] == CAPITAL - margin - trade["total_charges"]


def test_an_option_is_charged_on_its_premium():
    buy_id = _fill("BUY", LOT, D("100"), symbol=OPTION, exchange="NFO", product="NRML")
    sell_id = _fill("SELL", LOT, D("110"), symbol=OPTION, exchange="NFO", product="NRML")

    buy, sell = _trade(buy_id), _trade(sell_id)
    assert buy["brokerage"] == sell["brokerage"] == D("20.00")  # flat per executed order
    assert buy["stt"] == 0
    # 0.15% of the 8,250 premium sold is 12.375, and STT goes to the nearest rupee
    assert sell["stt"] == D("12.00")
    assert buy["total_charges"] == _expected("fno_options", "NFO", "BUY", D("7500")).total
    assert sell["total_charges"] == _expected("fno_options", "NFO", "SELL", D("8250")).total

    funds = funds_of(USER)
    gross = D("750.00")
    assert funds["realized"] == gross
    assert funds["used"] == 0
    assert funds["available"] == (CAPITAL + gross - buy["total_charges"] - sell["total_charges"])


def test_with_charges_off_a_fill_leaves_the_figures_it_always_left():
    set_charges(False)
    orderid = _fill("BUY", 50, D("2500"))

    trade = _trade(orderid)
    assert all(trade[name] == 0 for name in BUY_50_AT_2500)

    funds = funds_of(USER)
    assert funds["charges"] == 0
    assert funds["available"] + funds["used"] == CAPITAL


def test_a_saved_plan_applies_from_the_next_fill():
    from sandbox.charge_manager import save_charge_settings

    first = _fill("BUY", 50, D("2500"))
    assert _trade(first)["brokerage"] == D("20.00")

    ok, message = save_charge_settings(
        {"segments": {"equity_delivery": {"flat": "0", "percent": "0.5"}}}
    )
    release_sessions()
    assert ok, message

    second = _fill("BUY", 50, D("2500"))
    assert _trade(second)["brokerage"] == D("625.00")  # 0.5% of 1,25,000
    # The first trade keeps what it was charged; a plan change is not backdated.
    assert _trade(first)["brokerage"] == D("20.00")


def test_a_charge_the_balance_cannot_cover_takes_it_below_zero():
    """The order has filled, so the charge is owed, as on a broker's ledger."""
    reset_user(USER, capital=D("125000.00"))
    orderid = _fill("BUY", 50, D("2500"))

    assert _status(orderid) == "complete"
    funds = funds_of(USER)
    assert funds["used"] == D("125000.00")
    assert funds["available"] == D("-172.28")
    assert funds["charges"] == D("172.28")


def test_funds_report_the_charges_and_a_balance_already_net_of_them():
    from sandbox.fund_manager import FundManager

    _fill("BUY", 50, D("2500"))
    funds = run_in_thread(lambda: FundManager(USER).get_funds())

    assert funds["today_charges"] == 172.28
    assert funds["total_charges"] == 172.28
    assert funds["availablecash"] == float(CAPITAL - D("125000") - D("172.28"))
    assert funds["m2mrealized"] == 0.0


def test_a_capital_change_keeps_the_charges_already_paid():
    """Rebasing recomputes the balance from gross P&L, so it must subtract charges."""
    from sandbox.fund_manager import rebase_starting_capital

    _fill("BUY", 50, D("2500"))
    new_capital = D("5000000.00")
    with only_funds_of(USER):
        assert run_in_thread(lambda: rebase_starting_capital(new_capital)) == 1
        funds = funds_of(USER)

    assert funds["total_capital"] == new_capital
    assert funds["charges"] == D("172.28")
    assert funds["available"] == new_capital - D("125000.00") - D("172.28")


# ---------------------------------------------------------------------------
# Races
# ---------------------------------------------------------------------------


def test_one_order_reached_by_two_threads_is_charged_once(monkeypatch):
    """Both threads decide to fill before either writes; one must lose whole.

    The loser's claim fails before it stages anything, so it charges nothing.
    Charging before the claim, or in a commit of its own, would debit twice
    for one trade.
    """
    from database.sandbox_db import SandboxOrders, SandboxTrades, db_session
    from sandbox.execution_engine import ExecutionEngine

    orderid = _rest()
    barrier = threading.Barrier(2)
    real_trade_id = ExecutionEngine._generate_trade_id

    def trade_id_after_both_decided(self):
        barrier.wait(10)
        return real_trade_id(self)

    monkeypatch.setattr(ExecutionEngine, "_generate_trade_id", trade_id_after_both_decided)

    def fill():
        order = SandboxOrders.query.filter_by(orderid=orderid).first()
        ExecutionEngine()._process_order(order, quote(2490))

    run_in_threads([fill, fill])

    db_session.remove()
    assert SandboxTrades.query.filter_by(orderid=orderid).count() == 1
    db_session.remove()

    trade = _trade(orderid)
    assert trade["total_charges"] == D("172.28")
    funds = funds_of(USER)
    assert funds["charges"] == trade["total_charges"]
    assert funds["available"] + funds["used"] + funds["charges"] == CAPITAL


def test_a_fill_that_fails_at_its_commit_takes_its_charge_back(monkeypatch):
    """The charge is staged in the fill's transaction, not committed ahead of it.

    The second fill is handed the first one's trade id, so its insert breaks
    the unique index when the transaction commits, after the charge was
    staged. Nothing of it may survive: no trade, and no debit.
    """
    from database.sandbox_db import SandboxOrders, SandboxTrades, db_session
    from sandbox.execution_engine import ExecutionEngine

    first = _fill("BUY", 50, D("2500"))
    taken = _trade(first)["tradeid"]
    before = funds_of(USER)

    second = _rest()
    reserved = funds_of(USER)["used"] - before["used"]
    staged = []
    monkeypatch.setattr(ExecutionEngine, "_generate_trade_id", lambda self: taken)

    from sandbox.fund_manager import FundManager

    real_stage = FundManager.stage_charges

    def recording_stage(self, amount, *args, **kwargs):
        result = real_stage(self, amount, *args, **kwargs)
        staged.append((amount, result[0]))
        return result

    monkeypatch.setattr(FundManager, "stage_charges", recording_stage)

    def fill():
        order = SandboxOrders.query.filter_by(orderid=second).first()
        ExecutionEngine()._process_order(order, quote(2490))

    run_in_thread(fill)

    assert staged == [(D("172.28"), True)], "the charge was never staged, so nothing was undone"
    db_session.remove()
    assert SandboxTrades.query.filter_by(orderid=second).count() == 0
    db_session.remove()

    funds = funds_of(USER)
    assert funds["charges"] == before["charges"] == D("172.28")
    assert funds["today_charges"] == before["today_charges"]
    assert funds["available"] == before["available"] - reserved


def test_a_charge_does_not_erase_a_credit_that_lands_at_its_write(monkeypatch):
    """The debit is a compare-and-set, not a balance written back from a read.

    The credit commits after the charge has read the funds row and before it
    writes. A charge that wrote the balance it had read minus its amount would
    erase the credit.
    """
    from database.sandbox_db import db_session
    from sandbox import fund_manager
    from sandbox.fund_manager import FundManager

    credit = D("5000.00")
    charge = D("172.28")
    real_write = fund_manager.write_funds_if_unchanged
    fired = []

    def write_after_a_credit(user_id, snapshot, new_values):
        if user_id == USER and not fired:
            fired.append(1)
            run_in_thread(lambda: FundManager(USER).credit_sale_proceeds(credit, "race"))
        return real_write(user_id, snapshot, new_values)

    monkeypatch.setattr(fund_manager, "write_funds_if_unchanged", write_after_a_credit)

    def pay():
        ok, message = FundManager(USER).stage_charges(charge, "race")
        db_session.commit()
        return ok, message

    ok, message = run_in_thread(pay)

    assert fired, "the write was never reached, so nothing was raced"
    assert ok, message
    funds = funds_of(USER)
    assert funds["available"] == CAPITAL + credit - charge
    assert funds["charges"] == charge
    assert funds["today_charges"] == charge


def test_two_fills_at_once_both_pay(monkeypatch):
    """Fills on two instruments share one funds row; neither charge may be lost."""
    from sandbox.order_manager import OrderManager

    barrier = threading.Barrier(2)

    def buy(symbol):
        def place():
            order = {
                "symbol": symbol,
                "exchange": "NSE",
                "action": "BUY",
                "quantity": 50,
                "price": 2500.0,
                "price_type": "LIMIT",
                "product": "CNC",
            }
            barrier.wait(10)
            return OrderManager(USER).place_order(order, prefetched_quote=quote(2500))

        return place

    results = run_in_threads([buy("RELIANCE"), buy("ZEEL")])
    assert all(result[0] for result in results), results

    funds = funds_of(USER)
    assert funds["used"] == D("250000.00")
    assert funds["charges"] == 2 * D("172.28")
    assert funds["available"] == CAPITAL - D("250000.00") - 2 * D("172.28")


# ---------------------------------------------------------------------------
# What never happens: a refused or invented charge
# ---------------------------------------------------------------------------


def test_a_fill_with_no_funds_row_goes_through_uncharged():
    """A trade must not claim a charge nobody paid, and the fill must not be lost."""
    from database.sandbox_db import (
        SandboxFunds,
        SandboxOrders,
        SandboxPositions,
        SandboxTrades,
        db_session,
    )
    from sandbox.execution_engine import ExecutionEngine

    for model in (SandboxOrders, SandboxTrades, SandboxPositions, SandboxFunds):
        model.query.filter_by(user_id=NO_FUNDS_USER).delete()
    db_session.add(
        SandboxOrders(
            orderid="NOFUNDS-CHARGE-1",
            user_id=NO_FUNDS_USER,
            symbol="RELIANCE",
            exchange="NSE",
            action="BUY",
            quantity=10,
            price=D("2500.00"),
            price_type="LIMIT",
            product="CNC",
            order_status="open",
            pending_quantity=10,
            order_timestamp=RealDatetime.now(),
        )
    )
    db_session.commit()
    db_session.remove()

    def fill():
        order = SandboxOrders.query.filter_by(orderid="NOFUNDS-CHARGE-1").first()
        ExecutionEngine()._execute_order(order, D("2500.00"))

    run_in_thread(fill)

    db_session.remove()
    order = SandboxOrders.query.filter_by(orderid="NOFUNDS-CHARGE-1").first()
    trade = SandboxTrades.query.filter_by(orderid="NOFUNDS-CHARGE-1").first()
    assert order.order_status == "complete"
    assert trade is not None
    assert trade.total_charges == 0 and trade.brokerage == 0 and trade.stt == 0
    assert SandboxFunds.query.filter_by(user_id=NO_FUNDS_USER).first() is None
    for model in (SandboxOrders, SandboxTrades, SandboxPositions):
        model.query.filter_by(user_id=NO_FUNDS_USER).delete()
    db_session.commit()
    db_session.remove()


def test_a_fault_in_the_fee_calculation_does_not_cost_the_trader_the_fill(monkeypatch):
    """An order whose charges cannot be worked out fills uncharged, not rejected."""
    from sandbox import charge_manager

    def broken(*args, **kwargs):
        raise RuntimeError("rate card unavailable")

    monkeypatch.setattr(charge_manager, "charges_for_fill", broken)

    orderid = _fill("BUY", 50, D("2500"))

    assert _status(orderid) == "complete"
    assert _trade(orderid)["total_charges"] == 0
    funds = funds_of(USER)
    assert funds["charges"] == 0
    assert funds["available"] + funds["used"] == CAPITAL


def test_a_negative_charge_is_refused_rather_than_credited():
    from database.sandbox_db import db_session
    from sandbox.fund_manager import FundManager

    def pay():
        result = FundManager(USER).stage_charges(D("-50.00"), "bad")
        db_session.rollback()
        return result

    ok, _message = run_in_thread(pay)
    assert ok is False
    funds = funds_of(USER)
    assert funds["available"] == CAPITAL and funds["charges"] == 0
