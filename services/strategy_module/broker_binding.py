"""Which broker a Live run's orders belong to.

A run records the broker it started on (``SmStrategyRun.broker``) and, when the
session names one, the broker account (``SmStrategyRun.broker_account``). Every
Live order, cancel and status read the run makes afterwards is held to that
record by ``order_dispatch``, which refuses the call when OpenAlgo is logged in
to another broker or account. This module reads the record for a caller and,
for the stop and tick paths, asks the same question before any order row is
written, so a refusal that will last until the trader logs back in is reported
once rather than once per tick or per retry.

A run that started with no broker logged in (a signal run opened before the
day's login) has no broker to be held to yet. Its first Live call binds it to
the session of that moment, with a conditional write only one caller can win.

Nothing here holds a lock: every read and write is a short database or cached
auth lookup made by a caller that is already outside the run lock.
"""

from __future__ import annotations

from database import strategy_module_db as store
from services.strategy_module import order_dispatch
from services.strategy_module.order_dispatch import BrokerBinding
from utils.logging import get_logger

logger = get_logger(__name__)


def for_run(run_id: int, *, api_key: str, user_id: str) -> BrokerBinding | None:
    """The run's broker binding, binding it first if it has none. None if no run.

    Only meaningful for a Live run; a sandbox run's binding is never read.
    """
    read = _read_binding(run_id, api_key=api_key, user_id=user_id)
    return read[1] if read is not None else None


def refusal_for_run(run_id: int, *, api_key: str, user_id: str) -> str | None:
    """Why this Live run's orders cannot go through the current session, or None.

    None also when there is no session at all: that case already has its own
    handling and its own message on every path, and is not a broker mismatch.
    """
    read = _read_binding(run_id, api_key=api_key, user_id=user_id)
    if read is None or read[0] != "live":
        return None
    binding = read[1]
    _token, broker, error = order_dispatch.resolve_live_auth(api_key)
    if error:
        return None
    account = order_dispatch.session_account(user_id) if binding.account else None
    return order_dispatch.binding_refusal(binding, broker, account)


def _read_binding(run_id: int, *, api_key: str, user_id: str) -> tuple[str, BrokerBinding] | None:
    """``(mode, binding)`` for a run, binding an unbound Live run first."""
    run = store.get_run(run_id)
    if run is None:
        return None
    # Scalars now: a commit on this thread, or a synchronous fill replay that
    # removes the scoped session, can expire or detach the row.
    mode = str(run.mode)
    binding = BrokerBinding(
        broker=str(run.broker or ""),
        account=run.broker_account,
        user_id=user_id,
    )
    if mode != "live" or binding.known:
        return mode, binding

    # Started with no broker logged in. Bind it to the session placing its
    # first Live order; with no session the order is refused for that reason.
    _token, broker, error = order_dispatch.resolve_live_auth(api_key)
    if error or not broker:
        return mode, binding
    account = order_dispatch.session_account(user_id)
    if store.bind_run_broker(run_id, broker, account):
        logger.info("Run %s bound to broker %s on its first Live order", run_id, broker)
    # Read back whichever bind won: a racing order may have bound it first.
    bound = store.get_run(run_id)
    if bound is None:
        return mode, binding
    return mode, BrokerBinding(
        broker=str(bound.broker or ""),
        account=bound.broker_account,
        user_id=user_id,
    )
