"""Strategy-module scheduler: what gets installed, and what the jobs then do.

Nothing here starts a scheduler that can fire. The scheduler is started
*paused*, which still builds every job for real - trigger, timezone, job
defaults and next fire time - but never runs one, so the assertions are about
the installed schedule rather than about waiting on the wall clock. The two job
functions are called directly with the engine mocked.

Several cases pin defects in the schedulers this one was written against:
missing timezones, missing job defaults, and an intraday strategy whose
``exit_time`` was never turned into a square-off.
"""

from datetime import time as dt_time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# restx_api first: see the note in test_strategy_module_order_dispatch.py.
import restx_api  # noqa: F401
from database import strategy_module_db as store
from services.strategy_module import ack_reconciliation, engine, recovery, state
from services.strategy_module import scheduler as sched
from services.strategy_module.engine import StartResult
from services.strategy_module.order_dispatch import DispatchResult

USER = "scheduler_test_user"


def _scheduler_config(**overrides):
    config = {
        "enabled": True,
        "days": ["MON", "TUE", "WED", "THU", "FRI"],
        "start_time": "09:20",
        "auto_stop_time": "15:10",
        "default_mode": "sandbox",
    }
    config.update(overrides)
    return config


def _config(name="Scheduler test", **overrides):
    config = {
        "name": name,
        "underlying": "NIFTY",
        "underlying_exchange": "NSE_INDEX",
        "universe_tab": "weekly_monthly",
        "strategy_type": "positional",
        "product": "NRML",
        "legs": [
            {
                "id": 1,
                "segment": "options",
                "expiry": "weekly",
                "lots": 1,
                "position": "S",
                "option_type": "CE",
                "strike_mode": "atm",
                "atm_offset": "ATM",
            }
        ],
        "scheduler": _scheduler_config(),
    }
    config.update(overrides)
    return config


def _make(config=None):
    created, error = store.create_strategy(USER, config or _config())
    assert error is None, error
    return created["id"]


def _purge():
    for row in store.list_strategies(USER):
        for run in store.list_runs(row["id"]):
            state.clear_run_state(run["id"])
        store.set_strategy_status(row["id"], "stopped", None)
        store.delete_strategy(row["id"], USER)
    store.clear_strategy_module_cache()


@pytest.fixture(autouse=True)
def clean_slate():
    store.init_db()
    _purge()
    # Paused: jobs are installed and dated exactly as in production, and none of
    # them can fire while the test runs.
    sched.shutdown()
    sched.start(paused=True)
    yield
    sched.shutdown()
    _purge()


def _job(job_id):
    return sched.get_scheduler().get_job(job_id)


def _cron_fields(job):
    return {field.name: str(field) for field in job.trigger.fields}


# ---------------------------------------------------------------------------
# Nothing runs unless it was asked to
# ---------------------------------------------------------------------------


def test_importing_the_module_does_not_start_a_scheduler():
    # chartink and python_strategy both call start() at module scope, so any
    # tool that imports the app spins up live schedulers. This one is explicit,
    # and syncing without it is a logged no-op rather than a crash.
    sid = _make()
    sched.shutdown()

    assert sched.get_scheduler() is None
    assert sched.sync_strategy_jobs(sid) == []
    assert sched.remove_strategy_jobs(sid) == 0
    assert sched.list_jobs() == []


def test_start_and_shutdown_are_idempotent():
    first = sched.start(paused=True)
    second = sched.start(paused=True)
    assert first is second

    sched.shutdown()
    sched.shutdown()
    assert sched.get_scheduler() is None


def test_start_installs_one_shared_pending_stop_reconciliation_job():
    job = sched.get_scheduler().get_job(sched.PENDING_STOP_RECONCILE_JOB_ID)

    assert job is not None
    assert job.max_instances == 1
    assert job.coalesce is True


# ---------------------------------------------------------------------------
# What gets installed
# ---------------------------------------------------------------------------


def test_a_disabled_scheduler_installs_nothing():
    sid = _make(_config(scheduler=_scheduler_config(enabled=False)))

    assert sched.sync_strategy_jobs(sid) == []
    assert _job(sched.start_job_id(sid)) is None
    assert _job(sched.stop_job_id(sid)) is None


def test_a_strategy_with_no_scheduler_config_installs_nothing():
    sid = _make(_config(scheduler=None))

    assert sched.sync_strategy_jobs(sid) == []
    assert sched.list_jobs() == []


def test_an_enabled_scheduler_installs_both_jobs_with_the_documented_ids():
    sid = _make()

    installed = sched.sync_strategy_jobs(sid)

    assert installed == [f"strategy:{sid}:start", f"strategy:{sid}:stop"]
    assert _job(f"strategy:{sid}:start") is not None
    assert _job(f"strategy:{sid}:stop") is not None


def test_weekdays_map_to_cron_day_names_in_week_order():
    # Order matters only in that two equivalent schedules must produce the same
    # trigger; the days themselves must survive the mapping unchanged.
    sid = _make(_config(scheduler=_scheduler_config(days=["FRI", "MON", "WED"])))
    sched.sync_strategy_jobs(sid)

    assert _cron_fields(_job(sched.start_job_id(sid)))["day_of_week"] == "mon,wed,fri"
    assert _cron_fields(_job(sched.stop_job_id(sid)))["day_of_week"] == "mon,wed,fri"


def test_an_unknown_day_skips_the_job_rather_than_installing_a_partial_week():
    sid = _make(_config(scheduler=_scheduler_config(days=["MON", "FUNDAY"])))

    assert sched.sync_strategy_jobs(sid) == []


def test_the_configured_times_reach_the_trigger():
    sid = _make(_config(scheduler=_scheduler_config(start_time="09:20", auto_stop_time="15:10")))
    sched.sync_strategy_jobs(sid)

    start_fields = _cron_fields(_job(sched.start_job_id(sid)))
    stop_fields = _cron_fields(_job(sched.stop_job_id(sid)))

    assert (start_fields["hour"], start_fields["minute"]) == ("9", "20")
    assert (stop_fields["hour"], stop_fields["minute"]) == ("15", "10")


def test_the_timezone_reaches_both_the_scheduler_and_every_trigger():
    # PORTED DEFECT. flow_scheduler_service and historify_scheduler_service pass
    # no timezone on either, so their jobs fire in server-local time: a VPS in
    # UTC runs a 09:20 IST entry at 14:50 IST.
    sid = _make()
    sched.sync_strategy_jobs(sid)

    assert str(sched.get_scheduler().timezone) == "Asia/Kolkata"
    for job_id in (sched.start_job_id(sid), sched.stop_job_id(sid)):
        assert str(_job(job_id).trigger.timezone) == "Asia/Kolkata"


def test_every_job_carries_the_project_job_defaults():
    # PORTED DEFECT. python_strategy sets none, so it inherits APScheduler's
    # one-second misfire_grace_time and a 09:15 entry that misses its slot by
    # two seconds is dropped silently.
    sid = _make()
    sched.sync_strategy_jobs(sid)

    for job_id in (sched.start_job_id(sid), sched.stop_job_id(sid)):
        job = _job(job_id)
        assert job.coalesce is True
        assert job.max_instances == 1
        assert job.misfire_grace_time == 60


def test_jobs_are_module_level_callables_with_plain_arguments():
    # PORTED DEFECT. python_strategy schedules lambda: f(id), which no job store
    # can serialize.
    sid = _make()
    sched.sync_strategy_jobs(sid)

    start = _job(sched.start_job_id(sid))
    stop = _job(sched.stop_job_id(sid))

    assert start.func is sched.run_scheduled_start
    assert stop.func is sched.run_scheduled_stop
    assert tuple(start.args) == (sid,)
    assert tuple(stop.args) == (sid,)


def test_an_invalid_time_is_skipped_rather_than_installed():
    sid = _make(
        _config(scheduler=_scheduler_config(start_time="9:70", auto_stop_time="not a time"))
    )

    assert sched.sync_strategy_jobs(sid) == []
    assert _job(sched.start_job_id(sid)) is None
    assert _job(sched.stop_job_id(sid)) is None


def test_a_broken_stop_time_does_not_take_the_start_job_down_with_it():
    sid = _make(_config(scheduler=_scheduler_config(auto_stop_time="25:00")))

    assert sched.sync_strategy_jobs(sid) == [sched.start_job_id(sid)]


# ---------------------------------------------------------------------------
# The exit_time fallback
# ---------------------------------------------------------------------------


def test_an_intraday_exit_time_installs_the_square_off_the_original_never_scheduled():
    # PORTED DEFECT, and the one real gap closed here. In the source module the
    # auto-stop job comes only from scheduler.auto_stop_time, so an intraday
    # strategy that sets exit_time and leaves auto_stop_time blank gets no stop
    # job at all and its position stays open past the exit it configured.
    sid = _make(
        _config(
            strategy_type="intraday",
            entry_time=dt_time(9, 20),
            exit_time=dt_time(15, 20),
            scheduler=_scheduler_config(auto_stop_time=None),
        )
    )

    installed = sched.sync_strategy_jobs(sid)

    assert sched.stop_job_id(sid) in installed
    fields = _cron_fields(_job(sched.stop_job_id(sid)))
    assert (fields["hour"], fields["minute"]) == ("15", "20")


def test_an_intraday_exit_time_is_squared_off_with_the_scheduler_switched_off():
    """The default intraday configuration, and the one that was unreachable.

    The exit_time fallback sat below two early returns: one for a scheduler
    that is not enabled and one for a config with no usable days. Switching the
    scheduler off is exactly what an operator does when they want the strategy
    started by an alert and squared off by the clock, and that combination got
    no stop job at all.
    """
    sid = _make(
        _config(
            strategy_type="intraday",
            entry_time=dt_time(9, 20),
            exit_time=dt_time(15, 20),
            scheduler=_scheduler_config(enabled=False),
        )
    )

    installed = sched.sync_strategy_jobs(sid)

    assert installed == [sched.stop_job_id(sid)], "the square-off, and only it"
    assert _job(sched.start_job_id(sid)) is None, "nothing was asked to start it"
    fields = _cron_fields(_job(sched.stop_job_id(sid)))
    assert (fields["hour"], fields["minute"]) == ("15", "20")
    assert fields["day_of_week"] == "mon,tue,wed,thu,fri"


def test_an_intraday_exit_time_is_squared_off_with_no_scheduler_config_at_all():
    sid = _make(
        _config(
            strategy_type="intraday",
            entry_time=dt_time(9, 20),
            exit_time=dt_time(15, 15),
            scheduler=None,
        )
    )

    installed = sched.sync_strategy_jobs(sid)

    assert installed == [sched.stop_job_id(sid)]
    fields = _cron_fields(_job(sched.stop_job_id(sid)))
    assert (fields["hour"], fields["minute"]) == ("15", "15")


def test_the_scheduler_auto_stop_time_wins_over_exit_time_when_both_are_set():
    sid = _make(
        _config(
            strategy_type="intraday",
            entry_time=dt_time(9, 20),
            exit_time=dt_time(15, 20),
            scheduler=_scheduler_config(auto_stop_time="14:45"),
        )
    )
    sched.sync_strategy_jobs(sid)

    fields = _cron_fields(_job(sched.stop_job_id(sid)))
    assert (fields["hour"], fields["minute"]) == ("14", "45")


# ---------------------------------------------------------------------------
# Sync and removal
# ---------------------------------------------------------------------------


def test_sync_all_jobs_installs_from_the_database():
    first = _make(_config(name="Scheduler test A"))
    second = _make(_config(name="Scheduler test B", scheduler=_scheduler_config(enabled=False)))

    sched.sync_all_jobs()

    assert _job(sched.start_job_id(first)) is not None
    assert _job(sched.start_job_id(second)) is None


def test_syncing_again_after_the_scheduler_is_switched_off_removes_the_jobs():
    sid = _make()
    assert sched.sync_strategy_jobs(sid) != []

    store.update_strategy(sid, USER, {"scheduler": _scheduler_config(enabled=False)})

    assert sched.sync_strategy_jobs(sid) == []
    assert _job(sched.start_job_id(sid)) is None
    assert _job(sched.stop_job_id(sid)) is None


def test_remove_strategy_jobs_cleans_up_both_jobs():
    sid = _make()
    sched.sync_strategy_jobs(sid)

    assert sched.remove_strategy_jobs(sid) == 2
    assert _job(sched.start_job_id(sid)) is None
    assert _job(sched.stop_job_id(sid)) is None
    # Removing what is already gone is the desired end state, not an error.
    assert sched.remove_strategy_jobs(sid) == 0


def test_sync_all_jobs_drops_a_job_whose_strategy_is_gone():
    sid = _make()
    sched.sync_strategy_jobs(sid)
    store.delete_strategy(sid, USER)

    sched.sync_all_jobs()

    assert _job(sched.start_job_id(sid)) is None
    assert _job(sched.stop_job_id(sid)) is None


def test_list_jobs_reports_the_next_fire_time_in_ist():
    sid = _make()
    sched.sync_strategy_jobs(sid)

    listed = {job["id"]: job for job in sched.list_jobs()}

    entry = listed[sched.start_job_id(sid)]
    assert entry["strategy_id"] == sid
    assert entry["next_run_time"].endswith("+05:30")
    assert "day_of_week" in entry["trigger"]


# ---------------------------------------------------------------------------
# The start job
# ---------------------------------------------------------------------------


def test_the_start_job_starts_the_run_with_the_scheduler_as_the_trigger_source():
    sid = _make()

    with patch.object(engine, "start_run", return_value=StartResult(ok=True, run_id=7)) as run:
        sched.run_scheduled_start(sid)

    run.assert_called_once_with(sid, USER, "sandbox", trigger_source="scheduler")


def test_the_start_job_is_a_no_op_when_the_strategy_is_already_running():
    # A webhook or the UI may have started it seconds earlier. That is the
    # normal case, not a conflict.
    sid = _make()
    store.set_strategy_status(sid, "running", 42)

    with patch.object(engine, "start_run") as run:
        sched.run_scheduled_start(sid)

    run.assert_not_called()


def test_the_start_job_is_a_no_op_when_the_scheduler_has_since_been_disabled():
    sid = _make(_config(scheduler=_scheduler_config(enabled=False)))

    with patch.object(engine, "start_run") as run:
        sched.run_scheduled_start(sid)

    run.assert_not_called()


def test_a_live_start_is_refused_and_recorded_when_live_is_not_enabled():
    # Refusing silently is the failure this guards: the operator's only view of
    # why the entry never happened is the event trail.
    sid = _make(_config(scheduler=_scheduler_config(default_mode="live")))
    assert not store.get_strategy(sid, USER).live_enabled

    with patch.object(engine, "start_run") as run:
        sched.run_scheduled_start(sid)

    run.assert_not_called()

    warnings = [event for event in store.list_events(sid) if event["severity"] == "warn"]
    assert len(warnings) == 1
    assert warnings[0]["kind"] in store.EVENT_KINDS
    assert "live" in warnings[0]["message"].lower()


def test_a_live_start_goes_ahead_once_live_is_enabled():
    sid = _make(_config(scheduler=_scheduler_config(default_mode="live")))
    store.set_live_enabled(sid, USER, True)

    with patch.object(engine, "start_run", return_value=StartResult(ok=True, run_id=9)) as run:
        sched.run_scheduled_start(sid)

    run.assert_called_once_with(sid, USER, "live", trigger_source="scheduler")


def test_the_start_job_survives_a_strategy_that_has_been_deleted():
    sid = _make()
    store.delete_strategy(sid, USER)

    with patch.object(engine, "start_run") as run:
        sched.run_scheduled_start(sid)

    run.assert_not_called()


# ---------------------------------------------------------------------------
# The auto-stop job
# ---------------------------------------------------------------------------


def test_the_stop_job_squares_off_the_current_run():
    sid = _make()
    store.set_strategy_status(sid, "running", 55)

    with (
        patch.object(engine, "stop_run", return_value={"ok": True, "stop_pending": False}) as stop,
        patch.object(sched.logger, "info") as info,
    ):
        sched.run_scheduled_stop(sid)

    stop.assert_called_once_with(55, USER, reason="scheduler")
    assert "closed" in info.call_args.args[0].lower()


def test_the_stop_job_reports_accepted_pending_separately_from_confirmed_stopped():
    sid = _make()
    store.set_strategy_status(sid, "running", 56)

    with (
        patch.object(
            engine,
            "stop_run",
            return_value={"ok": True, "stop_pending": True, "exits": [{"ok": True}]},
        ),
        patch.object(sched.logger, "info") as info,
    ):
        sched.run_scheduled_stop(sid)

    rendered = " ".join(str(part) for part in info.call_args.args).lower()
    assert "pending" in rendered
    assert "closed" not in rendered


def test_the_stop_job_logs_from_scalars_after_engine_session_cleanup():
    sid = _make()
    store.set_strategy_status(sid, "running", 58)

    def stop_then_cleanup(*_args, **_kwargs):
        store.record_event(sid, USER, "run_stopped", "scheduler completed")
        store.db_session.remove()
        return {"ok": True, "stop_pending": False, "exits": []}

    with (
        patch.object(engine, "stop_run", side_effect=stop_then_cleanup) as stop,
        patch.object(sched.logger, "info") as info,
        patch.object(sched.logger, "exception") as exception,
    ):
        sched.run_scheduled_stop(sid)

    stop.assert_called_once_with(58, USER, reason="scheduler")
    rendered = " ".join(str(part) for part in info.call_args.args).lower()
    assert "closed" in rendered
    assert 58 in info.call_args.args
    exception.assert_not_called()


def test_the_stop_job_reports_refused_pending_as_retryable_not_accepted():
    sid = _make()
    store.set_strategy_status(sid, "running", 57)

    with (
        patch.object(
            engine,
            "stop_run",
            return_value={
                "ok": False,
                "stop_pending": True,
                "error": "No API key",
                "exits": [],
            },
        ),
        patch.object(sched.logger, "error") as error,
    ):
        sched.run_scheduled_stop(sid)

    rendered = " ".join(str(part) for part in error.call_args.args).lower()
    assert "refused" in rendered
    assert "pending" in rendered
    assert "closed" not in rendered


def test_the_stop_job_is_a_no_op_when_nothing_is_running():
    sid = _make()

    with patch.object(engine, "stop_run") as stop:
        sched.run_scheduled_stop(sid)

    stop.assert_not_called()


def test_periodic_reconciliation_self_heals_a_dropped_terminal_update_after_restart():
    """Recovery restores the working entry; the shared job polls its durable stop."""
    sid = _make()
    run = store.create_run(sid, "sandbox", "sandbox")
    assert run is not None
    assert store.set_strategy_status(sid, "running", run.id)
    entry = store.record_order(
        run.id,
        1,
        "entry",
        {
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": 75,
            "product": "NRML",
            "pricetype": "MARKET",
            "status": "open",
            "broker_order_id": "RECOVER-WORKING",
            "position_ref": "restart-owner",
        },
    )
    assert entry is not None
    assert store.request_run_stop(run.id, "scheduler")

    recovered = recovery.recover_run(run.id)
    assert recovered.ok is True
    assert state.get_run_state(run.id)["stopping"] is True

    with (
        patch.object(engine, "_api_key_for", return_value="scheduler-key"),
        patch.object(
            engine.order_dispatch,
            "cancel_order",
            return_value=DispatchResult(
                ok=True, broker_order_id="RECOVER-WORKING", response={}
            ),
            create=True,
        ) as cancel,
        patch.object(
            engine.order_dispatch,
            "fetch_order_status",
            return_value=SimpleNamespace(
                ok=True,
                order={
                    "orderid": "RECOVER-WORKING",
                    "order_status": "cancelled",
                    "filled_quantity": 0,
                    "average_price": 0,
                    "rejection_reason": "",
                },
                error=None,
            ),
            create=True,
        ) as poll,
        patch.object(engine, "_unsubscribe_run"),
    ):
        result = sched.reconcile_pending_stops()

    assert result == {"examined": 1, "pending": 0, "finalised": 1, "failed": 0}
    cancel.assert_called_once_with(
        mode="sandbox", api_key="scheduler-key", broker_order_id="RECOVER-WORKING"
    )
    poll.assert_called_once_with(
        mode="sandbox", api_key="scheduler-key", broker_order_id="RECOVER-WORKING"
    )
    assert store.get_run(run.id).stopped_at is not None
    assert state.get_run_state(run.id) is None


def test_pending_stop_repairs_an_accepted_entry_ack_before_cancel_and_poll():
    sid = _make()
    run = store.create_run(sid, "sandbox", "sandbox")
    assert run is not None
    run_id = run.id
    assert store.set_strategy_status(sid, "running", run_id)
    entry = store.record_order(
        run_id,
        1,
        "entry",
        {
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": 75,
            "product": "NRML",
            "pricetype": "MARKET",
            "status": "pending",
            "position_ref": "ack-entry-owner",
        },
    )
    assert entry is not None
    store.record_event(
        sid,
        USER,
        "order_ack_unrecorded",
        "Accepted acknowledgement is pending automatic reconciliation",
        run_id=run_id,
        leg_id=1,
        severity="critical",
        payload={
            "version": 1,
            "order_id": entry.id,
            "run_id": run_id,
            "leg_id": 1,
            "broker_order_id": "ACK-PENDING-ENTRY",
            "accepted": True,
            "status": "open",
            "reject_reason": None,
        },
    )
    assert store.request_run_stop(run_id, "scheduler")
    assert recovery.recover_run(run_id).ok is True

    with (
        patch.object(engine, "_api_key_for", return_value="scheduler-key"),
        patch.object(
            engine.order_dispatch,
            "cancel_order",
            return_value=DispatchResult(
                ok=True,
                broker_order_id="ACK-PENDING-ENTRY",
                response={},
            ),
            create=True,
        ) as cancel,
        patch.object(
            engine.order_dispatch,
            "fetch_order_status",
            return_value=SimpleNamespace(
                ok=True,
                order={
                    "orderid": "ACK-PENDING-ENTRY",
                    "order_status": "cancelled",
                    "filled_quantity": 0,
                    "average_price": 0,
                    "rejection_reason": "",
                },
                error=None,
            ),
            create=True,
        ) as poll,
        patch.object(engine.order_dispatch, "dispatch_order") as duplicate_exit,
        patch.object(engine, "_unsubscribe_run"),
    ):
        result = sched.reconcile_pending_stops()

    assert result == {"examined": 1, "pending": 0, "finalised": 1, "failed": 0}
    cancel.assert_called_once_with(
        mode="sandbox",
        api_key="scheduler-key",
        broker_order_id="ACK-PENDING-ENTRY",
    )
    poll.assert_called_once_with(
        mode="sandbox",
        api_key="scheduler-key",
        broker_order_id="ACK-PENDING-ENTRY",
    )
    duplicate_exit.assert_not_called()
    assert store.get_order(entry.id).status == "cancelled"
    assert store.get_run(run_id).stopped_at is not None


def test_periodic_repair_manages_active_run_fill_after_ack_write_failure():
    sid = _make()
    run = store.create_run(sid, "sandbox", "sandbox")
    assert run is not None
    run_id = run.id
    assert store.set_strategy_status(sid, "running", run_id)
    state.init_run_state(
        run_id,
        sid,
        [
            {
                "leg_id": 1,
                "position": "S",
                "symbol": "NIFTY28MAY2624000CE",
                "exchange": "NFO",
                "lots": 1,
                "quantity": 75,
                "position_ref": "active-ack-owner",
            }
        ],
    )
    entry = store.record_order(
        run_id,
        1,
        "entry",
        {
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": 75,
            "product": "NRML",
            "pricetype": "MARKET",
            "status": "pending",
            "position_ref": "active-ack-owner",
        },
    )
    assert entry is not None
    with state.run_state(run_id) as live:
        live["legs"]["1"]["entry_order_id"] = entry.id
        live["legs"]["1"]["entry_status"] = "open"
        live["legs"]["1"]["status"] = "open"
    store.record_event(
        sid,
        USER,
        "order_ack_unrecorded",
        "Accepted acknowledgement is pending automatic reconciliation",
        run_id=run_id,
        leg_id=1,
        severity="critical",
        payload={
            "version": 1,
            "order_id": entry.id,
            "run_id": run_id,
            "leg_id": 1,
            "broker_order_id": "ACTIVE-ACK-FILL",
            "accepted": True,
            "status": "open",
            "reject_reason": None,
        },
    )

    with (
        patch.object(ack_reconciliation, "_api_key_for", return_value="scheduler-key"),
        patch.object(
            ack_reconciliation.order_dispatch,
            "fetch_order_status",
            return_value=SimpleNamespace(
                ok=True,
                order={
                    "orderid": "ACTIVE-ACK-FILL",
                    "order_status": "complete",
                    "filled_quantity": 75,
                    "average_price": 102.25,
                    "rejection_reason": "",
                },
                error=None,
            ),
            create=True,
        ) as poll,
    ):
        result = sched.reconcile_pending_stops()

    assert result == {"examined": 0, "pending": 0, "finalised": 0, "failed": 0}
    poll.assert_called_once_with(
        mode="sandbox", api_key="scheduler-key", broker_order_id="ACTIVE-ACK-FILL"
    )
    durable = store.get_order(entry.id)
    assert durable.broker_order_id == "ACTIVE-ACK-FILL"
    assert durable.status == "complete"
    assert durable.filled_qty == 75
    live = state.get_run_state(run_id)["legs"]["1"]
    assert live["entry_status"] == "complete"
    assert live["entry_avg"] == pytest.approx(102.25)
    assert live["qty"] == 75
    assert store.get_run(run_id).stop_requested_reason is None


def test_periodic_ack_repair_rotates_through_all_open_runs_with_a_bounded_batch():
    order_ids = []
    for index in range(3):
        sid = _make(_config(name=f"Ack rotation {index}"))
        run = store.create_run(sid, "sandbox", "sandbox")
        assert run is not None
        assert store.set_strategy_status(sid, "running", run.id)
        entry = store.record_order(
            run.id,
            1,
            "entry",
            {
                "symbol": "NIFTY28MAY2624000CE",
                "exchange": "NFO",
                "action": "SELL",
                "qty": 75,
                "product": "NRML",
                "pricetype": "MARKET",
                "status": "pending",
            },
        )
        assert entry is not None
        store.record_event(
            sid,
            USER,
            "order_ack_unrecorded",
            "Rejected acknowledgement is pending automatic reconciliation",
            run_id=run.id,
            leg_id=1,
            severity="critical",
            payload={
                "version": 1,
                "order_id": entry.id,
                "run_id": run.id,
                "leg_id": 1,
                "broker_order_id": None,
                "accepted": False,
                "status": "rejected",
                "reject_reason": "broker refused",
            },
        )
        order_ids.append(entry.id)

    ack_reconciliation._open_run_cursor = 0
    observed = []
    for _ in range(3):
        summary = ack_reconciliation.reconcile_open_runs(
            run_limit=1,
            status_poll_limit=0,
        )
        observed.append(summary.examined)

    assert observed == [1, 1, 1]
    assert [store.get_order(order_id).status for order_id in order_ids] == [
        "rejected",
        "rejected",
        "rejected",
    ]


def _pending_stop_with_working_exit(*, broker_order_id: str):
    sid = _make()
    run = store.create_run(sid, "sandbox", "sandbox")
    assert run is not None
    assert store.set_strategy_status(sid, "running", run.id)
    position_ref = "working-exit-owner"
    entry = store.record_order(
        run.id,
        1,
        "entry",
        {
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": 75,
            "product": "NRML",
            "pricetype": "MARKET",
            "status": "complete",
            "avg_fill_price": 100.0,
            "filled_qty": 75,
            "broker_order_id": "ENTRY-COMPLETE",
            "position_ref": position_ref,
        },
    )
    assert entry is not None
    exit_row = store.record_order(
        run.id,
        1,
        "exit_overall_target",
        {
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "BUY",
            "qty": 75,
            "product": "NRML",
            "pricetype": "MARKET",
            "status": "open",
            "broker_order_id": broker_order_id,
            "position_ref": position_ref,
        },
    )
    assert exit_row is not None
    state.init_run_state(
        run.id,
        sid,
        [
            {
                "leg_id": 1,
                "position": "S",
                "position_ref": position_ref,
                "symbol": "NIFTY28MAY2624000CE",
                "exchange": "NFO",
                "quantity": 75,
            }
        ],
    )
    with state.run_state(run.id) as live:
        leg = live["legs"]["1"]
        leg["entry_order_id"] = entry.id
        leg["entry_status"] = "complete"
        leg["entry_avg"] = 100.0
        leg["status"] = "open"
        leg["exit_order_id"] = exit_row.id
        leg["exit_kind"] = "exit_overall_target"
        live["stopping"] = True
    assert store.request_run_stop(run.id, "overall_target")
    return sid, run.id, exit_row.id


def test_periodic_reconciliation_polls_a_working_exit_whose_terminal_frame_was_lost():
    sid, run_id, exit_row_id = _pending_stop_with_working_exit(
        broker_order_id="LOST-EXIT-COMPLETE"
    )

    with (
        patch.object(engine, "_api_key_for", return_value="scheduler-key"),
        patch.object(engine.order_dispatch, "cancel_order") as cancel,
        patch.object(
            engine.order_dispatch,
            "fetch_order_status",
            return_value=SimpleNamespace(
                ok=True,
                order={
                    "orderid": "LOST-EXIT-COMPLETE",
                    "order_status": "complete",
                    "filled_quantity": 75,
                    "average_price": 95.0,
                    "rejection_reason": "",
                },
                error=None,
            ),
            create=True,
        ) as poll,
        patch.object(engine.order_dispatch, "dispatch_order") as duplicate_exit,
        patch.object(engine, "_unsubscribe_run"),
    ):
        result = sched.reconcile_pending_stops()

    assert result == {"examined": 1, "pending": 0, "finalised": 1, "failed": 0}
    cancel.assert_not_called()
    poll.assert_called_once_with(
        mode="sandbox",
        api_key="scheduler-key",
        broker_order_id="LOST-EXIT-COMPLETE",
    )
    duplicate_exit.assert_not_called()
    assert store.list_orders(run_id)[1]["id"] == exit_row_id
    assert store.list_orders(run_id)[1]["status"] == "complete"
    stopped = store.get_run(run_id)
    assert stopped.stopped_at is not None
    assert stopped.stop_reason == "overall_target"
    assert float(stopped.pnl_realized) == pytest.approx(375.0)
    assert store.get_strategy(sid, USER).status == "stopped"


def test_pending_stop_repairs_an_accepted_exit_ack_before_polling_without_duplicate_exit():
    sid = _make()
    run = store.create_run(sid, "sandbox", "sandbox")
    assert run is not None
    run_id = run.id
    assert store.set_strategy_status(sid, "running", run_id)
    position_ref = "ack-exit-owner"
    entry = store.record_order(
        run_id,
        1,
        "entry",
        {
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "SELL",
            "qty": 75,
            "product": "NRML",
            "pricetype": "MARKET",
            "status": "complete",
            "avg_fill_price": 100.0,
            "filled_qty": 75,
            "broker_order_id": "ACK-EXIT-ENTRY",
            "position_ref": position_ref,
        },
    )
    exit_row = store.record_order(
        run_id,
        1,
        "exit_overall_target",
        {
            "symbol": "NIFTY28MAY2624000CE",
            "exchange": "NFO",
            "action": "BUY",
            "qty": 75,
            "product": "NRML",
            "pricetype": "MARKET",
            "status": "pending",
            "position_ref": position_ref,
        },
    )
    assert entry is not None and exit_row is not None
    store.record_event(
        sid,
        USER,
        "order_ack_unrecorded",
        "Accepted acknowledgement is pending automatic reconciliation",
        run_id=run_id,
        leg_id=1,
        severity="critical",
        payload={
            "version": 1,
            "order_id": exit_row.id,
            "run_id": run_id,
            "leg_id": 1,
            "broker_order_id": "ACK-PENDING-EXIT",
            "accepted": True,
            "status": "open",
            "reject_reason": None,
        },
    )
    assert store.request_run_stop(run_id, "overall_target")
    assert recovery.recover_run(run_id).ok is True

    with (
        patch.object(engine, "_api_key_for", return_value="scheduler-key"),
        patch.object(engine.order_dispatch, "cancel_order") as cancel,
        patch.object(
            engine.order_dispatch,
            "fetch_order_status",
            return_value=SimpleNamespace(
                ok=True,
                order={
                    "orderid": "ACK-PENDING-EXIT",
                    "order_status": "complete",
                    "filled_quantity": 75,
                    "average_price": 95.0,
                    "rejection_reason": "",
                },
                error=None,
            ),
            create=True,
        ) as poll,
        patch.object(engine.order_dispatch, "dispatch_order") as duplicate_exit,
        patch.object(engine, "_unsubscribe_run"),
    ):
        result = sched.reconcile_pending_stops()

    assert result == {"examined": 1, "pending": 0, "finalised": 1, "failed": 0}
    cancel.assert_not_called()
    poll.assert_called_once_with(
        mode="sandbox",
        api_key="scheduler-key",
        broker_order_id="ACK-PENDING-EXIT",
    )
    duplicate_exit.assert_not_called()
    assert store.get_order(exit_row.id).status == "complete"
    assert store.get_run(run_id).stopped_at is not None


def test_periodic_reconciliation_retries_only_the_unfilled_exit_remainder():
    _, run_id, _ = _pending_stop_with_working_exit(
        broker_order_id="LOST-EXIT-PARTIAL"
    )
    placed = []

    def accept_remainder(**kwargs):
        placed.append(kwargs["order"])
        return DispatchResult(
            ok=True,
            broker_order_id="REMAINDER-EXIT",
            response={},
        )

    with (
        patch.object(engine, "_api_key_for", return_value="scheduler-key"),
        patch.object(
            engine.order_dispatch,
            "fetch_order_status",
            return_value=SimpleNamespace(
                ok=True,
                order={
                    "orderid": "LOST-EXIT-PARTIAL",
                    "order_status": "cancelled",
                    "filled_quantity": 25,
                    "average_price": 95.0,
                    "rejection_reason": "cancelled remainder",
                },
                error=None,
            ),
            create=True,
        ),
        patch.object(
            engine.order_dispatch,
            "dispatch_order",
            side_effect=accept_remainder,
        ),
    ):
        result = sched.reconcile_pending_stops()

    assert result == {"examined": 1, "pending": 1, "finalised": 0, "failed": 0}
    assert len(placed) == 1
    assert placed[0]["quantity"] == "50"
    durable = store.list_orders(run_id)
    assert [
        int(row["filled_qty"] or 0) for row in durable if row["kind"] != "entry"
    ] == [25, 0]
    assert state.get_run_state(run_id)["legs"]["1"]["qty"] == 50


# ---------------------------------------------------------------------------
# Session hygiene
# ---------------------------------------------------------------------------


def test_the_start_job_releases_its_scoped_sessions_even_when_the_engine_raises():
    # A scheduler worker has no Flask app context, so teardown_appcontext never
    # fires and the sessions the job touched stay bound to that thread for the
    # life of a single Gunicorn worker that never restarts (issue #1738).
    sid = _make()

    with (
        patch.object(engine, "start_run", side_effect=RuntimeError("engine exploded")),
        patch("utils.db_sessions.remove_all_scoped_sessions") as release,
    ):
        sched.run_scheduled_start(sid)

    # Released even though the engine raised: this is a finally, not a happy path.
    release.assert_called_once()


def test_the_stop_job_releases_its_scoped_sessions_even_when_the_engine_raises():
    sid = _make()
    store.set_strategy_status(sid, "running", 61)

    with (
        patch.object(engine, "stop_run", side_effect=RuntimeError("engine exploded")),
        patch("utils.db_sessions.remove_all_scoped_sessions") as release,
    ):
        sched.run_scheduled_stop(sid)

    release.assert_called_once()
