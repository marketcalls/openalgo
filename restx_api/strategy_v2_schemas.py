"""Marshmallow schemas for /strategy/api/v2 endpoints.

Strict-mode schemas (`unknown=RAISE`) — unknown fields fail validation rather
than being silently ignored. Reduces the attack surface and surfaces typos
during integration.
"""

from marshmallow import EXCLUDE, RAISE, Schema, ValidationError, fields, validate


# ----------------------------------------------------------------------------
# Strategy
# ----------------------------------------------------------------------------


class StrategyCreateSchema(Schema):
    class Meta:
        unknown = RAISE

    name = fields.String(required=True, validate=validate.Length(min=3, max=80))
    platform = fields.String(load_default="manual",
                              validate=validate.OneOf(
                                  ["tradingview", "amibroker", "python", "manual", "chartink"]
                              ))
    underlying = fields.String(load_default=None, allow_none=True)
    underlying_exchange = fields.String(
        load_default=None,
        allow_none=True,
        validate=validate.OneOf(
            ["NSE_INDEX", "BSE_INDEX", "MCX_INDEX", "GLOBAL_INDEX", "NSE", "BSE", "NFO", "BFO", None]
        ),
    )
    is_intraday = fields.Boolean(load_default=True)
    start_time = fields.String(required=True,
                               validate=validate.Regexp(r"^[0-2]\d:[0-5]\d$"))
    end_time = fields.String(required=True,
                             validate=validate.Regexp(r"^[0-2]\d:[0-5]\d$"))
    squareoff_time = fields.String(load_default=None, allow_none=True,
                                   validate=validate.Regexp(r"^[0-2]\d:[0-5]\d$"))
    mode = fields.String(load_default="live",
                         validate=validate.OneOf(["live", "sandbox"]))
    webhook_signing_method = fields.String(
        load_default="NONE",
        validate=validate.OneOf(["NONE", "BODY_SECRET", "HMAC_SHA256", "BOTH"]),
    )
    webhook_replay_window_seconds = fields.Integer(load_default=0,
                                                    validate=validate.Range(min=0, max=3600))
    webhook_ip_allowlist = fields.List(fields.String(),
                                        load_default=None,
                                        allow_none=True)


class StrategyUpdateSchema(Schema):
    """All fields optional — partial update."""
    class Meta:
        unknown = RAISE

    name = fields.String(validate=validate.Length(min=3, max=80))
    platform = fields.String(validate=validate.OneOf(
        ["tradingview", "amibroker", "python", "manual", "chartink"]))
    underlying = fields.String(allow_none=True)
    underlying_exchange = fields.String(allow_none=True)
    is_intraday = fields.Boolean()
    start_time = fields.String(validate=validate.Regexp(r"^[0-2]\d:[0-5]\d$"))
    end_time = fields.String(validate=validate.Regexp(r"^[0-2]\d:[0-5]\d$"))
    squareoff_time = fields.String(allow_none=True,
                                   validate=validate.Regexp(r"^[0-2]\d:[0-5]\d$"))
    mode = fields.String(validate=validate.OneOf(["live", "sandbox"]))
    webhook_signing_method = fields.String(
        validate=validate.OneOf(["NONE", "BODY_SECRET", "HMAC_SHA256", "BOTH"]),
    )
    webhook_replay_window_seconds = fields.Integer(validate=validate.Range(min=0, max=3600))
    webhook_ip_allowlist = fields.List(fields.String(), allow_none=True)
    is_active = fields.Boolean()


# ----------------------------------------------------------------------------
# Leg
# ----------------------------------------------------------------------------


class LegSchema(Schema):
    class Meta:
        unknown = RAISE

    leg_index = fields.Integer(required=True, validate=validate.Range(min=1))
    segment = fields.String(required=True, validate=validate.OneOf(["CASH", "FUT", "OPT"]))
    position = fields.String(required=True, validate=validate.OneOf(["B", "S"]))
    product = fields.String(required=True, validate=validate.OneOf(["MIS", "CNC", "NRML"]))

    # CASH-only
    symbol_cash = fields.String(allow_none=True)
    qty = fields.Integer(allow_none=True, validate=validate.Range(min=1))

    # FUT + OPT
    expiry_type = fields.String(
        allow_none=True,
        validate=validate.OneOf(
            ["CURRENT_WEEK", "NEXT_WEEK", "CURRENT_MONTH", "NEXT_MONTH"]
        ),
    )
    lots = fields.Integer(allow_none=True, validate=validate.Range(min=1))

    # OPT-only
    option_type = fields.String(allow_none=True, validate=validate.OneOf(["CE", "PE"]))
    strike_criteria = fields.String(
        allow_none=True,
        validate=validate.OneOf(["ATM", "STRIKE_OFFSET", "PREMIUM", "DELTA"]),
    )
    strike_value = fields.Float(allow_none=True)

    # Per-leg risk (each pair: pts or pct)
    target_enabled = fields.Boolean(load_default=False)
    target_value = fields.Float(allow_none=True)
    target_unit = fields.String(allow_none=True, validate=validate.OneOf(["pts", "pct"]))

    sl_enabled = fields.Boolean(load_default=False)
    sl_value = fields.Float(allow_none=True)
    sl_unit = fields.String(allow_none=True, validate=validate.OneOf(["pts", "pct"]))

    trail_enabled = fields.Boolean(load_default=False)
    trail_x = fields.Float(allow_none=True)
    trail_y = fields.Float(allow_none=True)
    trail_unit = fields.String(allow_none=True, validate=validate.OneOf(["pts", "pct"]))

    momentum_enabled = fields.Boolean(load_default=False)
    momentum_value = fields.Float(allow_none=True)
    momentum_unit = fields.String(allow_none=True, validate=validate.OneOf(["pts", "pct"]))


# ----------------------------------------------------------------------------
# Webhook actions
# ----------------------------------------------------------------------------


class WebhookRotateSchema(Schema):
    class Meta:
        unknown = RAISE

    confirm = fields.String(
        required=True,
        validate=validate.Length(min=1),
        metadata={"description": "Strategy name as confirmation; must match exactly"},
    )


class WebhookTestSchema(Schema):
    """The test endpoint accepts ANY JSON — it just validates signing
    end-to-end. The body shape is whatever the user has scripted into their
    TradingView/Python alert."""
    class Meta:
        unknown = EXCLUDE


# ----------------------------------------------------------------------------
# Strategy-level risk config (Phase 4)
# ----------------------------------------------------------------------------


class RiskConfigSchema(Schema):
    """Overall (strategy-level) RMS configuration. Abs ₹ only — strategies
    don't carry capital allocation, so % at this scope has no reference.
    See plan §1.1 #4 + §14.2 #2."""
    class Meta:
        unknown = RAISE

    overall_sl_enabled = fields.Boolean(load_default=False)
    overall_sl_abs = fields.Float(allow_none=True, load_default=None)

    overall_target_enabled = fields.Boolean(load_default=False)
    overall_target_abs = fields.Float(allow_none=True, load_default=None)

    lock_profit_enabled = fields.Boolean(load_default=False)
    lock_at_abs = fields.Float(allow_none=True, load_default=None)
    lock_min_abs = fields.Float(allow_none=True, load_default=None)

    trail_to_entry_enabled = fields.Boolean(load_default=False)
    trail_to_entry_threshold = fields.Float(load_default=0.0,
                                            validate=validate.Range(min=0))
    trail_to_entry_unit = fields.String(load_default="pct",
                                        validate=validate.OneOf(["pts", "pct"]))


# ----------------------------------------------------------------------------
# Account-level risk config (Phase 4.5)
# ----------------------------------------------------------------------------


class AccountRiskConfigSchema(Schema):
    """Account-wide RMS — concurrent-run cap, daily loss cap, cooldown,
    debounce, per-strategy daily cap, optional auto-clear time.

    All fields optional / partial — the endpoint supports PATCH-style
    updates by setting only the fields you want to change.
    """
    class Meta:
        unknown = RAISE

    max_concurrent_runs = fields.Integer(
        validate=validate.Range(min=0, max=100), allow_none=True,
    )
    max_daily_loss_abs = fields.Float(allow_none=True)
    cooldown_after_loss_minutes = fields.Integer(
        validate=validate.Range(min=0, max=1440), allow_none=True,
    )
    max_runs_per_strategy_per_day = fields.Integer(
        validate=validate.Range(min=0, max=10000), allow_none=True,
    )
    min_seconds_between_runs = fields.Integer(
        validate=validate.Range(min=0, max=86400), allow_none=True,
    )
    auto_clear_at = fields.String(
        allow_none=True,
        validate=validate.Regexp(r"^[0-2]\d:[0-5]\d$"),
        metadata={"description": "HH:MM IST; lockout self-clears at this time"},
    )
