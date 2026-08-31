"""Per-strategy orderbook, tradebook and positions.

These views exist to answer one question - what has *this* strategy done - out
of books that describe the whole account. What matters here is therefore what
is filtered out, and what is recomputed once it has been: an account-wide
statistic reported against a filtered list would be read as the strategy's.

Everything is mocked. The point is the filtering and the routing, not the
broker, and a real book would make neither observable.
"""

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# Imported for their side effect: patch() resolves a dotted target by importing
# it, and each of these is only an attribute of the services package once the
# submodule has been imported somewhere. restx_api goes first for the same
# import-cycle reason as test_strategy_module_order_dispatch.
import restx_api  # noqa: F401
import services.orderbook_service  # noqa: F401
import services.positionbook_service  # noqa: F401
import services.sandbox_service  # noqa: F401
import services.tradebook_service  # noqa: F401
from services.strategy_module import views

STRATEGY_ID = 11
RUN_ID = 42
API_KEY = "test-api-key"

CE = "NIFTY28MAY2624000CE"
PE = "NIFTY28MAY2624000PE"

OURS_ONE = "250408000989443"
OURS_TWO = "250408000989444"
THEIRS = "250408000111111"


# ---------------------------------------------------------------------------
# Fixtures: the store, and what each global service answers
# ---------------------------------------------------------------------------


def _order_rows():
    """Two orders this strategy placed, both of which reached the broker."""
    return [
        {
            "broker_order_id": OURS_ONE,
            "symbol": CE,
            "exchange": "NFO",
            "leg_id": 1,
            "kind": "entry",
            "status": "complete",
            "qty": 75,
        },
        {
            "broker_order_id": OURS_TWO,
            "symbol": PE,
            "exchange": "NFO",
            "leg_id": 2,
            "kind": "entry",
            "status": "complete",
            "qty": 75,
        },
    ]


def _position_order(
    *,
    run_id,
    position_ref,
    symbol,
    action="BUY",
    filled_qty=25,
    leg_id=1,
):
    return {
        "run_id": run_id,
        "leg_id": leg_id,
        "position_ref": position_ref,
        "broker_order_id": f"{run_id}-{position_ref}-{action}",
        "symbol": symbol,
        "exchange": "NFO",
        "product": "NRML",
        "kind": "entry" if action == "BUY" else "exit_signal",
        "action": action,
        "status": "complete",
        "qty": filled_qty,
        "filled_qty": filled_qty,
        "avg_fill_price": 100.0 if action == "BUY" else 110.0,
        "placed_at": f"2026-05-28T03:{50 if action == 'BUY' else 51}:00+00:00",
    }


@contextmanager
def a_store(rows=None, mode="live", product="NRML", run="default", runs="default"):
    """Patch the store this module reads, and hand back the mocks."""
    if rows is None:
        rows = _order_rows()
    rows = [
        {
            "run_id": RUN_ID,
            "leg_id": index,
            "kind": "entry",
            "position_ref": f"fixture-owner-{index}",
            "action": "BUY",
            "product": product,
            "placed_at": f"2026-05-28T03:{40 + index}:00+00:00",
            **row,
        }
        for index, row in enumerate(rows, start=1)
    ]
    if run == "default":
        run = SimpleNamespace(id=RUN_ID, strategy_id=STRATEGY_ID, mode=mode)
    if runs == "default":
        runs = [{"id": RUN_ID, "strategy_id": STRATEGY_ID, "mode": mode}]

    mocks = SimpleNamespace(
        list_orders_for_strategy=MagicMock(return_value=list(rows)),
        get_run=MagicMock(return_value=run),
        list_runs=MagicMock(return_value=runs),
        get_strategy_unscoped=MagicMock(return_value=SimpleNamespace(product=product)),
    )
    with ExitStack() as stack:
        for name in vars(mocks):
            stack.enter_context(patch.object(views.store, name, getattr(mocks, name)))
        yield mocks


def global_orderbook():
    """What the global orderbook service returns for the whole account."""
    return {
        "status": "success",
        "data": {
            "orders": [
                {
                    "orderid": OURS_ONE,
                    "symbol": CE,
                    "exchange": "NFO",
                    "action": "SELL",
                    "quantity": 75,
                    "price": 120.5,
                    "trigger_price": 0.0,
                    "pricetype": "MARKET",
                    "product": "NRML",
                    "order_status": "complete",
                    "timestamp": "28-May-2026 09:20:01",
                },
                {
                    "orderid": OURS_TWO,
                    "symbol": PE,
                    "exchange": "NFO",
                    "action": "BUY",
                    "quantity": 75,
                    "price": 98.0,
                    "trigger_price": 0.0,
                    "pricetype": "MARKET",
                    "product": "NRML",
                    "order_status": "complete",
                    "timestamp": "28-May-2026 09:20:02",
                },
                {
                    "orderid": THEIRS,
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "action": "BUY",
                    "quantity": 1,
                    "price": 1186.0,
                    "trigger_price": 0.0,
                    "pricetype": "LIMIT",
                    "product": "MIS",
                    "order_status": "open",
                    "timestamp": "28-May-2026 10:02:11",
                },
                {
                    "orderid": "250408000222222",
                    "symbol": "YESBANK",
                    "exchange": "NSE",
                    "action": "BUY",
                    "quantity": 1,
                    "price": 16.5,
                    "trigger_price": 0.0,
                    "pricetype": "LIMIT",
                    "product": "MIS",
                    "order_status": "rejected",
                    "timestamp": "28-May-2026 10:04:55",
                },
            ],
            "statistics": {
                "total_buy_orders": 3,
                "total_sell_orders": 1,
                "total_completed_orders": 2,
                "total_open_orders": 1,
                "total_rejected_orders": 1,
            },
        },
    }


def global_tradebook():
    return {
        "status": "success",
        "data": [
            {
                "orderid": OURS_ONE,
                "symbol": CE,
                "exchange": "NFO",
                "product": "NRML",
                "action": "SELL",
                "quantity": 75,
                "average_price": 120.5,
                "trade_value": 9037.5,
                "timestamp": "09:20:01",
            },
            {
                "orderid": THEIRS,
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "product": "MIS",
                "action": "BUY",
                "quantity": 1,
                "average_price": 1186.0,
                "trade_value": 1186.0,
                "timestamp": "10:02:11",
            },
        ],
    }


def global_positionbook():
    return {
        "status": "success",
        "data": [
            {
                "symbol": CE,
                "exchange": "NFO",
                "product": "NRML",
                "quantity": "-75",
                "average_price": "120.50",
                "ltp": "110.00",
                "pnl": "787.50",
            },
            {
                "symbol": PE,
                "exchange": "NFO",
                "product": "NRML",
                "quantity": "75",
                "average_price": "98.00",
                "ltp": "94.00",
                "pnl": "-300.00",
            },
            {
                # Same contract, different product: a different book entirely.
                "symbol": CE,
                "exchange": "NFO",
                "product": "MIS",
                "quantity": "150",
                "average_price": "121.00",
                "ltp": "110.00",
                "pnl": "-1650.00",
            },
            {
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "product": "MIS",
                "quantity": "-1",
                "average_price": "1186.00",
                "ltp": "1189.90",
                "pnl": "-3.90",
            },
        ],
    }


def sandbox_positionbook():
    """The sandbox book carries account-wide totals the live one does not."""
    return {
        "status": "success",
        "data": [
            {
                "symbol": CE,
                "exchange": "NFO",
                "product": "NRML",
                "quantity": -75,
                "average_price": 120.5,
                "ltp": 110.0,
                "pnl": 787.5,
                "unrealized_pnl": 700.0,
                "today_realized_pnl": 87.5,
                "total_pnl_today": 787.5,
                "lot_size": 1.0,
            },
            {
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "product": "MIS",
                "quantity": -1,
                "average_price": 1186.0,
                "ltp": 1189.9,
                "pnl": -3.9,
                "unrealized_pnl": -3.9,
                "today_realized_pnl": 0.0,
                "total_pnl_today": -3.9,
                "lot_size": 1.0,
            },
        ],
        "total_pnl": 783.6,
        "total_unrealized_pnl": 696.1,
        "total_today_realized_pnl": 87.5,
        "total_pnl_today": 783.6,
        "mode": "analyze",
    }


@contextmanager
def live_books(
    orderbook=None,
    tradebook=None,
    positionbook=None,
    ok=True,
    auth=("tok", "zerodha"),
):
    """Patch the three global services and the broker session behind them."""
    calls = SimpleNamespace()
    with ExitStack() as stack:
        stack.enter_context(patch("database.auth_db.get_auth_token_broker", return_value=auth))
        calls.orderbook = stack.enter_context(
            patch(
                "services.orderbook_service.get_orderbook_with_auth",
                return_value=(ok, orderbook if orderbook is not None else global_orderbook(), 200),
            )
        )
        calls.tradebook = stack.enter_context(
            patch(
                "services.tradebook_service.get_tradebook_with_auth",
                return_value=(ok, tradebook if tradebook is not None else global_tradebook(), 200),
            )
        )
        calls.positionbook = stack.enter_context(
            patch(
                "services.positionbook_service.get_positionbook_with_auth",
                return_value=(
                    ok,
                    positionbook if positionbook is not None else global_positionbook(),
                    200,
                ),
            )
        )
        yield calls


@contextmanager
def sandbox_books(orderbook=None, tradebook=None, positionbook=None, ok=True):
    calls = SimpleNamespace()
    with ExitStack() as stack:
        calls.orderbook = stack.enter_context(
            patch(
                "services.sandbox_service.sandbox_get_orderbook",
                return_value=(ok, orderbook if orderbook is not None else global_orderbook(), 200),
            )
        )
        calls.tradebook = stack.enter_context(
            patch(
                "services.sandbox_service.sandbox_get_tradebook",
                return_value=(ok, tradebook if tradebook is not None else global_tradebook(), 200),
            )
        )
        calls.positionbook = stack.enter_context(
            patch(
                "services.sandbox_service.sandbox_get_positions",
                return_value=(
                    ok,
                    positionbook if positionbook is not None else sandbox_positionbook(),
                    200,
                ),
            )
        )
        yield calls


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def test_the_orderbook_keeps_only_this_strategys_orders():
    with a_store(), live_books():
        result = views.strategy_orderbook(STRATEGY_ID, API_KEY)

    assert result["status"] == "success"
    assert [order["orderid"] for order in result["data"]["orders"]] == [OURS_ONE, OURS_TWO]


def test_the_tradebook_keeps_only_trades_from_this_strategys_orders():
    with a_store(), live_books():
        result = views.strategy_tradebook(STRATEGY_ID, API_KEY)

    assert [trade["orderid"] for trade in result["data"]] == [OURS_ONE]


def test_positions_are_kept_by_contract_and_product_because_they_carry_no_order_id():
    # A position row is per contract, so there is no order id to match on. The
    # foreign contract and the same contract held under another product are
    # both out.
    with a_store(), live_books():
        result = views.strategy_positions(STRATEGY_ID, API_KEY)

    assert [(row["symbol"], row["product"]) for row in result["data"]] == [
        (CE, "NRML"),
        (PE, "NRML"),
    ]


def test_a_contract_this_strategy_never_traded_is_never_shown():
    with a_store(rows=[]), live_books():
        result = views.strategy_positions(STRATEGY_ID, API_KEY)

    assert result["data"] == []


def test_a_contract_whose_only_order_was_rejected_is_not_claimed():
    # A rejected order created no position, so its contract must not pull in a
    # row that belongs to something else.
    rows = [
        {
            "broker_order_id": OURS_ONE,
            "symbol": CE,
            "exchange": "NFO",
            "status": "rejected",
        }
    ]
    with a_store(rows=rows), live_books():
        result = views.strategy_positions(STRATEGY_ID, API_KEY)

    assert result["data"] == []


@pytest.mark.parametrize("status", ["pending", "open", "rejected", "cancelled"])
def test_any_status_with_explicit_positive_fill_claims_its_position(status):
    rows = [
        {
            "broker_order_id": OURS_ONE,
            "symbol": CE,
            "exchange": "NFO",
            "status": status,
            "filled_qty": 25,
        }
    ]
    with a_store(rows=rows), live_books():
        result = views.strategy_positions(STRATEGY_ID, API_KEY)

    assert [row["symbol"] for row in result["data"]] == [CE]


@pytest.mark.parametrize("status", ["pending", "open", "rejected", "cancelled"])
@pytest.mark.parametrize("filled_qty", [None, 0, "invalid"])
def test_noncomplete_without_explicit_positive_fill_claims_no_position(status, filled_qty):
    rows = [
        {
            "broker_order_id": OURS_ONE,
            "symbol": CE,
            "exchange": "NFO",
            "status": status,
            "filled_qty": filled_qty,
        }
    ]
    with a_store(rows=rows), live_books():
        result = views.strategy_positions(STRATEGY_ID, API_KEY)

    assert result["data"] == []


def test_a_complete_order_without_fill_quantity_retains_legacy_position_attribution():
    rows = [
        {
            "broker_order_id": OURS_ONE,
            "symbol": CE,
            "exchange": "NFO",
            "status": "complete",
            "filled_qty": None,
            "qty": 75,
        }
    ]
    with a_store(rows=rows), live_books():
        result = views.strategy_positions(STRATEGY_ID, API_KEY)

    assert [row["symbol"] for row in result["data"]] == [CE]


@pytest.mark.parametrize("filled_qty", [0, -1, "invalid"])
def test_a_complete_order_with_nonpositive_or_invalid_explicit_fill_claims_no_position(
    filled_qty,
):
    rows = [
        {
            "broker_order_id": OURS_ONE,
            "symbol": CE,
            "exchange": "NFO",
            "status": "complete",
            "filled_qty": filled_qty,
            "qty": 75,
        }
    ]
    with a_store(rows=rows), live_books():
        result = views.strategy_positions(STRATEGY_ID, API_KEY)

    assert result["data"] == []


def test_explicit_positive_fill_is_position_evidence_even_when_ack_id_was_not_persisted():
    rows = [
        {
            "broker_order_id": None,
            "symbol": CE,
            "exchange": "NFO",
            "status": "open",
            "filled_qty": 25,
            "qty": 75,
        }
    ]
    with a_store(rows=rows), live_books():
        result = views.strategy_positions(STRATEGY_ID, API_KEY)

    assert [row["symbol"] for row in result["data"]] == [CE]


def test_healthy_empty_broker_book_retains_a_prior_run_residual_owner():
    prior = "NIFTY28MAY2625000CE"
    rows = [
        _position_order(
            run_id=41, position_ref="prior-owner", symbol=prior, filled_qty=75
        ),
        _position_order(
            run_id=41,
            position_ref="prior-owner",
            symbol=prior,
            action="SELL",
            filled_qty=50,
        ),
    ]
    with a_store(rows=rows), live_books(positionbook={"status": "success", "data": []}):
        result = views.strategy_positions(STRATEGY_ID, API_KEY, RUN_ID)

    assert result["data"] == [
        pytest.approx(
            {
                "symbol": prior,
                "exchange": "NFO",
                "product": "NRML",
                "quantity": 25,
                "average_price": 100.0,
                "ltp": None,
                "pnl": None,
                "source": "local/unreconciled",
                "position_ref": "prior-owner",
                "run_id": 41,
                "leg_id": 1,
            }
        )
    ]


def test_broker_overlay_keeps_omitted_prior_owner_beside_current_contract_truth():
    prior = "NIFTY28MAY2625000CE"
    current = "NIFTY28MAY2626000CE"
    rows = [
        _position_order(run_id=41, position_ref="prior", symbol=prior),
        _position_order(run_id=43, position_ref="current", symbol=current),
    ]
    book = {
        "status": "success",
        "data": [
            {
                "symbol": current,
                "exchange": "NFO",
                "product": "NRML",
                "quantity": 7,
                "average_price": 123.0,
                "ltp": 125.0,
                "pnl": 14.0,
            },
            {
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "product": "MIS",
                "quantity": 1,
            },
        ],
    }
    with a_store(rows=rows), live_books(positionbook=book):
        result = views.strategy_positions(STRATEGY_ID, API_KEY, RUN_ID)

    by_symbol = {row["symbol"]: row for row in result["data"]}
    assert set(by_symbol) == {prior, current}
    assert by_symbol[current]["quantity"] == 7
    assert by_symbol[current]["source"] == "broker"
    assert by_symbol[current]["position_ref"] == "current"
    assert by_symbol[prior]["quantity"] == 25
    assert by_symbol[prior]["source"] == "local/unreconciled"


def test_shared_contract_keeps_each_local_owner_beside_the_broker_aggregate():
    shared = "NIFTY28MAY2625000CE"
    rows = [
        _position_order(run_id=41, position_ref="owner-a", symbol=shared, filled_qty=25),
        _position_order(
            run_id=43,
            position_ref="owner-b",
            symbol=shared,
            filled_qty=25,
            leg_id=2,
        ),
    ]
    book = {
        "status": "success",
        "data": [
            {
                "symbol": shared,
                "exchange": "NFO",
                "product": "NRML",
                "quantity": 50,
                "average_price": 100.0,
                "ltp": 101.0,
                "pnl": 50.0,
            }
        ],
    }
    with a_store(rows=rows), live_books(positionbook=book):
        result = views.strategy_positions(STRATEGY_ID, API_KEY, RUN_ID)

    assert [row["source"] for row in result["data"]] == [
        "broker/shared",
        "local/unreconciled",
        "local/unreconciled",
    ]
    assert {row.get("position_ref") for row in result["data"][1:]} == {
        "owner-a",
        "owner-b",
    }


# ---------------------------------------------------------------------------
# Recomputed aggregates
# ---------------------------------------------------------------------------


def test_orderbook_statistics_are_recounted_over_the_filtered_orders():
    # The account-wide block says 3 buys, 1 open and 1 rejected. None of that
    # is this strategy's, and passing it through would report it as if it were.
    with a_store(), live_books():
        result = views.strategy_orderbook(STRATEGY_ID, API_KEY)

    statistics = result["data"]["statistics"]
    assert statistics == {
        "total_buy_orders": 1,
        "total_sell_orders": 1,
        "total_completed_orders": 2,
        "total_open_orders": 0,
        "total_rejected_orders": 0,
    }
    assert statistics != global_orderbook()["data"]["statistics"]


def test_the_statistics_key_set_follows_the_service_that_answered():
    # The sandbox book reports a trigger-pending count the broker mappings do
    # not. The frontend renders whatever the global service sends, so the key
    # set has to survive the filter.
    book = global_orderbook()
    book["data"]["statistics"] = {
        "total_buy_orders": 9,
        "total_sell_orders": 9,
        "total_completed_orders": 9,
        "total_open_orders": 9,
        "total_rejected_orders": 9,
        "total_trigger_pending_orders": 9,
    }
    book["mode"] = "analyze"
    with a_store(mode="sandbox"), sandbox_books(orderbook=book):
        result = views.strategy_orderbook(STRATEGY_ID, API_KEY)

    assert set(result["data"]["statistics"]) == set(book["data"]["statistics"])
    assert result["data"]["statistics"]["total_trigger_pending_orders"] == 0


def test_position_totals_are_re_summed_over_the_filtered_rows():
    # The sandbox book's totals include a RELIANCE position this strategy never
    # traded. Only what survived the filter may be summed.
    with a_store(mode="sandbox"), sandbox_books():
        result = views.strategy_positions(STRATEGY_ID, API_KEY)

    assert [row["symbol"] for row in result["data"]] == [CE, PE]
    assert result["data"][1]["source"] == "local/unreconciled"
    assert result["total_pnl"] == 787.5
    assert result["total_unrealized_pnl"] == 700.0
    assert result["total_today_realized_pnl"] == 87.5
    assert result["total_pnl_today"] == 787.5


def test_a_book_with_no_totals_does_not_grow_any():
    # The live position book has no totals block. Inventing one would change
    # the envelope the frontend is rendering.
    with a_store(), live_books():
        result = views.strategy_positions(STRATEGY_ID, API_KEY)

    assert set(result) == set(global_positionbook())


# ---------------------------------------------------------------------------
# Envelope parity
# ---------------------------------------------------------------------------


def test_the_orderbook_envelope_has_the_same_keys_as_the_global_service():
    reference = global_orderbook()
    with a_store(), live_books():
        result = views.strategy_orderbook(STRATEGY_ID, API_KEY)

    assert set(result) == set(reference)
    assert set(result["data"]) == set(reference["data"])
    assert set(result["data"]["orders"][0]) == set(reference["data"]["orders"][0])


def test_the_tradebook_envelope_has_the_same_keys_as_the_global_service():
    reference = global_tradebook()
    with a_store(), live_books():
        result = views.strategy_tradebook(STRATEGY_ID, API_KEY)

    assert set(result) == set(reference)
    assert set(result["data"][0]) == set(reference["data"][0])


def test_the_positions_envelope_has_the_same_keys_as_the_global_service():
    reference = global_positionbook()
    with a_store(), live_books():
        result = views.strategy_positions(STRATEGY_ID, API_KEY)

    assert set(result) == set(reference)
    assert set(reference["data"][0]).issubset(result["data"][0])
    assert result["data"][0]["source"] == "broker"


def test_a_sandbox_envelope_keeps_the_mode_marker_the_service_sent():
    with a_store(mode="sandbox"), sandbox_books():
        result = views.strategy_positions(STRATEGY_ID, API_KEY)

    assert result["mode"] == "analyze"


def test_the_service_response_is_not_mutated_in_place():
    book = global_orderbook()
    with a_store(), live_books(orderbook=book):
        views.strategy_orderbook(STRATEGY_ID, API_KEY)

    assert len(book["data"]["orders"]) == 4
    assert book["data"]["statistics"]["total_buy_orders"] == 3


# ---------------------------------------------------------------------------
# Sandbox routing
# ---------------------------------------------------------------------------


def test_a_sandbox_run_reads_the_sandbox_books_not_the_brokers():
    # A sandbox run's orders are not in the live broker's book at all, so
    # reading the wrong one shows an empty page.
    with a_store(mode="sandbox"), live_books() as live, sandbox_books() as sandbox:
        views.strategy_orderbook(STRATEGY_ID, API_KEY)
        views.strategy_tradebook(STRATEGY_ID, API_KEY)
        views.strategy_positions(STRATEGY_ID, API_KEY)

    assert sandbox.orderbook.call_count == 1
    assert sandbox.tradebook.call_count == 1
    assert sandbox.positionbook.call_count == 1
    assert live.orderbook.call_count == 0
    assert live.tradebook.call_count == 0
    assert live.positionbook.call_count == 0


def test_a_live_run_reads_the_broker_and_ignores_the_platform_analyzer_toggle():
    # original_data=None is the internal-call form. Passing the api key instead
    # would let the global analyzer switch divert a live run to the sandbox.
    with a_store(mode="live"), live_books() as live, sandbox_books() as sandbox:
        views.strategy_orderbook(STRATEGY_ID, API_KEY)

    assert sandbox.orderbook.call_count == 0
    args = live.orderbook.call_args[0]
    assert args[0] == "tok"
    assert args[1] == "zerodha"
    assert args[2] is None


def test_the_run_decides_the_book_not_the_strategys_latest_run():
    # Two runs of one strategy may disagree, so a named run is authoritative.
    run = SimpleNamespace(id=RUN_ID, strategy_id=STRATEGY_ID, mode="sandbox")
    with (
        a_store(mode="live", run=run),
        live_books() as live,
        sandbox_books() as sandbox,
    ):
        views.strategy_orderbook(STRATEGY_ID, API_KEY, RUN_ID)

    assert sandbox.orderbook.call_count == 1
    assert live.orderbook.call_count == 0


def test_a_run_whose_mode_is_unrecognised_is_refused_rather_than_defaulted():
    # Defaulting to live would read a real broker book for a run the operator
    # believed was on paper.
    run = SimpleNamespace(id=RUN_ID, strategy_id=STRATEGY_ID, mode="")
    with a_store(run=run), live_books() as live:
        result = views.strategy_orderbook(STRATEGY_ID, API_KEY, RUN_ID)

    assert result["status"] == "error"
    assert live.orderbook.call_count == 0


# ---------------------------------------------------------------------------
# run_id narrowing
# ---------------------------------------------------------------------------


def test_run_id_narrows_the_orders_the_filter_is_built_from():
    with a_store() as store, live_books():
        views.strategy_orderbook(STRATEGY_ID, API_KEY, RUN_ID)

    store.list_orders_for_strategy.assert_called_once_with(STRATEGY_ID, RUN_ID)
    store.get_run.assert_called_once_with(RUN_ID)
    assert store.list_runs.call_count == 0


def test_without_a_run_id_every_run_of_the_strategy_is_included():
    with a_store() as store, live_books():
        views.strategy_orderbook(STRATEGY_ID, API_KEY)

    store.list_orders_for_strategy.assert_called_once_with(STRATEGY_ID, None)
    assert store.get_run.call_count == 0


def test_a_run_belonging_to_another_strategy_is_refused():
    # Otherwise a Detail page could be handed another strategy's book by
    # putting someone else's run id in the query string.
    run = SimpleNamespace(id=RUN_ID, strategy_id=STRATEGY_ID + 1, mode="live")
    with a_store(run=run), live_books() as live:
        result = views.strategy_orderbook(STRATEGY_ID, API_KEY, RUN_ID)

    assert result["status"] == "error"
    assert live.orderbook.call_count == 0


def test_a_run_that_does_not_exist_is_refused():
    with a_store(run=None), live_books() as live:
        result = views.strategy_tradebook(STRATEGY_ID, API_KEY, RUN_ID)

    assert result["status"] == "error"
    assert live.tradebook.call_count == 0


def test_a_strategy_that_has_never_run_asks_no_broker_anything():
    with a_store(runs=[]) as store, live_books() as live:
        orders = views.strategy_orderbook(STRATEGY_ID, API_KEY)
        trades = views.strategy_tradebook(STRATEGY_ID, API_KEY)
        positions = views.strategy_positions(STRATEGY_ID, API_KEY)

    assert orders["status"] == "success"
    assert orders["data"]["orders"] == []
    assert set(orders["data"]) == {"orders", "statistics"}
    assert all(value == 0 for value in orders["data"]["statistics"].values())
    assert trades["data"] == []
    assert positions["data"] == []
    assert live.orderbook.call_count == 0
    assert live.tradebook.call_count == 0
    assert live.positionbook.call_count == 0
    assert store.list_orders_for_strategy.call_count == 0


# ---------------------------------------------------------------------------
# Orders that cannot match
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reference", [None, "", "   "])
def test_an_order_with_no_broker_id_matches_nothing_rather_than_everything(reference):
    # An order rejected before the broker saw it has no reference. Leaving a
    # falsy id in the match set would make it equal to every broker row whose
    # own order id is blank.
    rows = [{"broker_order_id": reference, "symbol": CE, "exchange": "NFO", "status": "rejected"}]
    book = global_orderbook()
    book["data"]["orders"].append(
        {
            "orderid": "",
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 1,
            "price": 800.0,
            "trigger_price": 0.0,
            "pricetype": "MARKET",
            "product": "MIS",
            "order_status": "complete",
            "timestamp": "28-May-2026 11:00:00",
        }
    )
    with a_store(rows=rows), live_books(orderbook=book):
        result = views.strategy_orderbook(STRATEGY_ID, API_KEY)

    assert result["data"]["orders"] == []
    assert all(value == 0 for value in result["data"]["statistics"].values())


def test_a_trade_with_no_order_id_is_not_claimed():
    book = global_tradebook()
    book["data"].append(dict(book["data"][0], orderid=None, symbol="SBIN"))
    rows = [{"broker_order_id": None, "symbol": CE, "exchange": "NFO", "status": "pending"}]
    with a_store(rows=rows), live_books(tradebook=book):
        result = views.strategy_tradebook(STRATEGY_ID, API_KEY)

    assert result["data"] == []


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------


def test_a_failing_broker_call_returns_an_error_envelope():
    failure = {"status": "error", "message": "Broker session is not available or has expired"}
    with a_store(), live_books(orderbook=failure, ok=False):
        result = views.strategy_orderbook(STRATEGY_ID, API_KEY)

    assert result == failure


def test_a_raising_broker_call_becomes_an_error_envelope_not_an_exception():
    # One failing tab must not take out the Detail page.
    with (
        a_store(),
        patch("database.auth_db.get_auth_token_broker", return_value=("tok", "zerodha")),
        patch(
            "services.positionbook_service.get_positionbook_with_auth",
            side_effect=RuntimeError("broker exploded"),
        ),
    ):
        result = views.strategy_positions(STRATEGY_ID, API_KEY)

    assert result["status"] == "error"
    assert result["message"]


def test_a_missing_broker_session_is_reported_rather_than_attempted():
    with a_store(), live_books(auth=(None, None)) as live:
        result = views.strategy_tradebook(STRATEGY_ID, API_KEY)

    assert result["status"] == "error"
    assert live.tradebook.call_count == 0


def test_a_sandbox_failure_keeps_its_mode_marker():
    failure = {"status": "error", "message": "Invalid API key", "mode": "analyze"}
    with a_store(mode="sandbox"), sandbox_books(tradebook=failure, ok=False):
        result = views.strategy_tradebook(STRATEGY_ID, API_KEY)

    assert result == failure


def test_a_book_answering_with_an_unexpected_shape_does_not_crash_the_page():
    with a_store(), live_books(orderbook={"status": "success", "data": None}):
        orders = views.strategy_orderbook(STRATEGY_ID, API_KEY)
    with a_store(), live_books(tradebook={"status": "success", "data": "nonsense"}):
        trades = views.strategy_tradebook(STRATEGY_ID, API_KEY)

    assert orders["data"]["orders"] == []
    assert orders["data"]["statistics"]
    assert trades["data"] == []
