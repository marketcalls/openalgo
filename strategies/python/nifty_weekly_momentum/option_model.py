"""Pure W+1 option valuation and entry sizing for the momentum strategy."""
from __future__ import annotations

import math
from dataclasses import dataclass


TRADING_SECONDS_PER_YEAR = 252.0 * 6.25 * 60.0 * 60.0


@dataclass(frozen=True)
class OptionQuote:
    bid: float
    ask: float
    bid_size: float
    ask_size: float

    @property
    def midpoint(self) -> float:
        return (self.bid + self.ask) / 2.0


@dataclass(frozen=True)
class ValuationResult:
    allowed: bool
    reason: str
    forward: float = 0.0
    midpoint_iv: float = 0.0
    ask_iv: float = 0.0
    iv_rv_ratio: float = 0.0
    projected_decay: float = 0.0
    all_in_friction: float = 0.0


@dataclass(frozen=True)
class ValuationPolicy:
    rate: float = 0.06
    max_iv_rv_ratio: float = 1.25
    max_ask_iv_premium: float = 0.02
    hold_seconds: float = 1800.0
    crush_fraction: float = 0.10


@dataclass(frozen=True)
class EntryPlan:
    allowed: bool
    reason: str
    lots: int = 0
    quantity: int = 0
    limit_price: float = 0.0
    maximum_limit_price: float = 0.0
    risk_per_lot: float = 0.0
    reserved_risk: float = 0.0


def black76_price(
    forward: float,
    strike: float,
    years_to_expiry: float,
    rate: float,
    volatility: float,
    right: str,
) -> float:
    """Return the discounted Black-76 option value."""
    if forward <= 0 or strike <= 0 or years_to_expiry <= 0 or volatility <= 0:
        return 0.0
    sigma_root_t = volatility * math.sqrt(years_to_expiry)
    if sigma_root_t <= 0:
        return 0.0
    d1 = (math.log(forward / strike) + 0.5 * volatility * volatility * years_to_expiry) / sigma_root_t
    d2 = d1 - sigma_root_t
    discount = math.exp(-rate * years_to_expiry)
    if right == "call":
        return discount * (forward * _normal_cdf(d1) - strike * _normal_cdf(d2))
    if right == "put":
        return discount * (strike * _normal_cdf(-d2) - forward * _normal_cdf(-d1))
    raise ValueError(f"unsupported option right: {right}")


def implied_volatility(
    price: float,
    forward: float,
    strike: float,
    years_to_expiry: float,
    rate: float,
    right: str,
) -> float | None:
    """Invert Black-76 with bounded bisection."""
    if min(price, forward, strike, years_to_expiry) <= 0:
        return None
    discount = math.exp(-rate * years_to_expiry)
    intrinsic = discount * max(
        forward - strike if right == "call" else strike - forward,
        0.0,
    )
    if price <= intrinsic:
        return None

    low = 1e-4
    high = 5.0
    if black76_price(forward, strike, years_to_expiry, rate, high, right) < price:
        return None
    for _ in range(80):
        midpoint = (low + high) / 2.0
        estimate = black76_price(forward, strike, years_to_expiry, rate, midpoint, right)
        if estimate < price:
            low = midpoint
        else:
            high = midpoint
    return (low + high) / 2.0


def realized_volatility(prices: list[tuple[float, float]]) -> float | None:
    """Annualize one-second log-return volatility from ordered observations."""
    if len(prices) < 60:
        return None
    returns: list[float] = []
    for (_, previous), (_, current) in zip(prices, prices[1:]):
        if previous > 0 and current > 0:
            returns.append(math.log(current / previous))
    if len(returns) < 59:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / len(returns)
    return math.sqrt(variance * TRADING_SECONDS_PER_YEAR)


def evaluate_long_option(
    call_quote: OptionQuote,
    put_quote: OptionQuote,
    candidate_right: str,
    strike: float,
    seconds_to_expiry: float,
    realized_vol: float,
    lot_size: int,
    planned_risk: float,
    estimated_fees: float,
    policy: ValuationPolicy = ValuationPolicy(),
) -> ValuationResult:
    """Apply parity, IV/RV, IV-premium, carry, and all-in friction gates."""
    for name, quote in (("call", call_quote), ("put", put_quote)):
        if quote.bid <= 0 or quote.ask <= quote.bid:
            return ValuationResult(False, f"invalid {name} quote")
    if candidate_right not in {"call", "put"}:
        return ValuationResult(False, "invalid candidate right")
    if min(strike, seconds_to_expiry, realized_vol, lot_size, planned_risk) <= 0:
        return ValuationResult(False, "invalid valuation input")

    years = seconds_to_expiry / (365.0 * 24.0 * 60.0 * 60.0)
    discount = math.exp(-policy.rate * years)
    forward = strike + (call_quote.midpoint - put_quote.midpoint) / discount
    if forward <= 0:
        return ValuationResult(False, "parity produced a non-positive forward")

    candidate = call_quote if candidate_right == "call" else put_quote
    midpoint_iv = implied_volatility(
        candidate.midpoint, forward, strike, years, policy.rate, candidate_right
    )
    ask_iv = implied_volatility(
        candidate.ask, forward, strike, years, policy.rate, candidate_right
    )
    if midpoint_iv is None or ask_iv is None:
        return ValuationResult(False, "implied volatility did not converge", forward=forward)

    iv_rv_ratio = midpoint_iv / realized_vol
    if iv_rv_ratio > policy.max_iv_rv_ratio:
        return ValuationResult(
            False,
            f"IV/RV {iv_rv_ratio:.2f} exceeds {policy.max_iv_rv_ratio:.2f}",
            forward,
            midpoint_iv,
            ask_iv,
            iv_rv_ratio,
        )
    if ask_iv - midpoint_iv > policy.max_ask_iv_premium:
        return ValuationResult(
            False,
            f"ask IV premium {ask_iv - midpoint_iv:.4f} exceeds "
            f"{policy.max_ask_iv_premium:.4f}",
            forward,
            midpoint_iv,
            ask_iv,
            iv_rv_ratio,
        )

    remaining_seconds = max(1.0, seconds_to_expiry - policy.hold_seconds)
    shocked_price = black76_price(
        forward,
        strike,
        remaining_seconds / (365.0 * 24.0 * 60.0 * 60.0),
        policy.rate,
        max(0.01, midpoint_iv * (1.0 - policy.crush_fraction)),
        candidate_right,
    )
    projected_decay = max(0.0, candidate.midpoint - shocked_price) * lot_size
    spread_cost = (candidate.ask - candidate.bid) * lot_size
    all_in_friction = spread_cost + estimated_fees + projected_decay

    if projected_decay > planned_risk * 0.10:
        reason = f"projected carry {projected_decay:.2f} exceeds 10% of planned risk"
        return ValuationResult(
            False, reason, forward, midpoint_iv, ask_iv, iv_rv_ratio, projected_decay, all_in_friction
        )
    if all_in_friction > planned_risk * 0.20:
        reason = f"all-in friction {all_in_friction:.2f} exceeds 20% of planned risk"
        return ValuationResult(
            False, reason, forward, midpoint_iv, ask_iv, iv_rv_ratio, projected_decay, all_in_friction
        )

    return ValuationResult(
        True,
        "",
        forward,
        midpoint_iv,
        ask_iv,
        iv_rv_ratio,
        projected_decay,
        all_in_friction,
    )


def build_entry_plan(
    quote: OptionQuote,
    lot_size: int,
    tick_size: float,
    per_trade_risk: float,
    remaining_risk: float,
    capital: float,
    estimated_fees_per_lot: float,
    stop_loss_fraction: float = 0.25,
    spread_threshold_pct: float = 1.5,
    debit_cap_fraction: float = 0.25,
    chase_cap_pct: float = 0.5,
) -> EntryPlan:
    """Create a lot-aligned plan or explain why one lot does not fit."""
    if quote.bid <= 0 or quote.ask <= quote.bid:
        return EntryPlan(False, "invalid option quote")
    if min(lot_size, tick_size, per_trade_risk, remaining_risk, capital) <= 0:
        return EntryPlan(False, "invalid sizing input")
    if quote.ask_size < lot_size:
        return EntryPlan(False, "visible ask size is below one lot")

    midpoint = quote.midpoint
    spread = quote.ask - quote.bid
    maximum_spread = max(2.0 * tick_size, midpoint * spread_threshold_pct / 100.0)
    if spread > maximum_spread + 1e-12:
        return EntryPlan(False, f"spread {spread:.4f} exceeds {maximum_spread:.4f}")

    stop_loss_per_lot = quote.ask * stop_loss_fraction * lot_size
    spread_slippage_per_lot = spread * lot_size
    risk_per_lot = stop_loss_per_lot + spread_slippage_per_lot + estimated_fees_per_lot
    risk_budget = min(per_trade_risk, remaining_risk)
    lots_by_risk = int(risk_budget / risk_per_lot)
    lots_by_debit = int((capital * debit_cap_fraction) / (quote.ask * lot_size))
    lots = min(lots_by_risk, lots_by_debit)
    if lots < 1:
        return EntryPlan(False, f"one-lot risk {risk_per_lot:.2f} exceeds available budget")

    raw_limit = midpoint + spread * 0.5
    limit_price = _round_up(raw_limit, tick_size)
    maximum_limit = _round_down(quote.ask * (1.0 + chase_cap_pct / 100.0), tick_size)
    limit_price = min(limit_price, maximum_limit)
    quantity = lots * lot_size
    return EntryPlan(
        True,
        "",
        lots,
        quantity,
        limit_price,
        maximum_limit,
        risk_per_lot,
        risk_per_lot * lots,
    )


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _round_up(value: float, tick_size: float) -> float:
    return round(math.ceil(value / tick_size - 1e-12) * tick_size, 10)


def _round_down(value: float, tick_size: float) -> float:
    return round(math.floor(value / tick_size + 1e-12) * tick_size, 10)