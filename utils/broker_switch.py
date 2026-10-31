# utils/broker_switch.py
"""Whether the logged-in broker's session may end for a switch to another.

One broker is logged in at a time, so a login to another broker ends the live
session when it completes. Anything still trading on the old broker would then
send its orders through the new one, or lose the stop watching its position.
As OpenAlgo Desktop does (``services/broker_switch.rs``), the switch is refused
while the live broker still has running Live automation, and the trader is
told what to stop first.

What counts here: strategy module runs in Live mode, OpenScript runs started in
Live mode, and, while the platform is not in analyzer mode, running Python
strategies and positions under scalping protection.
"""

import sys

from utils.logging import get_logger

logger = get_logger(__name__)


def _counted(n, one, many):
    if n == 0:
        return None
    return f"1 {one}" if n == 1 else f"{n} {many}"


def _blockers(username):
    """(Live strategies, Live OpenScript runs, Python strategies, protected positions)."""
    from database.settings_db import get_analyze_mode
    from database.strategy_module_db import count_live_running_strategies
    from services.openscript_run_config import run_mode_of
    from services.openscript_running import all_running

    live_platform = not get_analyze_mode()
    strategy_runs = count_live_running_strategies(username)
    openscript_runs = sum(
        1
        for name in all_running()
        if run_mode_of(name) == "live" or (run_mode_of(name) == "" and live_platform)
    )

    python_runs = 0
    protected = 0
    if live_platform:
        # Only modules already loaded: what was never imported is not running,
        # and importing the strategy host here would start its scheduler.
        python_strategy = sys.modules.get("blueprints.python_strategy")
        if python_strategy is not None:
            python_runs = len(python_strategy.snapshot_running_strategies())
        scalping = sys.modules.get("services.scalping_risk_monitor_service")
        if scalping is not None:
            protected = scalping.get_scalping_risk_monitor().protected_count()
    return strategy_runs, openscript_runs, python_runs, protected


def previous_broker(username):
    """The broker logged in now, or else the one logged in to last.

    A logout clears the stored session but leaves its automation running, so
    the broker that automation trades through is still the one logged in to
    last (the latest successful broker login).
    """
    from utils.broker_keys import live_broker

    live = live_broker()
    if live:
        return live
    try:
        from database.auth_db import LoginAttempt

        row = (
            LoginAttempt.query.filter(
                LoginAttempt.username == username,
                LoginAttempt.status == "success",
                LoginAttempt.broker.isnot(None),
                LoginAttempt.broker != "",
            )
            .order_by(LoginAttempt.timestamp.desc())
            .first()
        )
        return row.broker if row else None
    except Exception:
        logger.exception("Could not read the broker logged in to last")
        return None


def refusal_for_login(broker, username):
    """Why a login to `broker` may not go ahead, or None.

    A login to another broker than the one logged in now (or last, after a
    logout) is refused while that broker still runs Live automation. Logging
    back in to the same broker is always allowed.
    """
    previous = previous_broker(username)
    if not previous or previous == broker:
        return None
    return switch_refusal(previous, username)


def switch_refusal(live_broker, username):
    """Why the live broker's session cannot end for a switch now, or None.

    Args:
        live_broker: The broker logged in now.
        username: The OpenAlgo user.

    Returns:
        str | None: A sentence for the trader naming what still runs.
    """
    from utils.broker_keys import broker_title

    name = broker_title(live_broker)
    try:
        strategy_runs, openscript_runs, python_runs, protected = _blockers(username)
    except Exception:
        logger.exception("Could not check what still runs on the broker session")
        return (
            f"OpenAlgo could not check whether anything still runs on {name}. "
            "Nothing was changed. Try again."
        )

    items = [
        item
        for item in (
            _counted(strategy_runs, "running Live strategy", "running Live strategies"),
            _counted(
                openscript_runs, "running Live OpenScript run", "running Live OpenScript runs"
            ),
            _counted(python_runs, "running Python strategy", "running Python strategies"),
            _counted(
                protected,
                "position under scalping protection",
                "positions under scalping protection",
            ),
        )
        if item
    ]
    if not items:
        return None
    listed = items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"
    return (
        f"{name} still has {listed}. They are not moved to another broker. "
        "First stop the strategies and protection, then switch. Nothing was changed."
    )
