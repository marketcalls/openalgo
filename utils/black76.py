"""
Black-76 model: pricing, implied volatility, and analytical Greeks
for options on futures/forwards.

Public API matches py_vollib.black call signatures so callers can
swap imports without changing arguments.

Greeks are returned in py_vollib's trader-friendly units:
- theta: daily (formula divided by 365)
- vega:  per 1% absolute change in volatility (formula divided by 100)
- rho:   per 1% absolute change in interest rate (formula divided by 100)
"""

from math import exp, log, sqrt

from scipy.optimize import brentq
from scipy.stats import norm


class BelowIntrinsicException(ValueError):
    """Raised when the observed option price is below intrinsic value (no real IV)."""


def _d1_d2(F, K, t, sigma):
    sqrt_t = sqrt(t)
    d1 = (log(F / K) + 0.5 * sigma * sigma * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    return d1, d2


def _price(flag, F, K, t, r, sigma):
    df = exp(-r * t)
    d1, d2 = _d1_d2(F, K, t, sigma)
    if flag == "c":
        return df * (F * norm.cdf(d1) - K * norm.cdf(d2))
    return df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def implied_volatility(price, F, K, r, t, flag):
    """Solve for sigma given option price under Black-76. Returns decimal vol."""
    df = exp(-r * t)
    if flag == "c":
        intrinsic = df * max(F - K, 0.0)
    else:
        intrinsic = df * max(K - F, 0.0)
    if price < intrinsic - 1e-12:
        raise BelowIntrinsicException(
            f"Option price {price} is below intrinsic value {intrinsic}"
        )

    def objective(sigma):
        return _price(flag, F, K, t, r, sigma) - price

    try:
        return brentq(objective, 1e-6, 5.0, xtol=1e-8, rtol=1e-8, maxiter=100)
    except ValueError as e:
        raise ValueError(f"IV convergence failed: {e}")


def delta(flag, F, K, t, r, sigma):
    df = exp(-r * t)
    d1, _ = _d1_d2(F, K, t, sigma)
    if flag == "c":
        return df * norm.cdf(d1)
    return -df * norm.cdf(-d1)


def gamma(flag, F, K, t, r, sigma):
    df = exp(-r * t)
    d1, _ = _d1_d2(F, K, t, sigma)
    return df * norm.pdf(d1) / (F * sigma * sqrt(t))


def vega(flag, F, K, t, r, sigma):
    df = exp(-r * t)
    d1, _ = _d1_d2(F, K, t, sigma)
    return F * df * norm.pdf(d1) * sqrt(t) / 100.0


def theta(flag, F, K, t, r, sigma):
    df = exp(-r * t)
    d1, d2 = _d1_d2(F, K, t, sigma)
    first = -F * df * norm.pdf(d1) * sigma / (2 * sqrt(t))
    if flag == "c":
        annual = first + r * F * df * norm.cdf(d1) - r * K * df * norm.cdf(d2)
    else:
        annual = first - r * F * df * norm.cdf(-d1) + r * K * df * norm.cdf(-d2)
    return annual / 365.0


def rho(flag, F, K, t, r, sigma):
    return -t * _price(flag, F, K, t, r, sigma) / 100.0
