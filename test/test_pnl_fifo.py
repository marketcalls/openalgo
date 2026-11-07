# test/test_pnl_fifo.py
"""Regression tests for utils/pnl_fifo.py's grouping key.

Grouping by (symbol, exchange, product) treats a cash-equity ISIN bought on NSE and sold on BSE as two unrelated positions,
producing phantom open positions and understated realized loss. Equity
must merge NSE/BSE by ISIN-equivalent symbol; F&O must not, since NFO/BFO
are genuinely different contracts.
"""

from utils.pnl_fifo import compute_realized_pnl


def _trade(
    action, qty, price, ts, exchange="NSE", segment="equity", product="CNC", symbol="AMARAJABAT"
):
    return {
        "symbol": symbol,
        "exchange": exchange,
        "product": product,
        "segment": segment,
        "action": action,
        "quantity": qty,
        "average_price": price,
        "trade_timestamp": ts,
    }


def test_equity_buy_on_nse_sell_on_bse_is_matched_not_left_open():
    trades = [
        _trade("BUY", 100, 500.0, "2026-01-05T09:30:00", exchange="NSE"),
        _trade("SELL", 100, 520.0, "2026-01-06T09:30:00", exchange="BSE"),
    ]
    result = compute_realized_pnl(trades)

    assert result.open_positions == []
    assert len(result.realized_lots) == 1
    lot = result.realized_lots[0]
    assert lot.realized_pnl == 2000.0
    # The lot still records the entry fill's own real exchange, not a
    # merged placeholder.
    assert lot.exchange == "NSE"


def test_equity_same_symbol_different_exchange_nets_correctly_both_directions():
    trades = [
        _trade("BUY", 50, 100.0, "2026-01-01T09:00:00", exchange="NSE"),
        _trade("BUY", 50, 110.0, "2026-01-02T09:00:00", exchange="BSE"),
        _trade("SELL", 100, 120.0, "2026-01-03T09:00:00", exchange="NSE"),
    ]
    result = compute_realized_pnl(trades)

    assert result.open_positions == []
    assert len(result.realized_lots) == 2
    assert result.total_realized_pnl == (120.0 - 100.0) * 50 + (120.0 - 110.0) * 50


def test_fno_segment_does_not_merge_across_exchange():
    # NFO and BFO are different contracts for the "same" underlying - must
    # stay as separate FIFO queues, unlike cash equity.
    trades = [
        _trade(
            "BUY",
            75,
            200.0,
            "2026-01-05T09:30:00",
            exchange="NFO",
            segment="fno",
            product="NRML",
            symbol="NIFTY26JANFUT",
        ),
        _trade(
            "SELL",
            75,
            210.0,
            "2026-01-06T09:30:00",
            exchange="BFO",
            segment="fno",
            product="NRML",
            symbol="NIFTY26JANFUT",
        ),
    ]
    result = compute_realized_pnl(trades)

    assert result.realized_lots == []
    assert len(result.open_positions) == 2
    exchanges = {op.exchange for op in result.open_positions}
    assert exchanges == {"NFO", "BFO"}


def test_missing_segment_keeps_exchange_separate_conservative_default():
    trades = [
        _trade("BUY", 10, 100.0, "2026-01-01T09:00:00", exchange="NSE", segment=None),
        _trade("SELL", 10, 110.0, "2026-01-02T09:00:00", exchange="BSE", segment=None),
    ]
    result = compute_realized_pnl(trades)

    assert result.realized_lots == []
    assert len(result.open_positions) == 2


def test_same_exchange_equity_matching_unaffected_by_the_fix():
    trades = [
        _trade("BUY", 10, 100.0, "2026-01-01T09:00:00", exchange="NSE"),
        _trade("SELL", 10, 105.0, "2026-01-02T09:00:00", exchange="NSE"),
    ]
    result = compute_realized_pnl(trades)

    assert len(result.realized_lots) == 1
    assert result.realized_lots[0].realized_pnl == 50.0
    assert result.open_positions == []


# --- Product is not part of the grouping key ---


def test_imported_buy_without_product_matches_captured_cnc_sell():
    # A stock bought via a Console CSV import (no product column,
    # stored as None), sold later by the bot and captured live as CNC. Keyed
    # on product these never met: the sell became a phantom short and the
    # P&L was never booked.
    trades = [
        _trade("BUY", 117, 595.83, "2026-05-26T10:00:00", product=None, symbol="MINDACORP"),
        _trade("SELL", 117, 677.68, "2026-09-15T15:13:00", product="CNC", symbol="MINDACORP"),
    ]
    result = compute_realized_pnl(trades)

    assert result.open_positions == []
    assert len(result.realized_lots) == 1
    assert round(result.total_realized_pnl, 2) == round((677.68 - 595.83) * 117, 2)
    # The lot reports the entry fill's own product, not a merged placeholder.
    assert result.realized_lots[0].product is None


def test_fno_mis_and_nrml_fills_of_one_symbol_match_per_symbol():
    # Zerodha's statement is per symbol: NIFTY08SEP2623550PE traded as MIS and
    # NRML shows one row. A buy under one product closed by a sell under the
    # other is still one position.
    trades = [
        _trade(
            "BUY",
            65,
            10.0,
            "2026-09-07T09:30:00",
            exchange="NFO",
            segment="fno",
            product="NRML",
            symbol="NIFTY08SEP2623550PE",
        ),
        _trade(
            "SELL",
            65,
            14.0,
            "2026-09-08T09:30:00",
            exchange="NFO",
            segment="fno",
            product="MIS",
            symbol="NIFTY08SEP2623550PE",
        ),
    ]
    result = compute_realized_pnl(trades)

    assert result.open_positions == []
    assert result.total_realized_pnl == (14.0 - 10.0) * 65


def test_open_position_reports_its_own_product():
    trades = [_trade("BUY", 10, 100.0, "2026-01-01T09:00:00", product="CNC")]
    result = compute_realized_pnl(trades)

    assert len(result.open_positions) == 1
    assert result.open_positions[0].product == "CNC"


def test_different_symbols_are_still_separate_positions():
    trades = [
        _trade("BUY", 10, 100.0, "2026-01-01T09:00:00", symbol="AAA"),
        _trade("SELL", 10, 110.0, "2026-01-02T09:00:00", symbol="BBB"),
    ]
    result = compute_realized_pnl(trades)

    assert result.realized_lots == []
    assert len(result.open_positions) == 2


def test_lot_and_open_position_carry_the_entry_fill_strategy():
    buy_a = {**_trade("BUY", 10, 100, "2026-10-01T10:00:00"), "strategy": "A"}
    sell_untagged = _trade("SELL", 4, 110, "2026-10-02T10:00:00")
    buy_b = {**_trade("BUY", 5, 120, "2026-10-03T10:00:00"), "strategy": "B"}

    result = compute_realized_pnl([buy_a, sell_untagged, buy_b])

    # The closing fill is untagged; the lot still belongs to the entry's strategy.
    assert [lot.strategy for lot in result.realized_lots] == ["A"]
    assert sorted((p.strategy, p.quantity) for p in result.open_positions) == [("A", 6), ("B", 5)]


def test_unrealized_reads_live_holdings_and_positions_not_the_ledger(monkeypatch):
    import database.strategy_book_db as book
    from services import holdings_service, positionbook_service, quotes_service
    from services.pnl_history_service import _live_open_rows

    monkeypatch.setattr(
        book,
        "get_strategy_legs",
        lambda strategy=None: [
            {
                "strategy": "A",
                "symbol": "INFY",
                "exchange": "NSE",
                "product": "CNC",
                "quantity": 6,
                "average_price": 95.0,
                "today_realized_pnl": 0,
            }
        ],
    )
    monkeypatch.setattr(
        holdings_service,
        "get_holdings",
        lambda api_key=None: (
            True,
            {
                "data": {
                    "holdings": [
                        {
                            "symbol": "INFY",
                            "exchange": "NSE",
                            "product": "CNC",
                            "quantity": 10,
                            "t1_quantity": 0,
                            "pledged_quantity": 0,
                            "average_price": 100.0,
                        }
                    ]
                }
            },
            200,
        ),
    )
    monkeypatch.setattr(
        positionbook_service,
        "get_positionbook",
        lambda api_key=None: (
            True,
            {
                "data": [
                    # Short option: open, valued at the live price.
                    {
                        "symbol": "NIFTYCE",
                        "exchange": "NFO",
                        "product": "NRML",
                        "quantity": -50,
                        "average_price": 100.0,
                    },
                    # Intraday equity is read from holdings only, so it is skipped.
                    {
                        "symbol": "INFY",
                        "exchange": "NSE",
                        "product": "MIS",
                        "quantity": 5,
                        "average_price": 100.0,
                    },
                    # Flat rows are not open.
                    {
                        "symbol": "FLAT",
                        "exchange": "NFO",
                        "product": "NRML",
                        "quantity": 0,
                        "average_price": 0.0,
                    },
                ]
            },
            200,
        ),
    )
    monkeypatch.setattr(
        quotes_service,
        "get_multiquotes",
        lambda wanted, api_key=None: (
            True,
            {
                "results": [
                    {"symbol": "INFY", "exchange": "NSE", "data": {"ltp": 110}},
                    {"symbol": "NIFTYCE", "exchange": "NFO", "data": {"ltp": 90}},
                ]
            },
            200,
        ),
    )

    rows, total = _live_open_rows("key", "2999-01-01")

    by_key = {(r["symbol"], r["strategy"]): r for r in rows}
    # The holding splits into the strategy's 6 shares and the untagged remainder of 4.
    assert by_key[("INFY", "A")]["unrealized_pnl"] == 90.0
    assert by_key[("INFY", None)]["unrealized_pnl"] == 10.0
    assert by_key[("INFY", None)]["source"] == "holdings"
    # A short gains when the price falls: (90 - 100) * -50.
    assert by_key[("NIFTYCE", None)]["unrealized_pnl"] == 500.0
    assert by_key[("NIFTYCE", None)]["action"] == "SELL"
    assert len(rows) == 3
    assert total == 600.0

    # A range that ended before today has no live price to value against.
    assert _live_open_rows("key", "2000-01-01") == ([], None)


def test_equity_same_day_round_trip_is_settled_before_older_lots():
    # FINCABLES, May 2026: Console books the 7 May sell against the 7 May buy
    # (-2,073.35), not against the older 5 May lot; the 66 carried lot keeps
    # its own cost (1056.95) for the sale on 1 June.
    trades = [
        _trade("BUY", 66, 1056.95, "2026-05-05T15:16:03", symbol="FINCABLES"),
        _trade("BUY", 306, 1087.43, "2026-05-07T09:31:07", symbol="FINCABLES"),
        _trade("SELL", 306, 1080.65, "2026-05-07T11:30:31", symbol="FINCABLES"),
        _trade("SELL", 66, 991.31, "2026-06-01T15:15:14", symbol="FINCABLES"),
    ]
    result = compute_realized_pnl(trades)

    by_exit = {str(lot.exit_timestamp)[:10]: lot for lot in result.realized_lots}
    assert round(by_exit["2026-05-07"].realized_pnl, 2) == round(306 * (1080.65 - 1087.43), 2)
    assert round(by_exit["2026-06-01"].realized_pnl, 2) == round(66 * (991.31 - 1056.95), 2)
    assert result.open_positions == []


def test_equity_day_leftover_is_carried_at_the_day_average():
    trades = [
        _trade("BUY", 100, 10.0, "2026-05-05T10:00:00"),
        _trade("BUY", 100, 20.0, "2026-05-05T11:00:00"),
        _trade("SELL", 100, 30.0, "2026-05-05T14:00:00"),
    ]
    result = compute_realized_pnl(trades)

    assert len(result.realized_lots) == 1
    assert result.realized_lots[0].realized_pnl == 100 * (30.0 - 15.0)
    assert result.open_positions[0].quantity == 100
    assert result.open_positions[0].average_price == 15.0


def test_fno_is_still_matched_in_plain_time_order():
    trades = [
        _trade(
            "BUY",
            75,
            100.0,
            "2026-05-05T10:00:00",
            exchange="NFO",
            segment="fno",
            product="NRML",
            symbol="OPT",
        ),
        _trade(
            "BUY",
            75,
            120.0,
            "2026-05-06T10:00:00",
            exchange="NFO",
            segment="fno",
            product="NRML",
            symbol="OPT",
        ),
        _trade(
            "SELL",
            75,
            130.0,
            "2026-05-06T14:00:00",
            exchange="NFO",
            segment="fno",
            product="NRML",
            symbol="OPT",
        ),
    ]
    result = compute_realized_pnl(trades)

    # Plain FIFO: the sell closes the oldest lot (100), not the same-day buy (120).
    assert result.realized_lots[0].realized_pnl == 75 * (130.0 - 100.0)
