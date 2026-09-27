"""Signal-mode configuration and webhook routing.

A signal leg is a different shape from a batch leg, not a superset of it: it
names its own instrument and an absolute quantity, and it carries no option
fields at all, because multi-leg option spreads stay in batch mode.

The webhook router is shared between the two kinds, so the action vocabulary
has to be checked against the strategy rather than globally. Sending one kind's
actions to the other is a configuration mistake and is refused rather than
half-handled.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

# restx_api first: see the note in test_strategy_module_order_dispatch.py.
import restx_api  # noqa: F401
from blueprints.strategy_module import validate_strategy_config
from services.strategy_module import webhook


def _signal(**overrides):
    body = {
        "name": "Signal",
        "strategy_kind": "signal",
        "direction": "both",
        "universe_tab": "stocks_fno",
        "underlying": "MULTI",
        "underlying_exchange": "NSE",
        "strategy_type": "positional",
        "legs": [
            {
                "id": 1,
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "side": "both",
                "qty": 100,
                "segment": "cash",
            }
        ],
    }
    body.update(overrides)
    return body


def _leg(**overrides):
    leg = {
        "id": 1,
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "side": "both",
        "qty": 100,
        "segment": "cash",
    }
    leg.update(overrides)
    return leg


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_a_signal_strategy_is_accepted_and_normalised():
    config, error = validate_strategy_config(
        _signal(legs=[_leg(symbol="reliance", exchange="nse")])
    )

    assert error is None
    leg = config["legs"][0]
    assert leg["symbol"] == "RELIANCE"
    assert leg["exchange"] == "NSE"
    assert leg["qty"] == 100
    assert leg["side"] == "both"


def test_option_fields_are_refused_on_a_signal_leg():
    # Accepting them and then ignoring them is how a strategy ends up looking
    # like it does something it does not.
    for field, value in (
        ("option_type", "CE"),
        ("strike_mode", "atm"),
        ("atm_offset", "ATM"),
        ("strike", 24000),
    ):
        _, error = validate_strategy_config(_signal(legs=[_leg(**{field: value})]))
        assert error is not None and field in error


def test_batch_leg_fields_are_refused_on_a_signal_leg():
    for field, value in (("position", "S"), ("lots", 1)):
        _, error = validate_strategy_config(_signal(legs=[_leg(**{field: value})]))
        assert error is not None and field in error


def test_a_signal_leg_must_name_its_own_instrument_and_quantity():
    for missing in ("symbol", "exchange", "qty"):
        leg = _leg()
        del leg[missing]
        _, error = validate_strategy_config(_signal(legs=[leg]))
        assert error is not None and missing in error


def test_quantity_is_a_positive_whole_number_of_shares():
    for bad in (0, -1, 1.5, "many", True):
        _, error = validate_strategy_config(_signal(legs=[_leg(qty=bad)]))
        assert error is not None, f"qty={bad!r} should be refused"


def test_a_leg_declares_which_signals_it_accepts():
    for side in ("long", "short", "both"):
        config, error = validate_strategy_config(_signal(legs=[_leg(side=side)]))
        assert error is None
        assert config["legs"][0]["side"] == side

    _, error = validate_strategy_config(_signal(legs=[_leg(side="buy")]))
    assert error is not None


def test_expiry_belongs_to_a_futures_leg_and_not_a_cash_one():
    _, error = validate_strategy_config(_signal(legs=[_leg(segment="cash", expiry="current")]))
    assert error is not None and "cash" in error

    # On NFO, because a futures leg on NSE names an instrument that venue
    # does not list, and the validator now refuses that rather than accepting
    # a segment nothing downstream reads.
    config, error = validate_strategy_config(
        _signal(legs=[_leg(segment="futures", exchange="NFO", expiry="current")])
    )
    assert error is None
    assert config["legs"][0]["expiry"] == "current"


def test_a_batch_strategy_still_takes_batch_legs():
    # The widening must not have changed the other kind.
    config, error = validate_strategy_config(
        {
            "name": "Batch",
            "strategy_kind": "batch",
            "universe_tab": "weekly_monthly",
            "underlying": "NIFTY",
            "underlying_exchange": "NSE_INDEX",
            "strategy_type": "positional",
            "legs": [
                {
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "strike_mode": "atm",
                    "atm_offset": "ATM",
                    "expiry": "weekly",
                }
            ],
        }
    )

    assert error is None
    assert config["legs"][0]["position"] == "S"


# ---------------------------------------------------------------------------
# Webhook routing
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_webhook_state():
    webhook.reset_state()
    yield
    webhook.reset_state()


def _strategy(kind, **overrides):
    row = SimpleNamespace(
        id=1,
        user_id="tester",
        strategy_kind=kind,
        direction="both",
        webhook_locked=False,
        webhook_ip_allowlist=None,
        live_enabled=False,
        status="stopped",
        current_run_id=None,
        strategy_type="positional",
        entry_time=None,
        exit_time=None,
        product="MIS",
        pricetype="MARKET",
        name="S",
        legs=[{"id": 1, "symbol": "RELIANCE", "exchange": "NSE", "side": "both", "qty": 1}],
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _call(strategy, body):
    token = "oaws_" + "A" * 43
    with (
        patch("database.strategy_module_db.get_strategy_by_webhook_token", return_value=strategy),
        patch(
            "database.strategy_module_db.record_webhook_event", return_value=SimpleNamespace(id=1)
        ),
    ):
        return webhook.handle_webhook(token, body, ip="1.2.3.4", user_agent="TradingView")


def test_a_batch_strategy_refuses_a_directional_signal():
    outcome = _call(_strategy("batch"), {"action": "long_entry", "leg_id": 1})

    assert outcome.ok is False
    assert outcome.result == "rejected_invalid_action"
    assert "start" in outcome.message


def test_a_signal_strategy_refuses_start_and_stop():
    for action in ("start", "stop"):
        outcome = _call(_strategy("signal"), {"action": action, "mode": "sandbox"})
        assert outcome.ok is False
        assert outcome.result == "rejected_invalid_action"
        assert "long_entry" in outcome.message


def test_a_directional_signal_reaches_the_signal_engine():
    strategy = _strategy("signal")
    with patch(
        "services.strategy_module.signals.handle_signal",
        return_value=SimpleNamespace(ok=True, note=None, error=None, run_id=7, leg_id=1),
    ) as handler:
        outcome = _call(strategy, {"action": "long_entry", "leg_id": 1})

    assert outcome.ok is True
    assert outcome.result == "ok"
    assert handler.call_args[0][1] == "long_entry"


def test_a_no_op_signal_is_reported_as_a_success():
    # A repeat alert did nothing, and saying so as a failure would invite the
    # retry that turns one alert into two positions.
    with patch(
        "services.strategy_module.signals.handle_signal",
        return_value=SimpleNamespace(ok=True, note="already_long", error=None, run_id=7, leg_id=1),
    ):
        outcome = _call(_strategy("signal"), {"action": "long_entry", "leg_id": 1})

    assert outcome.ok is True
    assert outcome.status == 200
    assert "already_long" in outcome.message


def test_a_signal_refused_by_configuration_is_reported_as_a_refusal():
    with patch(
        "services.strategy_module.signals.handle_signal",
        return_value=SimpleNamespace(
            ok=False, note=None, error="This strategy is long_only", run_id=None, leg_id=1
        ),
    ):
        outcome = _call(_strategy("signal"), {"action": "short_entry", "leg_id": 1})

    assert outcome.ok is False
    assert "long_only" in outcome.message


# ---------------------------------------------------------------------------
# Contradictions the form used to accept
# ---------------------------------------------------------------------------


def test_a_leg_side_the_direction_can_never_act_on_is_refused():
    # A long_only strategy discards every short signal before it reaches a leg,
    # so a leg declared short is configuration that looks complete and can never
    # trade. Nothing downstream complains: the gate refuses the signal, the leg
    # never opens, and the operator watches a strategy do nothing.
    _, error = validate_strategy_config(_signal(direction="long_only", legs=[_leg(side="short")]))
    assert error is not None
    assert "long_only" in error and "side" in error

    _, error = validate_strategy_config(_signal(direction="short_only", legs=[_leg(side="long")]))
    assert error is not None


def test_a_both_sided_leg_is_accepted_under_any_direction():
    for direction in ("both", "long_only", "short_only"):
        _config, error = validate_strategy_config(
            _signal(direction=direction, legs=[_leg(side="both")])
        )
        assert error is None, f"{direction} should accept a both-sided leg: {error}"


def test_a_matching_side_is_accepted():
    _config, error = validate_strategy_config(
        _signal(direction="long_only", legs=[_leg(side="long")])
    )
    assert error is None


def test_batch_legs_are_unaffected_by_the_direction_check():
    # Batch legs carry a B/S position rather than a side, and are entered as a
    # basket regardless of direction.
    config, error = validate_strategy_config(
        {
            "name": "Batch",
            "strategy_kind": "batch",
            "direction": "long_only",
            "universe_tab": "weekly_monthly",
            "underlying": "NIFTY",
            "underlying_exchange": "NSE_INDEX",
            "strategy_type": "positional",
            "legs": [
                {
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "strike_mode": "atm",
                    "atm_offset": "ATM",
                    "expiry": "weekly",
                }
            ],
        }
    )
    assert error is None
    assert config["legs"][0]["position"] == "S"


# ---------------------------------------------------------------------------
# Lot-size awareness on derivative exchanges
# ---------------------------------------------------------------------------


def test_a_derivative_quantity_in_units_must_be_a_whole_number_of_lots():
    # Units mode only: in lots mode the number IS a lot count, so checking it
    # against the lot size would be nonsense. The broker refuses a part lot at
    # order time, so catching it here turns a rejected order into a message the
    # user can act on from the form.
    with patch("services.strategy_module.symbol_resolver.lot_size_for", return_value=25):
        _, error = validate_strategy_config(
            _signal(
                legs=[
                    _leg(
                        symbol="RELIANCE",
                        exchange="NFO",
                        segment="futures",
                        expiry="current",
                        qty=7,
                        qty_mode="units",
                    )
                ]
            )
        )
        assert error is not None
        assert "whole number of lots" in error and "25" in error

        config, error = validate_strategy_config(
            _signal(
                legs=[
                    _leg(
                        symbol="RELIANCE",
                        exchange="NFO",
                        segment="futures",
                        expiry="current",
                        qty=50,
                        qty_mode="units",
                    )
                ]
            )
        )
        assert error is None
        assert config["legs"][0]["qty"] == 50


def test_a_cash_leg_has_no_lot_constraint():
    # Cash trades in single units, so any positive quantity is fine.
    with patch("services.strategy_module.symbol_resolver.lot_size_for", return_value=None):
        config, error = validate_strategy_config(
            _signal(legs=[_leg(symbol="RELIANCE", exchange="NSE", qty=7)])
        )
    assert error is None
    assert config["legs"][0]["qty"] == 7


def test_an_unknown_lot_size_does_not_block_the_form():
    # The master contract may not be downloaded yet. Refusing for a reason the
    # user cannot fix from this screen is worse than letting the engine check
    # again at entry, where the real contract is known.
    with patch("services.strategy_module.symbol_resolver.lot_size_for", return_value=None):
        _config, error = validate_strategy_config(
            _signal(
                legs=[
                    _leg(
                        symbol="WHATEVER",
                        exchange="NFO",
                        segment="futures",
                        expiry="current",
                        qty=7,
                    )
                ]
            )
        )
    assert error is None


# ---------------------------------------------------------------------------
# Quantity mode
# ---------------------------------------------------------------------------


def test_a_derivative_leg_defaults_to_lots_and_cash_to_units():
    # The venue implies how the instrument is counted, so neither the user nor
    # an API caller has to say it.
    config, error = validate_strategy_config(
        _signal(
            legs=[_leg(symbol="NIFTY", exchange="NFO", segment="futures", expiry="current", qty=5)]
        )
    )
    assert error is None
    assert config["legs"][0]["qty_mode"] == "lots"
    assert config["legs"][0]["qty"] == 5

    config, error = validate_strategy_config(_signal(legs=[_leg(exchange="NSE", qty=100)]))
    assert error is None
    assert config["legs"][0]["qty_mode"] == "units"


def test_lots_mode_stores_the_lot_count_not_the_product():
    # This is what lets the leg survive an exchange revising its lot size.
    # Storing 325 would silently become 5 lots under one size and 4.33 under
    # the next; storing 5 lots is still 5 lots.
    config, error = validate_strategy_config(
        _signal(
            legs=[
                _leg(
                    symbol="NIFTY",
                    exchange="NFO",
                    segment="futures",
                    expiry="current",
                    qty=5,
                    qty_mode="lots",
                )
            ]
        )
    )
    assert error is None
    assert config["legs"][0]["qty"] == 5


def test_lots_mode_is_refused_on_a_cash_leg():
    _, error = validate_strategy_config(
        _signal(legs=[_leg(exchange="NSE", qty=5, qty_mode="lots")])
    )
    assert error is not None
    assert "no lot size" in error.lower()


def test_units_mode_on_a_derivative_is_allowed_and_still_lot_checked():
    with patch("services.strategy_module.symbol_resolver.lot_size_for", return_value=65):
        config, error = validate_strategy_config(
            _signal(
                legs=[
                    _leg(
                        symbol="NIFTY",
                        exchange="NFO",
                        segment="futures",
                        expiry="current",
                        qty=325,
                        qty_mode="units",
                    )
                ]
            )
        )
        assert error is None
        assert config["legs"][0]["qty"] == 325

        _, error = validate_strategy_config(
            _signal(
                legs=[
                    _leg(
                        symbol="NIFTY",
                        exchange="NFO",
                        segment="futures",
                        expiry="current",
                        qty=7,
                        qty_mode="units",
                    )
                ]
            )
        )
        assert error is not None and "whole number of lots" in error


def test_an_unknown_quantity_mode_is_refused():
    _, error = validate_strategy_config(_signal(legs=[_leg(qty_mode="contracts")]))
    assert error is not None and "qty_mode" in error
