"""External API for the /strategy module: multi-leg options strategies.

Lifecycle plus reads, deliberately not full CRUD. Building a multi-leg strategy
is a wizard job and stays in the browser at ``/strategy``; what TradingView, the
Python SDK, Excel and MCP need is to start one, stop one, close a leg, and read
what happened. A thinner API-key surface is less to secure: nothing here can
create a strategy, edit its configuration, enable live trading, rotate a webhook
token, or delete anything.

Every route is a POST with the identifier in the body, matching the rest of
``/api/v1``. External callers cannot always choose a method or set a header, so
a path parameter or a GET would put this surface out of their reach.

Four rules this module holds to.

**Mode is required on start, and is never defaulted.** A caller that omits it
gets a 400, not a live order. Marshmallow enforces it (``required=True`` with no
``load_default``) and this module never supplies a fallback of its own. It is
the single most important line in the file.

**Live is opt-in per strategy.** ``mode: "live"`` is refused unless the strategy
carries ``live_enabled``. The engine checks this too, and that check stays; this
one exists so the refusal happens a layer before the order path and carries a
message the caller can act on.

**404, never 403, for a strategy that is not yours.** Every route resolves
through the owner-scoped ``store.get_strategy`` before doing anything else, so a
strategy belonging to somebody else is indistinguishable from one that does not
exist. A 403 would confirm the id is real and let the id space be probed.

**No route returns a webhook token.** Only its SHA-256 digest is stored, so
there is nothing to return, and no route here implies otherwise:
``strategy_to_dict`` never carries the plaintext, and creation and rotation --
the only two places it has ever existed -- are not part of this surface.
"""

import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from database import strategy_module_db as store
from database.auth_db import verify_api_key
from limiter import limiter
from restx_api.strategy_schema import (
    StrategyCloseLegSchema,
    StrategyEventsSchema,
    StrategyListSchema,
    StrategyOrdersSchema,
    StrategyRefSchema,
    StrategyRunsSchema,
    StrategyStartSchema,
)
from services.strategy_module.audit_messages import CLOSE_ALL_REQUESTED_MESSAGE
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace("strategy", description="Strategy module API: lifecycle and history")

logger = get_logger(__name__)

#: The same message for a strategy that does not exist and one that is not
#: yours. Two different messages would be as good as a 403.
NOT_FOUND = "Strategy not found"

NOT_RUNNING = "This strategy is not running"

INVALID_KEY = "Invalid openalgo apikey"

list_schema = StrategyListSchema()
ref_schema = StrategyRefSchema()
start_schema = StrategyStartSchema()
close_leg_schema = StrategyCloseLegSchema()
runs_schema = StrategyRunsSchema()
orders_schema = StrategyOrdersSchema()
events_schema = StrategyEventsSchema()


def _engine():
    """The strategy engine, imported on use rather than at module scope.

    The engine pulls in the order path, which imports back into ``restx_api``.
    This module lives inside ``restx_api``, so importing the engine at module
    scope would make ``restx_api/__init__`` the entry point of that cycle.
    Deferring it also keeps application startup from loading the risk and
    symbol-resolution stack for endpoints that may never be called.
    """
    from services.strategy_module import engine

    return engine


def _success(payload: dict | None = None, code: int = 200):
    body = {"status": "success"}
    if payload:
        body.update(payload)
    return make_response(jsonify(body), code)


def _failure(message, code: int, payload: dict | None = None):
    body = {"status": "error", "message": message}
    if payload:
        body.update(payload)
    return make_response(jsonify(body), code)


def _resolve(schema, *, needs_strategy: bool = True):
    """Validate the body, authenticate the key, and load the strategy.

    Returns ``(data, user_id, row, error_response)``; exactly one of ``row`` and
    ``error_response`` is meaningful. Ownership is not a separate step: the
    store's ``get_strategy`` takes the user id in its signature so no call site
    can forget it, and a miss is reported as 404 whether the row is absent or
    belongs to somebody else.
    """
    try:
        data = schema.load(request.get_json(silent=True) or {})
    except ValidationError as err:
        return None, None, None, _failure(err.messages, 400)

    api_key = data.pop("apikey")
    user_id = verify_api_key(api_key)
    if user_id is None:
        return None, None, None, _failure(INVALID_KEY, 403)

    if not needs_strategy:
        return data, user_id, None, None

    row = store.get_strategy(data["strategy_id"], user_id)
    if row is None:
        return data, user_id, None, _failure(NOT_FOUND, 404)

    return data, user_id, row, None


def _stop_current_run(row, user_id: str, *, event: str | None = None):
    """Exit every open leg of the strategy's current run and finalise it.

    The run id is resolved from the strategy rather than taken from the caller.
    A caller-supplied run id would be a second thing to authorise, and getting
    it wrong would mean stopping a run that is not the live one.
    """
    run_id = row.current_run_id
    if not run_id:
        # A state conflict, not a malformed request: the caller's fix is to
        # start the strategy, not to change the payload.
        return _failure(NOT_RUNNING, 409)

    if event:
        store.record_event(
            row.id,
            user_id,
            event,
            CLOSE_ALL_REQUESTED_MESSAGE,
            run_id=run_id,
        )

    result = _engine().stop_run(run_id, user_id, reason="manual")
    if not result.get("ok"):
        return _failure(
            result.get("error") or "Could not stop the run",
            409,
            {
                "stop_pending": result.get("stop_pending", False),
                "exits": result.get("exits", []),
            },
        )

    return _success(
        {
            "run_id": run_id,
            "stop_pending": result.get("stop_pending", False),
            "exits": result.get("exits", []),
        }
    )


@api.route("/list", strict_slashes=False)
class StrategyList(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """List the strategies this API key owns, newest first."""
        try:
            data, user_id, _row, error = _resolve(list_schema, needs_strategy=False)
            if error:
                return error

            query = (data.get("q") or "").strip() or None
            rows = store.list_strategies(user_id, status=data.get("status"), q=query)
            return _success({"data": rows})
        except Exception:
            logger.exception("Unexpected error in strategy list endpoint")
            return _failure("An unexpected error occurred", 500)


@api.route("/status", strict_slashes=False)
class StrategyStatus(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """One strategy: its configuration and its current run, if any."""
        try:
            _data, _user_id, row, error = _resolve(ref_schema)
            if error:
                return error

            run = None
            if row.current_run_id:
                # Owner-scoped by construction: the run id was read off a
                # strategy this API key already proved it owns.
                run_row = store.get_run(row.current_run_id)
                if run_row is not None:
                    run = store.run_to_dict(run_row)

            # strategy_to_dict never carries the webhook token; only its hash
            # is stored, and the plaintext is unrecoverable by design.
            return _success({"data": store.strategy_to_dict(row), "run": run})
        except Exception:
            logger.exception("Unexpected error in strategy status endpoint")
            return _failure("An unexpected error occurred", 500)


@api.route("/start", strict_slashes=False)
class StrategyStart(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Start a run in the mode the caller asks for.

        ``mode`` is required and never defaulted, and ``live`` is refused unless
        the strategy is enabled for it.
        """
        try:
            data, user_id, row, error = _resolve(start_schema)
            if error:
                return error

            mode = data["mode"]
            if mode == "live" and not row.live_enabled:
                # A state conflict rather than a bad payload: the caller's fix
                # is to enable live trading on the strategy, or to ask for
                # sandbox, not to correct the request.
                return _failure(
                    "This strategy is not enabled for live trading. Enable it on the "
                    "strategy page, or start it with mode 'sandbox'.",
                    409,
                )

            # trigger_source is 'manual' because the store's TRIGGER_SOURCES
            # vocabulary is manual, webhook and scheduler; an API-key start is
            # a person asking for it right now, which is what 'manual' means
            # here. The alternative would be adding a value to the store's
            # enumeration, which the UI filters on.
            result = _engine().start_run(row.id, user_id, mode, trigger_source="manual")
            if not result.ok:
                # An already-running strategy is a conflict; anything else the
                # engine refused is a bad configuration the caller must fix.
                code = 409 if "already running" in (result.error or "") else 400
                return _failure(result.error or "Could not start the strategy", code)

            return _success({"run_id": result.run_id, "mode": mode, "legs": result.legs})
        except Exception:
            logger.exception("Unexpected error in strategy start endpoint")
            return _failure("An unexpected error occurred", 500)


@api.route("/stop", strict_slashes=False)
class StrategyStop(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Exit every open leg at market and stop the current run."""
        try:
            _data, user_id, row, error = _resolve(ref_schema)
            if error:
                return error
            return _stop_current_run(row, user_id)
        except Exception:
            logger.exception("Unexpected error in strategy stop endpoint")
            return _failure("An unexpected error occurred", 500)


@api.route("/close_all", strict_slashes=False)
class StrategyCloseAll(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Same effect as stop, named for what the caller is doing.

        Kept as its own route rather than an alias so the audit trail records
        the intent: "the operator closed everything" reads differently from
        "the run was stopped" when reconstructing a session afterwards.
        """
        try:
            _data, user_id, row, error = _resolve(ref_schema)
            if error:
                return error
            return _stop_current_run(row, user_id, event="close_all_manual")
        except Exception:
            logger.exception("Unexpected error in strategy close_all endpoint")
            return _failure("An unexpected error occurred", 500)


@api.route("/close_leg", strict_slashes=False)
class StrategyCloseLeg(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Exit one leg of the current run. The run continues with the rest."""
        try:
            data, user_id, row, error = _resolve(close_leg_schema)
            if error:
                return error

            run_id = row.current_run_id
            if not run_id:
                return _failure(NOT_RUNNING, 409)

            leg_id = data["leg_id"]
            result = _engine().close_leg(run_id, leg_id, user_id)
            if not result.get("ok"):
                return _failure(result.get("error") or "Could not close that leg", 409)

            return _success(
                {
                    "run_id": run_id,
                    "leg_id": leg_id,
                    "run_stopped": result.get("run_stopped", False),
                    "exits": result.get("exits", []),
                }
            )
        except Exception:
            logger.exception("Unexpected error in strategy close_leg endpoint")
            return _failure("An unexpected error occurred", 500)


@api.route("/runs", strict_slashes=False)
class StrategyRuns(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Every activation of this strategy, newest first."""
        try:
            data, _user_id, row, error = _resolve(runs_schema)
            if error:
                return error
            return _success({"data": store.list_runs(row.id, limit=data["limit"])})
        except Exception:
            logger.exception("Unexpected error in strategy runs endpoint")
            return _failure("An unexpected error occurred", 500)


@api.route("/orders", strict_slashes=False)
class StrategyOrders(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """Orders across this strategy's runs, optionally narrowed to one run.

        ``run_id`` needs no separate ownership check: the store joins through
        ``sm_strategy_run`` on this strategy's id, so another strategy's run
        matches nothing rather than leaking its orders.
        """
        try:
            data, _user_id, row, error = _resolve(orders_schema)
            if error:
                return error
            orders = store.list_orders_for_strategy(row.id, run_id=data.get("run_id"))
            return _success({"data": orders})
        except Exception:
            logger.exception("Unexpected error in strategy orders endpoint")
            return _failure("An unexpected error occurred", 500)


@api.route("/events", strict_slashes=False)
class StrategyEvents(Resource):
    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        """The risk-event audit trail for this strategy, newest first."""
        try:
            data, _user_id, row, error = _resolve(events_schema)
            if error:
                return error

            events = store.list_events(
                row.id,
                run_id=data.get("run_id"),
                kind=data.get("kind"),
                severity=data.get("severity"),
                limit=data["limit"],
            )
            return _success({"data": events})
        except Exception:
            logger.exception("Unexpected error in strategy events endpoint")
            return _failure("An unexpected error occurred", 500)
