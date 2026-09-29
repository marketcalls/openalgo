"""Request schemas for the external ``/api/v1/strategy`` surface.

Its own module rather than an addition to ``data_schemas.py``: that file is the
market-data boundary (quotes, history, depth, expiry, option chain), while these
are strategy-lifecycle requests and sit closer in kind to ``account_schema.py``.

The vocabulary is imported from ``database.strategy_module_db`` rather than
restated here, so the API and the store cannot drift apart about what a mode, a
status, an event kind or a severity is. The store keeps those as plain tuples
instead of SQL CHECK constraints (SQLite cannot alter a constraint in place),
which makes this file one of the two places a bad value is refused at all.

One rule outranks everything else in here: ``mode`` on start is ``required=True``
and has no ``load_default``. A caller that omits it is refused. The default a
hurried reader would reach for is the one that places real orders, so there is
no default at all.
"""

from marshmallow import Schema, fields, validate

from database.strategy_module_db import (
    EVENT_KINDS,
    EVENT_SEVERITIES,
    RUN_MODES,
    STRATEGY_STATUSES,
)

#: Event history page size. The engine writes an event per risk transition per
#: leg, so an unbounded read would serialize a whole trading day. Mirrors the
#: ceiling the session-authenticated /strategy pages already apply.
EVENTS_DEFAULT_LIMIT = 500
EVENTS_MAX_LIMIT = 1000

#: Run history page size, matching the store's own default.
RUNS_DEFAULT_LIMIT = 100
RUNS_MAX_LIMIT = 500

#: Longest free-text search accepted by ``/list``.
MAX_QUERY_LENGTH = 100


class StrategyListSchema(Schema):
    """``/list``: the strategies this API key owns, optionally filtered."""

    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    status = fields.Str(
        load_default=None, allow_none=True, validate=validate.OneOf(STRATEGY_STATUSES)
    )
    q = fields.Str(
        load_default=None, allow_none=True, validate=validate.Length(max=MAX_QUERY_LENGTH)
    )


class StrategyRefSchema(Schema):
    """Names one strategy, and nothing else.

    The base every other request here builds on, and the whole of the body for
    ``/status``, ``/stop`` and ``/close_all``. The identifier travels in the
    body rather than the path because TradingView, Excel and the other external
    callers cannot always choose a URL or set a header.
    """

    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    strategy_id = fields.Int(required=True, validate=validate.Range(min=1))


class StrategyStartSchema(StrategyRefSchema):
    """``/start``: the only request in this module that can place a real order.

    ``mode`` is required with no default, and ``validate.OneOf`` rejects
    anything that is not exactly ``live`` or ``sandbox``. Both halves matter: a
    default would let a caller that forgot the field trade for real, and a
    permissive value would let a typo such as ``"paper"`` be read as something
    it is not.
    """

    mode = fields.Str(required=True, validate=validate.OneOf(RUN_MODES))


class StrategyCloseLegSchema(StrategyRefSchema):
    """``/close_leg``: exit one leg of the strategy's current run.

    The run is resolved from the strategy, so the caller never supplies a run
    id. Leg ids are the 1-based ids the wizard assigns within a strategy.
    """

    leg_id = fields.Int(required=True, validate=validate.Range(min=1))


class StrategyRunsSchema(StrategyRefSchema):
    """``/runs``: every activation of this strategy, newest first."""

    limit = fields.Int(
        load_default=RUNS_DEFAULT_LIMIT,
        validate=validate.Range(min=1, max=RUNS_MAX_LIMIT),
    )


class StrategyOrdersSchema(StrategyRefSchema):
    """``/orders``: orders across this strategy's runs, optionally one run."""

    run_id = fields.Int(load_default=None, allow_none=True, validate=validate.Range(min=1))


class StrategyEventsSchema(StrategyRefSchema):
    """``/events``: the risk-event audit trail for this strategy.

    ``limit`` is bounded rather than silently clamped, so a caller learns that
    the value was refused. The lower bound is not cosmetic: SQLite reads a
    negative LIMIT as "no limit", so an unbounded field would let ``limit: -1``
    serialize every event the strategy has ever recorded.
    """

    run_id = fields.Int(load_default=None, allow_none=True, validate=validate.Range(min=1))
    kind = fields.Str(load_default=None, allow_none=True, validate=validate.OneOf(EVENT_KINDS))
    severity = fields.Str(
        load_default=None, allow_none=True, validate=validate.OneOf(EVENT_SEVERITIES)
    )
    limit = fields.Int(
        load_default=EVENTS_DEFAULT_LIMIT,
        validate=validate.Range(min=1, max=EVENTS_MAX_LIMIT),
    )
