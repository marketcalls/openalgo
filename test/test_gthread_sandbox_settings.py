"""The sandbox settings view changes capital and resets safely (gthread audit rest-03).

Changing the starting capital recomputed every account's balance in the view
from the funds rows it had just read, so a margin block committed in between
was lost from the available balance. It now goes through the funds
compare-and-set (sandbox.fund_manager.rebase_starting_capital).

A reset wipes an account in one transaction, which already holds the database
write lock from its first delete to its commit. What it could not stop is a
fill already under way in an engine thread: its trade committed before the
wipe and its position after it, leaving a position the reset had reported as
cleared. Under the gthread worker, where engine threads truly run alongside
the request, the reset now pauses the execution engine and the square-off
scheduler for the wipe and starts again whatever was running. Under eventlet
and on the development server the reset is exactly as before.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

import pytest
from test_gthread_sandbox_support import (
    CAPITAL,
    configs_restored,
    funds_of,
    only_funds_of,
    prepare_databases,
    release_sessions,
    reset_user,
    run_in_thread,
)

USER = "gthread_sandbox_settings"

#: Every config key the reset writes, so the shared test database gets them back.
RESET_KEYS = [
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


@pytest.fixture(autouse=True)
def fresh_account():
    prepare_databases()
    reset_user(USER)
    release_sessions()
    with configs_restored(RESET_KEYS):
        yield
    release_sessions()


def _call(view_name, body):
    """Run a sandbox view's own function inside a request, as the logged-in user."""
    from flask import Flask, session

    import blueprints.sandbox as sandbox_views

    view = inspect.unwrap(getattr(sandbox_views, view_name))
    app = Flask(__name__)
    app.secret_key = "test-only"
    with app.test_request_context(json=body, method="POST"):
        session["user"] = USER
        response = view()
        if isinstance(response, tuple):
            response, status = response
        else:
            status = response.status_code
        payload = response.get_json()
    release_sessions()
    return payload, status


def test_a_capital_change_goes_through_the_funds_compare_and_set(monkeypatch):
    from sandbox import fund_manager
    from sandbox.fund_manager import FundManager

    margin = Decimal("400000.00")
    run_in_thread(lambda: FundManager(USER).block_margin(margin, "open order"))

    calls = []
    real_rebase = getattr(fund_manager, "rebase_starting_capital", None)
    assert real_rebase is not None, "capital changes still recompute balances in the view"

    def recording_rebase(new_capital):
        calls.append(new_capital)
        return real_rebase(new_capital)

    monkeypatch.setattr(fund_manager, "rebase_starting_capital", recording_rebase)

    with only_funds_of(USER):
        payload, status = _call(
            "update_config", {"config_key": "starting_capital", "config_value": "5000000"}
        )
        funds = funds_of(USER)

    assert status == 200 and payload["status"] == "success", payload
    assert calls == [Decimal("5000000")]
    assert funds["total_capital"] == Decimal("5000000.00")
    assert funds["used"] == margin
    assert funds["available"] == Decimal("5000000.00") - margin


def _record_engines(monkeypatch, *, engine_running, scheduler_running, analyze_mode=True):
    from database import settings_db
    from sandbox import execution_thread, squareoff_thread

    events = []
    monkeypatch.setattr(execution_thread, "is_execution_engine_running", lambda: engine_running)
    monkeypatch.setattr(
        squareoff_thread, "is_squareoff_scheduler_running", lambda: scheduler_running
    )
    monkeypatch.setattr(
        execution_thread, "stop_execution_engine", lambda: events.append("stop engine")
    )
    monkeypatch.setattr(
        execution_thread, "start_execution_engine", lambda *a: events.append("start engine")
    )
    monkeypatch.setattr(
        squareoff_thread,
        "stop_squareoff_scheduler",
        lambda *a, **k: events.append("stop scheduler"),
    )
    monkeypatch.setattr(
        squareoff_thread, "start_squareoff_scheduler", lambda: events.append("start scheduler")
    )
    monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: analyze_mode)

    import blueprints.sandbox as sandbox_views

    real_wipe = getattr(sandbox_views, "_wipe_sandbox_account", None)
    assert real_wipe is not None, "the reset does not wipe the account as one step"

    def recording_wipe(*args, **kwargs):
        events.append("wipe")
        return real_wipe(*args, **kwargs)

    monkeypatch.setattr(sandbox_views, "_wipe_sandbox_account", recording_wipe)
    return events


def test_under_gthread_a_reset_pauses_the_engines_around_the_wipe(monkeypatch):
    import blueprints.sandbox as sandbox_views

    monkeypatch.setattr(sandbox_views, "gthread_active", lambda: True)
    events = _record_engines(monkeypatch, engine_running=True, scheduler_running=True)

    payload, status = _call("reset_config", {})

    assert status == 200 and payload["status"] == "success", payload
    assert events == [
        "stop engine",
        "stop scheduler",
        "wipe",
        "start engine",
        "start scheduler",
    ]
    funds = funds_of(USER)
    assert funds["available"] == CAPITAL and funds["used"] == 0


def test_a_reset_restarts_only_what_was_running_and_only_in_analyze_mode(monkeypatch):
    import blueprints.sandbox as sandbox_views

    monkeypatch.setattr(sandbox_views, "gthread_active", lambda: True)
    events = _record_engines(monkeypatch, engine_running=True, scheduler_running=False)
    _call("reset_config", {})
    assert events == ["stop engine", "wipe", "start engine"]

    events = _record_engines(
        monkeypatch, engine_running=True, scheduler_running=True, analyze_mode=False
    )
    _call("reset_config", {})
    assert events == ["stop engine", "stop scheduler", "wipe"]


def test_outside_gthread_a_reset_leaves_the_engines_alone(monkeypatch):
    import blueprints.sandbox as sandbox_views

    monkeypatch.setattr(sandbox_views, "gthread_active", lambda: False)
    events = _record_engines(monkeypatch, engine_running=True, scheduler_running=True)

    payload, status = _call("reset_config", {})

    assert status == 200 and payload["status"] == "success", payload
    assert events == ["wipe"]
