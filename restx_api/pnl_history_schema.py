# restx_api/pnl_history_schema.py
"""Marshmallow schemas for the /api/v1/pnl/* resources (restx_api/pnl_history.py)."""

from marshmallow import Schema, fields, validate

from database.pnl_db import VALID_SEGMENTS


class PnlHistorySchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    start_date = fields.Str(required=True, validate=validate.Length(equal=10))
    end_date = fields.Str(required=True, validate=validate.Length(equal=10))
    symbol = fields.Str(required=False, load_default=None)
    # One of database.pnl_db.VALID_SEGMENTS. "mutual_fund" is accepted for
    # parity with Zerodha Console's own segment picker (the reference this
    # filter row is modeled on) even though no OpenAlgo exchange constant
    # maps to it today - it will simply never match a real row until MF
    # broker support exists. Omitted/empty means no segment filter.
    segment = fields.Str(
        required=False, load_default=None, validate=validate.OneOf(list(VALID_SEGMENTS))
    )
    # Free-text: strategy names come from database.strategy_book_db, an open-ended
    # set. Omitted means no strategy filter.
    strategy = fields.Str(required=False, load_default=None)


class PnlCurveSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    start_date = fields.Str(required=True, validate=validate.Length(equal=10))
    end_date = fields.Str(required=True, validate=validate.Length(equal=10))
    # range_start: lots carried into the range are valued from the close before
    # it, so a window holds only what was earned in it. actual_cost: the fill
    # price, as the broker's own report does.
    basis = fields.Str(
        required=False,
        load_default="range_start",
        validate=validate.OneOf(["range_start", "actual_cost"]),
    )
    # Case-insensitive part of a symbol; narrows the fills before matching.
    symbol_contains = fields.Str(required=False, load_default=None)


class PnlImportSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    # The uploaded file itself arrives as multipart/form-data, not JSON, so
    # it's read directly from request.files in the resource rather than
    # validated by this schema - Marshmallow here only covers the apikey
    # form field sent alongside it.


class PnlStrategyLegsSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    strategy = fields.Str(required=False, load_default=None)


class PnlSetTradeStrategySchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    strategy = fields.Str(required=True, validate=validate.Length(min=1, max=120))
