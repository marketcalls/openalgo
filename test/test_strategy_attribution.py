"""
Unit tests for splitting broker positions / holdings into per-strategy slices.

Run with: uv run pytest test/test_strategy_attribution.py -v
"""

from services.strategy_attribution import (
    KIND_HOLDINGS,
    KIND_POSITIONS,
    UNATTRIBUTED,
    attribute,
)


def _leg(strategy, symbol, quantity, average_price, exchange="NFO", product="NRML"):
    return {
        "strategy": strategy,
        "symbol": symbol,
        "exchange": exchange,
        "product": product,
        "quantity": quantity,
        "average_price": average_price,
    }


def _pos(symbol, quantity, average_price, exchange="NFO", product="NRML"):
    return {
        "symbol": symbol,
        "exchange": exchange,
        "product": product,
        "quantity": quantity,
        "average_price": average_price,
    }


def _slices(result, index=0):
    return {s["strategy"]: s["quantity"] for s in result["rows"][index]["slices"]}


def test_single_strategy_owns_the_whole_position():
    result = attribute(
        [_pos("NIFTYX", -150, 100.0)], [_leg("IC", "NIFTYX", -150, 100.0)], KIND_POSITIONS
    )
    row = result["rows"][0]
    assert _slices(result) == {"IC": -150}
    assert row["mismatch"] is False
    assert result["strategies"] == ["IC"]


def test_two_strategies_on_one_contract_split_quantity():
    legs = [_leg("B", "NIFTYX", -50, 90.0), _leg("A", "NIFTYX", -100, 110.0)]
    result = attribute([_pos("NIFTYX", -150, 103.33)], legs, KIND_POSITIONS)
    assert _slices(result) == {"A": -100, "B": -50}
    assert result["strategies"] == ["A", "B"]
    assert result["rows"][0]["mismatch"] is False


def test_untagged_remainder_becomes_unattributed():
    result = attribute([_pos("X", 300, 50.0)], [_leg("S", "X", 100, 40.0)], KIND_POSITIONS)
    row = result["rows"][0]
    assert _slices(result) == {"S": 100, UNATTRIBUTED: 200}
    # Remainder's cost backs out so notional adds up: (50*300 - 40*100) / 200 = 55.
    remainder = next(s for s in row["slices"] if s["strategy"] == UNATTRIBUTED)
    assert remainder["average_price"] == 55.0
    assert remainder["attributed"] is False
    assert row["mismatch"] is False
    assert result["strategies"] == ["S"]


def test_no_legs_means_all_unattributed_at_broker_average():
    result = attribute([_pos("X", 10, 20.0)], [], KIND_POSITIONS)
    s = result["rows"][0]["slices"]
    assert len(s) == 1 and s[0]["strategy"] == UNATTRIBUTED
    assert s[0]["quantity"] == 10 and s[0]["average_price"] == 20.0


def test_legs_exceeding_broker_quantity_are_capped_and_flagged():
    legs = [_leg("A", "X", 100, 10.0), _leg("B", "X", 100, 10.0)]
    result = attribute([_pos("X", 150, 10.0)], legs, KIND_POSITIONS)
    row = result["rows"][0]
    assert _slices(result) == {"A": 100, "B": 50}
    assert sum(abs(s["quantity"]) for s in row["slices"]) == 150
    assert row["mismatch"] is True
    assert "exceed" in row["mismatch_reason"]


def test_opposite_side_leg_is_not_netted_and_is_flagged():
    result = attribute([_pos("X", 100, 10.0)], [_leg("S", "X", -100, 10.0)], KIND_POSITIONS)
    row = result["rows"][0]
    assert _slices(result) == {UNATTRIBUTED: 100}
    assert row["mismatch"] is True
    assert "opposite" in row["mismatch_reason"]


def test_flat_legs_are_ignored():
    result = attribute([_pos("X", 10, 5.0)], [_leg("S", "X", 0.0, 0.0)], KIND_POSITIONS)
    assert _slices(result) == {UNATTRIBUTED: 10}
    assert result["strategies"] == []


def test_closed_broker_position_has_no_slices():
    result = attribute([_pos("X", 0, 0.0)], [_leg("S", "X", 50, 5.0)], KIND_POSITIONS)
    assert result["rows"][0]["slices"] == []


def test_positions_match_on_product():
    legs = [_leg("S", "X", 10, 5.0, product="MIS")]
    result = attribute([_pos("X", 10, 5.0, product="NRML")], legs, KIND_POSITIONS)
    assert _slices(result) == {UNATTRIBUTED: 10}


def test_empty_strategy_name_is_unattributed_not_a_strategy():
    result = attribute([_pos("X", 10, 5.0)], [_leg("", "X", 10, 5.0)], KIND_POSITIONS)
    assert _slices(result) == {UNATTRIBUTED: 10}
    assert result["strategies"] == []


def test_short_position_signs():
    legs = [_leg("S", "X", -40, 10.0)]
    result = attribute([_pos("X", -100, 10.0)], legs, KIND_POSITIONS)
    assert _slices(result) == {"S": -40, UNATTRIBUTED: -60}


def _holding(symbol, quantity, average_price, t1=0, pledged=0, exchange="NSE"):
    return {
        "symbol": symbol,
        "exchange": exchange,
        "product": "CNC",
        "quantity": quantity,
        "t1_quantity": t1,
        "pledged_quantity": pledged,
        "average_price": average_price,
    }


def test_holdings_total_includes_t1_and_pledged():
    legs = [_leg("EBP", "INFY", 100, 1500.0, exchange="NSE", product="CNC")]
    result = attribute([_holding("INFY", 60, 1500.0, t1=10, pledged=30)], legs, KIND_HOLDINGS)
    row = result["rows"][0]
    assert row["quantity"] == 100
    assert _slices(result) == {"EBP": 100}
    assert row["mismatch"] is False


def test_holdings_ignore_intraday_legs_for_same_symbol():
    legs = [_leg("Gap", "INFY", 50, 1500.0, exchange="NSE", product="MIS")]
    result = attribute([_holding("INFY", 50, 1500.0)], legs, KIND_HOLDINGS)
    assert _slices(result) == {UNATTRIBUTED: 50}


def test_holdings_bought_before_the_book_existed_are_unattributed():
    legs = [_leg("EBP", "INFY", 40, 1600.0, exchange="NSE", product="CNC")]
    result = attribute([_holding("INFY", 100, 1500.0)], legs, KIND_HOLDINGS)
    assert _slices(result) == {"EBP": 40, UNATTRIBUTED: 60}
    assert result["strategies"] == ["EBP"]


def test_invalid_kind_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        attribute([], [], "orders")


def test_flat_leg_with_realized_pnl_today_is_a_zero_quantity_slice():
    legs = [_leg("IC", "X", 0.0, 0.0) | {"today_realized_pnl": 1250.0}]
    result = attribute([_pos("X", 0, 0.0)], legs, KIND_POSITIONS)
    (slice_,) = result["rows"][0]["slices"]
    assert slice_["strategy"] == "IC"
    assert slice_["quantity"] == 0
    assert slice_["today_realized_pnl"] == 1250.0
    assert result["strategies"] == ["IC"]


def test_flat_leg_alongside_an_open_leg_on_the_same_contract():
    legs = [
        _leg("A", "X", 0.0, 0.0) | {"today_realized_pnl": -300.0},
        _leg("B", "X", 50, 10.0),
    ]
    result = attribute([_pos("X", 50, 10.0)], legs, KIND_POSITIONS)
    assert _slices(result) == {"B": 50, "A": 0}
    assert result["rows"][0]["mismatch"] is False


def test_flat_leg_without_pnl_today_is_dropped():
    result = attribute([_pos("X", 0, 0.0)], [_leg("S", "X", 0.0, 0.0)], KIND_POSITIONS)
    assert result["rows"][0]["slices"] == []


def test_holdings_never_get_flat_slices():
    legs = [
        _leg("S", "INFY", 0.0, 0.0, exchange="NSE", product="CNC") | {"today_realized_pnl": 5.0}
    ]
    result = attribute([_holding("INFY", 10, 100.0)], legs, KIND_HOLDINGS)
    assert _slices(result) == {UNATTRIBUTED: 10}


# --- service wrapper (auth, book-unavailable, data shapes) ---------------------------------------


def _patch_service(monkeypatch, *, legs=None, book_error=False, positions=None, holdings=None):
    import database.strategy_book_db as book
    import services.holdings_service as holdings_service
    import services.pnl_attribution_service as svc
    import services.positionbook_service as position_service

    def fake_legs(*args, **kwargs):
        if book_error:
            raise svc.StrategyBookUnavailable("book down")
        return legs or []

    monkeypatch.setattr(svc, "get_auth_token_broker", lambda key: ("tok", "zerodha"))
    monkeypatch.setattr(book, "get_strategy_legs", fake_legs)
    monkeypatch.setattr(
        position_service,
        "get_positionbook",
        lambda **kw: (True, {"status": "success", "data": positions or []}, 200),
    )
    monkeypatch.setattr(
        holdings_service,
        "get_holdings",
        lambda **kw: (True, {"status": "success", "data": {"holdings": holdings or []}}, 200),
    )
    return svc


def test_service_positions_round_trip(monkeypatch):
    svc = _patch_service(
        monkeypatch,
        legs=[_leg("IC", "X", -75, 100.0)],
        positions=[_pos("X", -75, 100.0)],
    )
    ok, body, code = svc.get_pnl_attribution("key", "positions")
    assert ok and code == 200
    assert body["data"]["strategies"] == ["IC"]


def test_service_holdings_unwraps_the_holdings_list(monkeypatch):
    svc = _patch_service(
        monkeypatch,
        legs=[_leg("EBP", "INFY", 10, 1500.0, exchange="NSE", product="CNC")],
        holdings=[_holding("INFY", 10, 1500.0)],
    )
    ok, body, code = svc.get_pnl_attribution("key", "holdings")
    assert ok and code == 200
    assert body["data"]["rows"][0]["slices"][0]["strategy"] == "EBP"


def test_service_reports_unavailable_book_instead_of_all_unattributed(monkeypatch):
    svc = _patch_service(monkeypatch, book_error=True, positions=[_pos("X", 1, 1.0)])
    ok, body, code = svc.get_pnl_attribution("key", "positions")
    assert not ok and code == 503


def test_service_rejects_bad_key_and_kind(monkeypatch):
    svc = _patch_service(monkeypatch)
    monkeypatch.setattr(svc, "get_auth_token_broker", lambda key: (None, None))
    assert svc.get_pnl_attribution("bad", "positions")[2] == 403
    assert svc.get_pnl_attribution("key", "orders")[2] == 400


def test_hedged_strategies_on_one_contract_keep_their_gross_quantity():
    legs = [_leg("A", "X", 100, 10.0), _leg("B", "X", -40, 12.0)]
    result = attribute([_pos("X", 60, 9.0)], legs, KIND_POSITIONS)
    row = result["rows"][0]
    assert _slices(result) == {"A": 100, "B": -40}
    assert sum(s["quantity"] for s in row["slices"]) == row["quantity"]
    assert row["mismatch"] is False


def test_hedged_legs_with_a_manual_remainder_on_the_broker_side():
    legs = [_leg("A", "X", 100, 10.0), _leg("B", "X", -40, 10.0)]
    result = attribute([_pos("X", 80, 10.0)], legs, KIND_POSITIONS)
    assert _slices(result) == {"A": 100, "B": -40, UNATTRIBUTED: 20}
    assert sum(s["quantity"] for s in result["rows"][0]["slices"]) == 80
    assert result["rows"][0]["mismatch"] is False


def test_hedged_legs_that_disagree_with_the_broker_net_are_still_flagged():
    # Book says net +60, broker only holds +50: the book over-claims.
    legs = [_leg("A", "X", 100, 10.0), _leg("B", "X", -40, 10.0)]
    result = attribute([_pos("X", 50, 10.0)], legs, KIND_POSITIONS)
    row = result["rows"][0]
    assert row["mismatch"] is True
    assert sum(abs(s["quantity"]) for s in row["slices"]) <= 50


def test_hedged_legs_netting_to_the_wrong_side_are_flagged():
    legs = [_leg("A", "X", 40, 10.0), _leg("B", "X", -100, 10.0)]
    result = attribute([_pos("X", 50, 10.0)], legs, KIND_POSITIONS)
    assert result["rows"][0]["mismatch"] is True


def test_hedged_legs_flat_at_the_broker_net():
    legs = [_leg("A", "X", 100, 10.0), _leg("B", "X", -100, 10.0)]
    result = attribute([_pos("X", 30, 10.0)], legs, KIND_POSITIONS)
    assert _slices(result) == {"A": 100, "B": -100, UNATTRIBUTED: 30}


def test_flat_broker_row_names_the_single_stale_strategy_as_leftover_owner():
    result = attribute([_pos("X", 0, 0.0)], [_leg("IC", "X", -65, 17.15)], KIND_POSITIONS)
    row = result["rows"][0]
    assert row["slices"] == []
    assert row["leftover_owner"] == "IC"


def test_two_stale_strategies_on_a_flat_row_are_ambiguous():
    legs = [_leg("A", "X", -65, 17.0), _leg("B", "X", 65, 3.0)]
    result = attribute([_pos("X", 0, 0.0)], legs, KIND_POSITIONS)
    assert result["rows"][0]["leftover_owner"] is None


def test_open_broker_row_never_has_a_leftover_owner():
    result = attribute([_pos("X", -65, 17.15)], [_leg("IC", "X", -65, 17.15)], KIND_POSITIONS)
    assert result["rows"][0]["leftover_owner"] is None


def test_flat_row_with_one_strategy_realized_today_names_it_leftover_owner():
    # Fade closed the contract today; the broker's P&L on the row differs from the fills.
    legs = [_leg("Fade", "X", 0.0, 0.0, product="NRML") | {"today_realized_pnl": -5616.0}]
    result = attribute([_pos("X", 0, 0.0, product="NRML")], legs, KIND_POSITIONS)
    row = result["rows"][0]
    assert [s["strategy"] for s in row["slices"]] == ["Fade"]
    assert row["leftover_owner"] == "Fade"


def test_flat_row_two_strategies_active_today_stays_ambiguous():
    legs = [
        _leg("A", "X", 0.0, 0.0) | {"today_realized_pnl": 100.0},
        _leg("B", "X", 0.0, 0.0) | {"today_realized_pnl": -50.0},
    ]
    result = attribute([_pos("X", 0, 0.0)], legs, KIND_POSITIONS)
    assert result["rows"][0]["leftover_owner"] is None


def test_flat_row_stale_leg_plus_another_strategy_realized_today_is_ambiguous():
    legs = [_leg("A", "X", -65, 17.0), _leg("B", "X", 0.0, 0.0) | {"today_realized_pnl": 10.0}]
    result = attribute([_pos("X", 0, 0.0)], legs, KIND_POSITIONS)
    assert result["rows"][0]["leftover_owner"] is None


def _patch_m2m_inputs(
    monkeypatch, *, trades=None, prev_close=None, tradebook_ok=True, quotes_ok=True
):
    import services.quotes_service as quotes_service
    import services.tradebook_service as tradebook_service

    monkeypatch.setattr(
        tradebook_service,
        "get_tradebook",
        lambda **kw: (
            (True, {"status": "success", "data": trades or []}, 200)
            if tradebook_ok
            else (False, {"status": "error"}, 500)
        ),
    )

    def fake_quotes(symbols, **kw):
        if not quotes_ok:
            return False, {"status": "error"}, 500
        return (
            True,
            {
                "status": "success",
                "results": [
                    {
                        "symbol": s["symbol"],
                        "exchange": s["exchange"],
                        "data": {"prev_close": (prev_close or {}).get(s["symbol"])},
                    }
                    for s in symbols
                ],
            },
            200,
        )

    monkeypatch.setattr(quotes_service, "get_multiquotes", fake_quotes)


def test_service_positions_with_m2m_merges_todays_figures(monkeypatch):
    position = _pos("X", 0, 0.05, product="NRML") | {
        "average_price_basis": "carry_forward_valuation"
    }
    svc = _patch_service(
        monkeypatch,
        legs=[_leg("Fade", "X", 0.0, 0.0, product="NRML") | {"today_realized_pnl": -5616.0}],
        positions=[position],
    )
    _patch_m2m_inputs(
        monkeypatch,
        trades=[_trade_row("X", "SELL", 195, 0.25, "NRML")],
        prev_close={"X": 22.7},
    )
    ok, body, code = svc.get_pnl_attribution("key", "positions", include_m2m=True)
    row = body["data"]["rows"][0]
    assert ok and code == 200
    assert row["m2m_available"] is True
    assert row["m2m"] == -4377.75
    assert row["overnight_quantity"] == 195
    assert row["pnl_equals_m2m"] is True
    assert body["data"]["m2m_error"] is None


def test_service_m2m_is_opt_in(monkeypatch):
    svc = _patch_service(monkeypatch, positions=[_pos("X", 0, 0.05)])
    ok, body, _ = svc.get_pnl_attribution("key", "positions")
    assert ok and "m2m" not in body["data"]["rows"][0]
    assert "m2m_error" not in body["data"]


def test_service_m2m_failure_is_reported_not_zeroed(monkeypatch):
    svc = _patch_service(monkeypatch, positions=[_pos("X", 0, 0.05)])
    _patch_m2m_inputs(monkeypatch, tradebook_ok=False)
    ok, body, code = svc.get_pnl_attribution("key", "positions", include_m2m=True)
    row = body["data"]["rows"][0]
    assert ok and code == 200
    assert body["data"]["m2m_error"] == "today's trades are unavailable"
    assert row["m2m_available"] is False
    assert "m2m" not in row


def test_service_m2m_quotes_failure_is_reported(monkeypatch):
    svc = _patch_service(monkeypatch, positions=[_pos("X", 0, 0.05)])
    _patch_m2m_inputs(monkeypatch, quotes_ok=False)
    ok, body, _ = svc.get_pnl_attribution("key", "positions", include_m2m=True)
    assert body["data"]["m2m_error"] == "previous closes are unavailable"
    assert body["data"]["rows"][0]["m2m_available"] is False


def test_service_holdings_ignore_the_m2m_flag(monkeypatch):
    svc = _patch_service(monkeypatch, holdings=[_holding("INFY", 10, 100.0)])
    ok, body, _ = svc.get_pnl_attribution("key", "holdings", include_m2m=True)
    assert ok and "m2m_error" not in body["data"]


def _trade_row(symbol, action, quantity, price, product="MIS", exchange="NFO"):
    return {
        "symbol": symbol,
        "exchange": exchange,
        "product": product,
        "action": action,
        "quantity": quantity,
        "average_price": price,
    }
