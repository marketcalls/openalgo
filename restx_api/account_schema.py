from marshmallow import INCLUDE, Schema, fields, validate


class FundsSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class OrderbookSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class TradebookSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class PositionbookSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class HoldingsSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class OrderStatusSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    strategy = fields.Str(required=True)
    orderid = fields.Str(required=True)


class OpenPositionSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    strategy = fields.Str(required=True)
    symbol = fields.Str(required=True)
    exchange = fields.Str(required=True)
    product = fields.Str(required=True, validate=validate.OneOf(["MIS", "NRML", "CNC"]))


class AnalyzerSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class AnalyzerToggleSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    mode = fields.Bool(required=True)


class AnalyzerIntakeSchema(Schema):
    """Decision-telemetry intake payload (ADR-006 Amendment 5 producer contract).

    The producer is an external strategy process (LOATS) whose routed
    TradeDecision payload carries exactly these decision fields plus the
    standard ``apikey``. Unknown fields are retained rather than rejected so
    the producer can extend its telemetry without a gateway release; the
    required fields are the minimum a decision row must carry to be
    attributable.
    """

    class Meta:
        # Decision telemetry is producer-owned and evolving; keep extra keys.
        unknown = INCLUDE

    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    decision_id = fields.Str(required=True, validate=validate.Length(min=1, max=256))
    symbol = fields.Str(required=True, validate=validate.Length(min=1, max=64))
    decision_type = fields.Str(required=True, validate=validate.Length(min=1, max=64))
    timestamp = fields.Str(required=True, validate=validate.Length(min=1, max=64))


class PingSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))


class ChartSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))

    class Meta:
        # Allow unknown fields - chart preferences can have any key-value pairs
        unknown = INCLUDE


class PnlSymbolsSchema(Schema):
    apikey = fields.Str(required=True, validate=validate.Length(min=1, max=256))
